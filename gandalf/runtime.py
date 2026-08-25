from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field as dataclass_field, replace
from functools import cached_property
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseForm
from django.http import HttpRequest, HttpResponseBase, QueryDict
from django.utils.datastructures import MultiValueDict

from gandalf import tree
from gandalf.context import WizardContext
from gandalf.escapes import Escape
from gandalf.file_storage import FileRef, WizardFileStorage
from gandalf.observers import WizardObserver
from gandalf.types import (
    Context,
    FileRefs,
    RunData,
    Stash,
    State,
    Metadata,
    StateEntry,
    Submission,
    WizardRequest,
    WizardStorage,
)


if TYPE_CHECKING:
    from gandalf.form_views import StepViewClass
    from gandalf.viewsets import WizardViewSet
    from gandalf.wizard import ConfiguredWizard


#: A node in a walked runtime tree. Preserved nodes are the sealed region
#: past the cursor, carried verbatim rather than interpreted.
RuntimeNode: TypeAlias = (
    "RuntimeStep | RuntimeBranch | RuntimeExpand | PreservedBranch | PreservedExpand"
)

#: What a walk can be told to place a submission at: the context a URL
#: resolved to, or a step declaration a caller already holds.
Claim: TypeAlias = "Context | tree.Step"


logger = logging.getLogger(__name__)


#: Django's CSRF form field, dropped from every submission on the way in.
#: `{% csrf_token %}` puts it in each step's form, so a browser posts one
#: with every answer, and it answers nothing: `CsrfViewMiddleware` has
#: already checked it by the time a viewset reads the POST, and a replayed
#: submission is dispatched through a synthetic request no middleware sees.
#: Stored, it would be the session's CSRF secret sitting in state — and
#: `stash()` carries state out of the session that issued it, to wherever
#: the application keeps one.
CSRF_FIELD = "csrfmiddlewaretoken"


def submission_from_post(post: QueryDict) -> Submission:
    """Flatten a POST `QueryDict` into the stored submission shape.

    A key the browser sent more than once — one input per selected value,
    as `CheckboxSelectMultiple` renders — keeps every value it was sent
    with; every other key stores its single value. A stored submission is
    always rebuilt into a `QueryDict` before it reaches a widget, so a
    multi-valued field still reads a list back even when only one value was
    submitted. The CSRF token is dropped rather than stored — see
    `CSRF_FIELD`.
    """
    return {
        key: values[0] if len(values) == 1 else values
        for key, values in post.lists()
        if key != CSRF_FIELD
    }


def _as_post_data(submission):
    """Restore a stored submission to the multi-value mapping widgets read.

    `SelectMultiple` and friends pull their value through `getlist`, which a
    plain dict does not offer: handed one, a `MultipleChoiceField` sees a
    bare string and rejects it with "Enter a list of values".
    """
    data = QueryDict(mutable=True)
    for key, value in submission.items():
        if isinstance(value, (list, tuple)):
            data.setlist(key, list(value))
        else:
            data[key] = value
    return data


class StepNotFound(LookupError):
    """Raised when a context-based edit targets a step that is not on the
    active runtime path or has no stored submission."""


# Version stamp written into every stash envelope, checked on resurrection so
# a payload from a future incompatible format is refused rather than walked.
STASH_VERSION = 1


class InvalidStash(ValueError):
    """Raised when a payload cannot seed a run: not a stash envelope, an
    unsupported version, or a label that does not match the expected one."""


def _without_csrf(submission):
    """A stored submission with any CSRF token dropped.

    Nothing writes one any more — `submission_from_post` drops it as the POST
    is read — so this is for state an earlier version stored, still in flight
    when that landed. Swept on the way into a stash because that is the one
    thing that carries answers out of the session they were given to.
    """
    if not submission or CSRF_FIELD not in submission:
        return submission
    return {key: value for key, value in submission.items() if key != CSRF_FIELD}


def _stripped_for_stash(entries):
    """Return `entries` ready to leave the run: no `files` key at any depth,
    and no CSRF token on any answer.

    A stash outlives the run, but the uploaded bytes do not — completion
    deletes them — so a payload must not carry refs to files that no longer
    exist. The step data itself is kept: on resurrection the walk re-proves
    it without files, so a required file field parks the cursor at that step
    (the correct resume point) while its other answers survive. Recurses
    through branch arms — active and dormant alike, plus the legacy bare-list
    shape — and expansion sub-lists. Builds new structures; never mutates.
    """
    stripped = []
    for entry in entries:
        if "branch" in entry:
            arms = entry["branch"]
            if isinstance(arms, dict):
                entry = {
                    "branch": {
                        arm_id: _stripped_for_stash(arm_entries)
                        for arm_id, arm_entries in arms.items()
                    }
                }
            else:
                entry = {"branch": _stripped_for_stash(arms)}
        elif "expand" in entry:
            entry = {"expand": _stripped_for_stash(entry["expand"])}
        else:
            metadata = entry.get("meta")
            entry = {"step": _without_csrf(entry.get("step"))}
            if metadata:
                entry["meta"] = metadata
        stripped.append(entry)
    return stripped


# Sentinel for "no tree is pinned" — no walk in progress, and no finished
# run being held open. Distinct from `None`, which is a *valid* head: the
# prefix before the very first step is empty, and reading the run from there
# must yield an empty path rather than starting a nested walk.
_NO_WALK = object()


def _open_file_refs(bound_wizard, file_refs):
    if not file_refs:
        return None
    return MultiValueDict(
        {
            field_name: [bound_wizard.file_storage.open(ref)]
            for field_name, ref in file_refs.items()
        }
    )


@dataclass
class RuntimeStep:
    """Runtime mirror of a declared `tree.Step`, carrying per-request state."""

    declaration: tree.Step
    data: Submission | None = None
    files: FileRefs | None = None
    metadata: Metadata | None = None
    next: RuntimeNode | None = None
    bound_wizard: BoundWizard | None = dataclass_field(
        default=None, repr=False, compare=False
    )

    @property
    def name(self) -> str | None:
        """The step's routable name — its `name` context, the `name=`
        `.step()` was declared with. None for a step declared without one."""
        return (self.declaration.context or {}).get("name")

    @property
    def url(self) -> str | None:
        """This step's own URL: a GET renders its answer for editing, so it
        is the "change this" link for a summary page. None without a URL
        reverser (programmatic use — see `BoundWizard.step_url`)."""
        # Every node the walk builds carries its wizard; the default is for
        # nodes built by hand in a test.
        bound_wizard = cast("BoundWizard", self.bound_wizard)
        return bound_wizard.step_url(self.declaration)

    @cached_property
    def form(self) -> BaseForm:
        """Reconstruct a bound, validated form for this step.

        Built once per node: a request that reads a step's answer several
        times — a summary page listing every field, a template reaching for
        `cleaned_data` twice — pays one form validation, not one per read.
        `path` builds fresh nodes on each access, so hold the steps you are
        iterating rather than re-reading `wizard.path` per field.

        Drives the step's `FormView` through its public composition API:
        instantiates the view, calls `view.setup()` with a synthetic POST
        request carrying the stored submission, then returns `view.get_form()`
        after calling `is_valid()` to populate `cleaned_data`. This honors
        `form_class`, `get_form_class()`, `get_form_kwargs()`, `get_initial()`,
        and `get_prefix()` overrides on the user's FormView.

        Note: the synthetic request comes from `bound_wizard.context` — the
        *current* environment, not the one that originally submitted the
        step. For typical single-user flows they're equivalent; for flows
        where one user edits another's run, the actor reflects the editor.

        Customizations beyond composition (overrides of `form_valid()`,
        `post()`, `dispatch()`, or `setup()`) are not surfaced here — `.form`
        does not run the FormView's dispatch pipeline.

        A step whose stored answer escapes from `clean()` still reconstructs,
        but `cleaned_data` only holds the fields cleaned before the raise.
        Raise from `form_valid()` instead when the answer must stay wholly
        readable afterwards.
        """
        form_view_class = cast("StepViewClass", self.declaration.form_view)
        bound_wizard = cast("BoundWizard", self.bound_wizard)
        request = bound_wizard.dispatcher.build_request(
            "POST",
            submission=self.data or {},
            files=_open_file_refs(bound_wizard, self.files),
        )
        view = form_view_class()
        view.setup(request)
        form: BaseForm = view.get_form()
        try:
            form.is_valid()
        except Escape:
            pass
        return form

    def matches_context(self, **context: Any) -> bool:
        return self.declaration.matches_context(**context)

    def accept_reduce(self, reducer: Any) -> Any:
        return reducer.visit_step(self)

    def accept_transform(self, transformer: Any) -> Any:
        next_result = transformer.transform(self.next)
        return transformer.visit_step(self, next_result)


@dataclass
class RuntimeBranch:
    """Runtime mirror of a declared `tree.Branch` along the active path —
    records the selected arm only. Inactive arms are not mirrored in the
    runtime tree; their stored entries ride along verbatim in
    `dormant_arms`, keyed by arm id, so answers survive an arm change and
    are restored when the user flips back. Inspect
    `bound_wizard.wizard.tree` for the full declared structure.
    """

    declaration: tree.Branch
    selected_arm: RuntimeNode | None = None
    selected_arm_id: str | None = None
    dormant_arms: dict[str, State] = dataclass_field(default_factory=dict)
    next: RuntimeNode | None = None

    def accept_reduce(self, reducer: Any) -> Any:
        sub_result = reducer.reduce(self.selected_arm)
        return reducer.visit_branch(self, sub_result)

    def accept_transform(self, transformer: Any) -> Any:
        transformed_arm = transformer.transform(self.selected_arm)
        next_result = transformer.transform(self.next)
        return transformer.visit_branch(self, transformed_arm, next_result)


@dataclass
class PreservedBranch:
    """Verbatim passthrough of a stored branch entry positioned after the
    cursor. The walk cannot select an arm there — branch predicates may
    depend on answers the user has not (re)supplied yet — so the raw entry
    is carried through serialization untouched and re-interpreted on a
    later walk once the steps before it are answered.

    `accept_reduce` returns the raw entry without consulting the reducer,
    so custom `state_serializer_class` hooks do not see sealed regions.
    """

    entry: StateEntry
    next: RuntimeNode | None = None

    # ContextFinder treats nodes carrying a `selected_arm` attribute as
    # runtime branches and skips them when it is None — preserved regions
    # are opaque to context lookups.
    selected_arm: RuntimeNode | None = None

    def accept_reduce(self, reducer: Any) -> StateEntry:
        return self.entry

    def accept_transform(self, transformer: Any) -> Any:
        next_result = transformer.transform(self.next)
        return transformer.visit_preserved_branch(self, next_result)


@dataclass
class RuntimeExpand:
    """Runtime mirror of a declared `tree.Expand`: the subtree its builder
    produced on this walk, mirrored like a branch's selected arm. There are
    no dormant arms — an expansion is a single computed subtree — so its
    stored entries are a plain positional list, `{"expand": [...]}`.
    """

    declaration: tree.Expand
    selected_arm: RuntimeNode | None = None
    next: RuntimeNode | None = None

    def accept_reduce(self, reducer: Any) -> Any:
        sub_result = reducer.reduce(self.selected_arm)
        return reducer.visit_expand(self, sub_result)

    def accept_transform(self, transformer: Any) -> Any:
        transformed_arm = transformer.transform(self.selected_arm)
        next_result = transformer.transform(self.next)
        return transformer.visit_expand(self, transformed_arm, next_result)


@dataclass
class PreservedExpand:
    """Verbatim passthrough of a stored expansion entry positioned after the
    cursor — the counterpart to `PreservedBranch`. The builder is not run
    (it may depend on answers not yet re-supplied), so the raw entry rides
    through serialization untouched and is re-interpreted on a later walk."""

    entry: StateEntry
    next: RuntimeNode | None = None

    # Opaque to context lookups and route iteration, exactly like a
    # preserved branch region.
    selected_arm: RuntimeNode | None = None

    def accept_reduce(self, reducer: Any) -> StateEntry:
        return self.entry

    def accept_transform(self, transformer: Any) -> Any:
        next_result = transformer.transform(self.next)
        return transformer.visit_preserved_expand(self, next_result)


def _expand_sub_entries(entry):
    """The stored entries for an expansion, a plain positional list."""
    if entry is None:
        return []
    return entry["expand"]


def _branch_sub_entries(entry, arm_id):
    """Split a stored branch entry into (active sub-entries, dormant arms)
    for the derived `arm_id`. A bare-list entry is the pre-per-arm legacy
    shape and is treated as belonging to whichever arm is active on this
    walk."""
    if entry is None:
        return [], {}
    stored = entry["branch"]
    if isinstance(stored, list):
        return stored, {}
    dormant = {key: value for key, value in stored.items() if key != arm_id}
    return stored.get(arm_id, []), dormant


def _overlay_file_refs(old_refs, new_refs):
    """Overlay new upload refs over stored ones per field, returning the
    merged mapping plus the stored refs that were replaced (so callers can
    delete them once the new state is safely persisted)."""
    merged = {**old_refs, **new_refs}
    replaced = [old_refs[field] for field in old_refs if field in new_refs]
    return merged, replaced


def _iter_route_steps(node: RuntimeNode | None) -> Iterator[RuntimeStep]:
    """Yield RuntimeStep nodes in active-route order, descending selected
    branch arms inline. Preserved (opaque) branch regions are yielded as
    their PreservedBranch node — the steps inside them are unknowable."""
    while node is not None:
        if isinstance(node, RuntimeStep):
            yield node
        else:
            yield from _iter_route_steps(node.selected_arm)
        node = node.next


def first_route_step(state: RuntimeNode | None) -> RuntimeStep | None:
    """The first `RuntimeStep` on the active route of a walked tree, or None.

    On a complete walk this is where an edit naturally begins — the earliest
    step a URL can render — which is what lets a resurrected run land on a
    step instead of the bare run URL (where a fully-valid run would finish
    immediately).
    """
    return next(_iter_route_steps(state), None)


def _trim_trailing_holes(entries: State) -> State:
    """Drop trailing hole entries so persisted state stays minimal: a
    trailing `{"step": None}` or empty branch slot carries no information
    (walkers treat a missing entry the same way). Interior holes are kept —
    they preserve positional alignment for answered entries that come
    after them."""
    trimmed = list(entries)
    while trimmed and _is_empty_entry(trimmed[-1]):
        trimmed.pop()
    return trimmed


def _is_empty_entry(entry: StateEntry) -> bool:
    if "branch" in entry:
        return not entry["branch"]
    if "expand" in entry:
        return not entry["expand"]
    return entry.get("step") is None and not entry.get("files")


@dataclass(frozen=True)
class Cursor:
    """Position in the wizard where the user currently is — the first step
    whose stored data does not satisfy the step (no data, or invalid data).

    `node` is None when every stored submission validates and there is no
    next step. `response` carries the rendered form when stored data was
    invalid; otherwise the cursor is at an empty slot ready for a GET render.
    `state` is the full runtime tree: validated up to the cursor (with a
    pending submission already placed at the cursor's slot) and carried
    verbatim past it, so serializing it preserves answers positioned after
    the cursor.

    `escapes` records any `Escape` raised while validating a step on this
    walk, as `(declaration, escape)` pairs. An escape counts as satisfying
    its step, so the walk continues past it; only the viewset acts on one,
    and only for the step the user just submitted.
    """

    node: tree.Step | None
    state: RuntimeNode | None
    response: HttpResponseBase | None = None
    escapes: tuple[tuple[tree.Step, Escape], ...] = ()

    def escape_for(self, declaration: tree.Step) -> Escape | None:
        """The escape raised by `declaration` on this walk, or None."""
        for step_declaration, escape in self.escapes:
            if step_declaration is declaration:
                return escape
        return None


@dataclass(frozen=True)
class Walk:
    """What one walk of the tree found.

    `cursor` is where the run ended up. `reached` says whether the walk got
    as far as the step the claim named — the URL is only ever a claim, and
    the sole way to honour one is to arrive at it, which cannot happen
    without validating every step before it. `target` is the runtime step it
    arrived at, or None. `replaced_refs` are stored file refs that a
    placement superseded, to be deleted once the new state is safely
    persisted.
    """

    cursor: Cursor
    reached: bool = False
    target: RuntimeStep | None = None
    replaced_refs: tuple[FileRef, ...] = ()


class Path:
    """The resolved route through a run: the answered steps in walk order,
    with selected branch arms inlined.

    `find_step` / `filter_steps` search only these steps, so they only ever
    see answers that are actually on the taken path — never the current
    (unanswered) step, a step not yet reached, or a step in a preserved or
    dormant branch arm. Iterate it for the steps themselves; it is falsy when
    the run has completed no steps yet.
    """

    def __init__(self, head: RuntimeStep | None) -> None:
        self.head = head

    def __iter__(self) -> Iterator[RuntimeStep]:
        node: RuntimeStep | None = self.head
        while node is not None:
            yield node
            # `PathFlattener` produces a chain of RuntimeStep only.
            node = cast("RuntimeStep | None", node.next)

    def __bool__(self) -> bool:
        return self.head is not None

    def find_step(self, **context: Any) -> RuntimeStep | None:
        """Return the single answered step matching `context`, or None —
        `name=` matches the name `.step(..., name=...)` declared. Raises
        `MultipleStepsReturned` on ambiguity."""
        finder = tree.ContextFinder(context)
        finder.visit(self.head)
        return cast("RuntimeStep | None", finder.one())

    def filter_steps(self, **context: Any) -> list[RuntimeStep]:
        """Return every answered step matching `context` in walk order. Takes
        the same lookups as `find_step`."""
        finder = tree.ContextFinder(context)
        finder.visit(self.head)
        return cast("list[RuntimeStep]", finder.all())


class StepDispatcher:
    """HTTP adapter: builds request snapshots, dispatches step form views,
    decides whether a step's response represents a valid submission, and
    renders a cursor as an HTTP response.
    """

    def __init__(self, bound_wizard: BoundWizard) -> None:
        self._bound_wizard = bound_wizard

    def dispatch(
        self,
        step: tree.Step,
        request: HttpRequest,
        *args: Any,
        initial: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> HttpResponseBase:
        view_kwargs = {} if initial is None else {"initial": initial}
        form_view_class = cast("StepViewClass", step.form_view)
        step_view = form_view_class.as_view(**view_kwargs)
        return step_view(request, *args, **kwargs)

    def build_request(
        self,
        method: str,
        submission: Submission | None = None,
        files: MultiValueDict[str, Any] | None = None,
    ) -> WizardRequest:
        """A request shaped to dispatch one step view with.

        The context supplies the request — a copy of the browser's, or one
        built for a run nobody is browsing — and this shapes it into the
        submission being replayed. Both halves matter and only one of them
        is about HTTP: where a request comes from is the context's business,
        what Django's parsing expects to find on it is this module's.
        """
        request = cast(WizardRequest, self._bound_wizard.context.http_request())
        request.method = method
        if method == "POST":
            request.POST = _as_post_data(submission)
            if files is not None:
                # Where Django's own parsing puts uploads: a synthetic replay
                # request carries its stored files the same way.
                request._files = files  # type: ignore[attr-defined]
        return request

    def response_satisfies_step(self, response: HttpResponseBase) -> bool:
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def render_cursor(
        self, cursor: Cursor, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        if cursor.response is not None:
            return cursor.response
        return self.dispatch(
            # A cursor with no rendered response sits at a step.
            cast(tree.Step, cursor.node),
            self.build_request("GET"),
            *args,
            **kwargs,
        )


class BoundWizard:
    def __init__(
        self,
        context: WizardContext,
        storage: WizardStorage,
        wizard: ConfiguredWizard | None = None,
    ) -> None:
        # `wizard` and `run_id` are both filled in immediately after
        # construction — `bind()` and `initialise()`/`retrieve()` — and every
        # reader runs after that, so they are typed as though always present.
        # Reaching either during the gap in between is a programming error.
        self.wizard: ConfiguredWizard = wizard  # type: ignore[assignment]
        self.context = context
        # The context is the run's environment and the run is the context's
        # subject; each needs the other. Closed once, here, rather than on
        # every synthetic request as `request.wizard = ...` used to be.
        context.run = self
        self.storage = storage
        self.run_id: str = None  # type: ignore[assignment]
        self.urls: WizardViewSet | None = None
        self._partial_runtime_head: Any = _NO_WALK
        self._finished_runtime_head: Any = _NO_WALK
        self._render_context: tuple[Cursor, tree.Step] | None = None
        self._dispatcher: StepDispatcher | None = None
        self._file_storage: WizardFileStorage | None = None
        self._observer: WizardObserver | None = None
        # Memo for one switch's selector while its arm is being chosen.
        self._selector_values: dict[Any, str] = {}

    @property
    def dispatcher(self) -> StepDispatcher:
        if self._dispatcher is None:
            self._dispatcher = self.wizard.step_dispatcher_class(self)
        return self._dispatcher

    @property
    def file_storage(self) -> WizardFileStorage:
        if self._file_storage is None:
            self._file_storage = self.wizard.file_storage_class()
        return self._file_storage

    @property
    def observer(self) -> WizardObserver:
        """This run's observer — the no-op base unless the wizard was
        configured with one. Built once, on first use, and told which run
        it is watching."""
        if self._observer is None:
            self._observer = self.wizard.observer_class(self.run_id)
        return self._observer

    def bind(self, wizard: ConfiguredWizard) -> None:
        self.wizard = wizard

    def initialise(self) -> None:
        self.run_id = self.storage.initialise_run()
        logger.debug("Initialise BoundWizard: %s", self.run_id)

    def retrieve(self, run_id: str) -> None:
        self.run_id = self.storage.retrieve_run(run_id)
        logger.debug("Retrieving BoundWizard: %s", self.run_id)

    def get_run_data(self) -> RunData:
        return self.storage.get_run_data(self.run_id)

    def get_state(self) -> State:
        return self.storage.get_state(self.run_id)

    def stash(self, label: str | None = None) -> Stash:
        """A caller-owned, JSON-safe payload of this run's answers.

        Callable inside `done()` — completion tears the run down only after
        `done()` returns, so the final state is still readable there. File
        refs are stripped (the bytes are deleted at completion); everything
        else rides verbatim, ready to seed a fresh run via `resurrect()`.
        `label` is an opt-in guard: state aligns with the wizard tree
        positionally, so resurrection should be refused when the payload was
        stashed by a differently-shaped wizard.
        """
        payload = {
            "version": STASH_VERSION,
            "state": _stripped_for_stash(self.get_state()),
        }
        if label is not None:
            payload["label"] = label
        return payload

    def resurrect(self, payload: Stash, expected_label: str | None = None) -> str:
        """Seed a fresh run from a stash payload; return the new run id.

        Storage-only — the wizard need not be resolved yet, matching how a
        run always exists before its wizard is bound. The state is deep
        copied so repeated resurrections of one payload yield fully
        independent runs, and the payload is vetted first, so a refusal
        leaves no run behind. Every answer is still re-proved by the walk on
        every request; resurrecting trusts the payload no further than a
        live session's own stored state.
        """
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), list):
            raise InvalidStash("A stash payload is a dict with a state list.")
        if payload.get("version") != STASH_VERSION:
            raise InvalidStash(
                f"Unsupported stash version: {payload.get('version')!r} "
                f"(expected {STASH_VERSION})."
            )
        if expected_label is not None and payload.get("label") != expected_label:
            raise InvalidStash(
                f"Stash label {payload.get('label')!r} does not match "
                f"expected label {expected_label!r}."
            )
        self.initialise()
        self.storage.set_state(self.run_id, deepcopy(payload["state"]))
        return self.run_id

    def obliterate(self) -> None:
        """Forget this run: its uploaded files and its stored state.

        Completion discards state too (see `WizardViewSet.finish`) but
        leaves a tombstone behind, so a revisit can still be answered as
        finished. This removes the run outright, leaving nothing to tell it
        apart from a run that never existed.
        """
        self.cleanup_files()
        self.storage.delete_run(self.run_id)

    def keep_readable(self) -> None:
        """Pin this run's tree, so reading it survives `complete()`.

        `done()` may hand back a `TemplateResponse`, which Django renders
        after the view has returned — by which point the run it describes
        has been tombstoned and its answers discarded. A completion page
        reading the finished run back (the README's re-entrant pattern)
        would find nothing there.

        Pinning the tree keeps the run readable for as long as anything
        holds this `BoundWizard`, which is what lets `WizardViewSet.finish`
        tombstone immediately rather than waiting on a render: a template
        that raises must not leave a run that can fire `done()` again.

        The walk this costs is the run's last. It is taken after `done()`
        has returned so that `done()` still sees a live run, and a `done()`
        that writes state is still walking storage rather than a snapshot
        of it.
        """
        self._finished_runtime_head = self.cursor().state

    def complete(self) -> None:
        """Tombstone this run: its answers are discarded and it is marked
        finished, so `done()` can never fire for it again."""
        self.storage.complete_run(self.run_id)
        self.observer.run_completed()

    @property
    def is_complete(self) -> bool:
        """True once this run has finished and been tombstoned."""
        return self.storage.is_run_complete(self.run_id)

    @property
    def runtime_tree(self) -> RuntimeNode | None:
        """The runtime tree behind the sealed cursor walk: validated up to
        the cursor, carried verbatim past it, with unreached branch regions
        opaque. On a complete run this is the full tree. Reuses a tree
        already pinned — by a walk in progress, or by `keep_readable()` on a
        finished run — then the render context's walk when the viewset
        recorded one; otherwise walks once.

        While a walk is in progress this is the prefix validated so far (see
        `walking()`), because that is the only tree that exists yet — which
        is what lets a branch predicate, an expansion builder, or a step view
        read the run without starting a nested walk.
        """
        if self._partial_runtime_head is not _NO_WALK:
            return cast("RuntimeNode | None", self._partial_runtime_head)
        if self._finished_runtime_head is not _NO_WALK:
            return cast("RuntimeNode | None", self._finished_runtime_head)
        if self._render_context is not None:
            return self._render_context[0].state
        return self.cursor().state

    @property
    def path(self) -> Path:
        """The resolved route as a `Path` — the answered steps in walk order.
        Built from the runtime tree, so anything running inside a walk sees
        the validated prefix so far and `path.find_step(...)` reads prior
        answers.

        Each access rebuilds the step nodes, so a node read from one access
        shares no memoised `.form` with the next: re-reading this per answer
        costs a validation per answer. Outside a render there is no recorded
        cursor to reuse either, so every access walks. Read it once and hold
        the steps you iterate.
        """
        return Path(PathFlattener().transform(self.runtime_tree))

    @contextmanager
    def walking(self, partial_runtime_head: RuntimeNode | None) -> Iterator[None]:
        """Expose `partial_runtime_head` as the runtime tree for the duration
        of the block.

        Everything the walk calls out to — branch predicates, expansion
        builders, and the step views dispatched to validate stored answers —
        runs *inside* a walk. Without this handoff, reading `path` or
        `runtime_tree` from one of them would start a fresh walk, which would
        call out to the same code again and recurse forever. With it, those
        reads see the prefix already validated on this walk: prior answers,
        never the step being visited or anything after it.

        Restores the enclosing head rather than clearing it, so a nested walk
        (a branch arm, an expansion subtree) hands back correctly.
        """
        previous = self._partial_runtime_head
        self._partial_runtime_head = partial_runtime_head
        try:
            yield
        finally:
            self._partial_runtime_head = previous

    def previous_step(
        self, cursor: Cursor, target_declaration: tree.Step
    ) -> RuntimeStep | None:
        """The step immediately before `target_declaration` in active-route
        order on the walked tree behind `cursor`, or None when the target is
        the first step.

        The target is always at or before the cursor — nothing further on can
        be rendered — so every step before it has been walked and its
        predecessor is always knowable."""
        previous = None
        for node in _iter_route_steps(cursor.state):
            if node.declaration is target_declaration:
                return previous
            previous = node
        return None

    def mark_rendering(self, cursor: Cursor, target_declaration: tree.Step) -> None:
        """Record which step this request is rendering, so the navigation
        properties can derive URLs lazily. Called by the viewset before
        dispatching a step render; reuses the cursor it already computed."""
        self._render_context = (cursor, target_declaration)

    def clear_rendering(self) -> None:
        """Forget the recorded render context, so `runtime_tree` and the
        navigation properties stop reusing a walk that a later write has
        invalidated."""
        self._render_context = None

    @property
    def rendering(self) -> tree.Step | None:
        """The declaration of the step this request is rendering, or None
        outside a step render (programmatic use, or a walk in progress).

        A step view that wants to talk about the run it sits in needs to know
        which step *it* is — a summary page listing every answered step would
        otherwise offer to change itself once the run has been round the
        houses and its own answer is stored too.
        """
        if self._render_context is None:
            return None
        return self._render_context[1]

    @property
    def run_url(self) -> str | None:
        """The bare run URL — redirects to the current step, so it works as
        a "return to where I was" link. None without a URL reverser (set by
        the viewset via `bound_wizard.urls`)."""
        if self.urls is None:
            return None
        return self.urls.get_wizard_url(self.run_id)

    def step_url(self, step: RuntimeStep | tree.Step) -> str | None:
        """The URL of `step` — a `RuntimeStep` or the declaration behind one.

        A step URL renders that step pre-filled, so this is the "change this
        answer" link a summary page hangs off each row. Unlike `back_url` it
        needs no render context: any step the caller can name, it can link
        to. None without a URL reverser (set by the viewset via
        `bound_wizard.urls`).
        """
        if self.urls is None:
            return None
        declaration = step.declaration if isinstance(step, RuntimeStep) else step
        segment = self.wizard.step_router_class().reverse(declaration)
        return self.urls.get_step_url(self.run_id, segment)

    def entry_url(self, step: str | None = None) -> str | None:
        """A step URL for this run — never the bare run URL.

        The link *into* a run from outside it: a hub row resuming a section,
        a resurrected stash, a link in an email. The bare run URL redirects
        to wherever the cursor is, and when every stored answer validates
        that is completion, so a GET there fires `done()` before the user has
        touched anything. Naming a step instead makes that impossible.

        `step` is a URL segment, and walks nothing. Without one the run is
        walked once: the cursor's step, or — for a run whose answers all
        validate — the first step on the active route, which is where an edit
        naturally begins. Falls back to the bare run URL only for a wizard
        with no steps at all, where there is nothing else to name and nothing
        to fire either. None without a URL reverser (set by the viewset via
        `bound_wizard.urls`).
        """
        if self.urls is None:
            return None
        if step is not None:
            return self.urls.get_step_url(self.run_id, step)
        cursor = self.cursor()
        if cursor.node is not None:
            return self.step_url(cursor.node)
        first = first_route_step(cursor.state)
        if first is None:
            return self.run_url
        return self.step_url(first.declaration)

    @property
    def back_url(self) -> str | None:
        """The previous active-route step's URL for the step this request
        is rendering. None without a URL reverser or render context
        (programmatic use), at the first step, or when the predecessor is
        hidden inside a preserved branch region."""
        if self.urls is None or self._render_context is None:
            return None
        cursor, target_declaration = self._render_context
        previous = self.previous_step(cursor, target_declaration)
        if previous is None:
            return None
        segment = self.wizard.step_router_class().reverse(previous.declaration)
        return self.urls.get_step_url(self.run_id, segment)

    def walk(
        self,
        *args: Any,
        claim: Claim | None = None,
        submission: Submission | None = None,
        files: FileRefs | None = None,
        metadata: Metadata | None = None,
        **kwargs: Any,
    ) -> Walk:
        """Replay the stored answers in order; where `claim` names a step,
        put `submission` there instead of what is stored; stop at the first
        step that does not hold.

        This is the whole operation. Submitting and editing differ only in
        whether the claimed step already had an answer, which changes nothing
        about the mechanics — so there is one walk, not one per intention.
        Nothing is persisted; the caller decides that from the result.
        """
        walker = self.wizard.cursor_walker_class(
            self.dispatcher,
            self.get_state(),
            args,
            kwargs,
            self,
            claim=claim,
            submission=submission,
            files=files,
            metadata=metadata,
        )
        walker.walk(self.wizard.tree)
        return Walk(
            cursor=walker.cursor(),
            reached=walker.reached,
            target=walker.target,
            replaced_refs=tuple(walker.replaced_refs),
        )

    def persist(self, walk: Walk) -> None:
        """Store the state this walk produced, then drop the file refs it
        superseded — in that order, so nothing deletes a live file."""
        serializer = self.wizard.state_serializer_class()
        self.storage.set_state(self.run_id, serializer.reduce(walk.cursor.state))
        for ref in walk.replaced_refs:
            self.file_storage.delete(ref)

    def cursor(self, *args: Any, **kwargs: Any) -> Cursor:
        """Walk stored state and return the run's current Cursor."""
        return self.walk(*args, **kwargs).cursor

    def render_step(
        self,
        *args: Any,
        target: RuntimeStep | None = None,
        url_kwargs: dict[str, Any] | None = None,
        **context: Any,
    ) -> HttpResponseBase:
        """Render a step pre-filled with its stored submission.

        `target` accepts an already-walked runtime step; without one the run
        is walked with `context` as the claim, so the step only renders if
        the run can actually reach it.
        """
        if url_kwargs is None:
            url_kwargs = {}
        if target is None:
            walk = self.walk(*args, claim=context, **url_kwargs)
            # A reached walk always carries the step it arrived at.
            reached_target = cast(RuntimeStep, walk.target)
            if not walk.reached or reached_target.data is None:
                raise StepNotFound(context)
            target = reached_target
        initial = dict(target.data or {})
        for field, ref in (target.files or {}).items():
            initial[field] = self.file_storage.open(ref)
        return self.dispatcher.dispatch(
            target.declaration,
            self.dispatcher.build_request("GET"),
            *args,
            initial=initial,
            **url_kwargs,
        )

    def store_uploads(
        self, uploaded_files: Mapping[str, UploadedFile]
    ) -> FileRefs | None:
        """Save `uploaded_files` under this run and return their references,
        which is what a submission carries and what state holds.

        `None` rather than `{}` for nothing given, because a walk reads a
        missing `files` as "this submission says nothing about files" and
        keeps whatever the step already had. An empty mapping would mean
        the same thing here, and saying it once is cheaper than relying on
        every caller to know that.
        """
        if not uploaded_files:
            return None
        return {
            field: self.file_storage.save(self.run_id, uploaded_file)
            for field, uploaded_file in uploaded_files.items()
        }

    def delete_file_refs(self, refs: FileRefs | None) -> None:
        for ref in (refs or {}).values():
            self.file_storage.delete(ref)

    def cleanup_files(self) -> None:
        """Remove all files persisted under this run's prefix.

        Intended to be called from `WizardViewSet.done()` overrides after the
        final submission has been consumed. Idempotent on empty runs.
        """
        self.file_storage.delete_run(self.run_id)

    def _build_expansion(
        self, expand_node: tree.Expand, partial_runtime_head: RuntimeNode | None = None
    ) -> tree.Node | None:
        """Run an expansion's builder and return its configured subtree.

        The builder sees the prefix validated so far through the same
        `walking()` handoff a branch predicate uses, so `path.find_step(...)`
        inside it reads prior answers and nothing after the cursor. The
        subtree it returns is configured and vetted (routable names, no
        nested expansion) before it is walked."""
        with self.walking(partial_runtime_head):
            built = expand_node.builder(self.context)
        return self.wizard.configure_expansion(built)

    def _select_branch_arm(
        self, branch_node: tree.Branch, partial_runtime_head: RuntimeNode | None = None
    ) -> tuple[str, tree.Node | None]:
        """Derive the active arm for a branch, returning `(arm_id, subtree)`.

        `arm_id` is the arm's declaration-order index as a string — or, for
        a `Switch`, the name of the case that applies — or `"default"`. It
        is the key the arm's sub-entries are stored under. The decision
        itself is never persisted; only per-arm memory is keyed by it.

        A switch's cases are guards like any other, so the arms are asked
        in order here too; what keeps its selector from running once per
        case is `switch_value`, memoised for this one selection.
        """
        with self.walking(partial_runtime_head):
            self._selector_values = {}
            for index, (predicate, subtree) in enumerate(branch_node.arms):
                if predicate(self.context):
                    return branch_node.arm_id(index), subtree
            return "default", branch_node.default

    def switch_value(self, selector: tree.Selector, context: WizardContext) -> str:
        """What the selector deciding the current switch returned.

        Every case of a switch asks the same question, and the answer
        cannot change midway through choosing an arm — so it is computed
        for the first case that asks and remembered for the rest. A
        selector is free to be expensive; how many cases a switch declares
        should not decide how often it runs.
        """
        if selector not in self._selector_values:
            self._selector_values[selector] = selector(context)
        return self._selector_values[selector]


class CursorWalker(tree.Interpreter):
    """Interpreter that locates the wizard cursor and builds a runtime tree
    mirroring the full declaration tree. Validates stored entries by
    dispatching POSTs through the StepDispatcher; when given a pending
    submission, places it at the cursor's slot.

    Once the cursor is found the walk *seals* instead of stopping: later
    steps carry their stored entries verbatim (no validation — it could not
    be trusted while earlier answers are missing) and later branches become
    `PreservedBranch` passthroughs. Serializing the head therefore keeps
    every answer positioned after the cursor, so an edit that diverts the
    flow only costs the user the steps that genuinely changed."""

    def __init__(
        self,
        dispatcher: StepDispatcher,
        entries: State,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        bound_wizard: BoundWizard,
        claim: Claim | None = None,
        submission: Submission | None = None,
        files: FileRefs | None = None,
        metadata: Metadata | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self._claim = claim
        self._submission = submission
        self._files = files
        self._metadata = metadata
        self._args = args
        self._kwargs = kwargs
        self._head: RuntimeNode | None = None
        self._tail: RuntimeNode | None = None
        self._cursor: Cursor | None = None
        self._escapes: list[tuple[tree.Step, Escape]] = []
        self.reached = False
        self.target: RuntimeStep | None = None
        self.replaced_refs: list[FileRef] = []

    @property
    def _sealed(self):
        return self._cursor is not None

    def _placement(self, stored_files):
        """The submission and the files that go with it.

        Browsers never re-send file inputs, so a submission without a new
        upload keeps the stored refs. The ones it replaces are reported so
        the caller can delete them, but only once the new state is safely
        persisted.
        """
        merged, self.replaced_refs = _overlay_file_refs(
            stored_files or {}, self._files or {}
        )
        return self._submission, (merged or None)

    def _satisfies(self, step, data, files):
        """Dispatch `data` at `step`. Returns whether it satisfies the step,
        and the rendered response when it does not.

        Dispatched behind the `walking()` handoff, so a step view that reads
        `request.wizard` sees the prefix validated so far instead of starting
        a nested walk. `self._head` is the prefix *excluding* this step — it
        is appended only once the dispatch returns — which is exactly the
        "prior answers, never the current step" contract `path` promises.
        """
        if data is None:
            return False, None
        try:
            with self._bound_wizard.walking(self._head):
                response = self._dispatcher.dispatch(
                    step,
                    self._dispatcher.build_request(
                        "POST",
                        submission=data,
                        files=self._open_files(files),
                    ),
                    *self._args,
                    **self._kwargs,
                )
        except Escape as escape:
            # An escape satisfies its step, so the walk carries on past it.
            # Recording it lets the viewset redirect for the live submission;
            # on every later replay it is simply satisfied.
            self._escapes.append((step, escape))
            return True, None
        if self._dispatcher.response_satisfies_step(response):
            return True, None
        return False, response

    def visit_step(self, step: tree.Step) -> None:
        entry = next(self._entries_iter, None)
        stored = entry["step"] if entry is not None else None
        stored_files = entry.get("files") if entry is not None else None
        stored_metadata = entry.get("meta") if entry is not None else None
        if self._sealed:
            self._append(
                RuntimeStep(
                    declaration=step,
                    data=stored,
                    files=stored_files,
                    metadata=stored_metadata,
                    bound_wizard=self._bound_wizard,
                )
            )
            return

        # Reaching the claimed step is the authorisation: the walk only gets
        # here by validating everything before it, so a URL naming a step the
        # run cannot reach never becomes a placement.
        data, files = stored, stored_files
        claimed = not self.reached and self._matches_claim(step)
        if claimed and self._submission is not None:
            data, files = self._placement(stored_files)

        satisfied, response = self._satisfies(step, data, files)
        if claimed and self._submission is not None:
            # Only a placement is a submission. The walk re-proves stored
            # answers on every request, and counting those would count one
            # mistake once per page that follows it.
            self._bound_wizard.observer.submission(step, satisfied, self._metadata)

        node = RuntimeStep(
            declaration=step,
            data=data,
            files=files,
            # A placement replaces what was recorded about the last one:
            # metadata describes the answer that is there now.
            metadata=self._metadata if claimed else stored_metadata,
            bound_wizard=self._bound_wizard,
        )
        self._append(node)
        if claimed:
            self.reached = True
            self.target = node
        if not satisfied:
            self._cursor = Cursor(node=step, state=self._head, response=response)

    def _matches_claim(self, step):
        """Is this the step the claim names?

        A claim is either the context a URL resolved to, or a step
        declaration for callers that already hold one. Without a claim
        nothing is placed — the walk is a plain read.
        """
        if self._claim is None:
            return False
        if isinstance(self._claim, tree.Step):
            return step is self._claim
        return step.matches_context(**self._claim)

    def visit_branch(self, branch: tree.Branch) -> None:
        entry = next(self._entries_iter, None)
        if self._sealed:
            self._append(
                PreservedBranch(entry=entry if entry is not None else {"branch": {}})
            )
            return
        arm_id, arm = self._bound_wizard._select_branch_arm(branch, self._head)
        sub_entries, dormant_arms = _branch_sub_entries(entry, arm_id)
        # A claim is satisfied once; an arm walked after that carries neither
        # the claim nor the submission, so nothing can be placed twice. The
        # files and the metadata travel with the submission wherever it lands:
        # a placement inside an arm is a placement, and it records what it
        # claimed about itself like any other.
        sub = type(self)(
            self._dispatcher,
            sub_entries,
            self._args,
            self._kwargs,
            self._bound_wizard,
            claim=None if self.reached else self._claim,
            submission=None if self.reached else self._submission,
            files=self._files,
            metadata=self._metadata,
        )
        sub.walk(arm)
        self._append(
            RuntimeBranch(
                declaration=branch,
                selected_arm=sub._head,
                selected_arm_id=arm_id,
                dormant_arms=dormant_arms,
            )
        )
        self._escapes.extend(sub._escapes)
        if sub.reached:
            self.reached = True
            self.target = sub.target
            self.replaced_refs = sub.replaced_refs
        if sub._cursor is not None:
            self._cursor = Cursor(
                node=sub._cursor.node,
                state=self._head,
                response=sub._cursor.response,
            )

    def visit_expand(self, expand: tree.Expand) -> None:
        entry = next(self._entries_iter, None)
        if self._sealed:
            self._append(
                PreservedExpand(entry=entry if entry is not None else {"expand": []})
            )
            return
        # Build the subtree from the prefix validated so far — the same
        # partial-tree handoff a branch predicate gets — then walk it inline,
        # exactly like a branch arm. Nothing distinguishes an expanded step
        # from a declared one once it is in the tree.
        subtree = self._bound_wizard._build_expansion(expand, self._head)
        sub = type(self)(
            self._dispatcher,
            _expand_sub_entries(entry),
            self._args,
            self._kwargs,
            self._bound_wizard,
            claim=None if self.reached else self._claim,
            submission=None if self.reached else self._submission,
            files=self._files,
            metadata=self._metadata,
        )
        sub.walk(subtree)
        self._append(RuntimeExpand(declaration=expand, selected_arm=sub._head))
        self._escapes.extend(sub._escapes)
        if sub.reached:
            self.reached = True
            self.target = sub.target
            self.replaced_refs = sub.replaced_refs
        if sub._cursor is not None:
            self._cursor = Cursor(
                node=sub._cursor.node,
                state=self._head,
                response=sub._cursor.response,
            )

    def cursor(self) -> Cursor:
        escapes = tuple(self._escapes)
        if self._cursor is not None:
            return replace(self._cursor, escapes=escapes)
        return Cursor(node=None, state=self._head, escapes=escapes)

    def _open_files(self, file_refs):
        return _open_file_refs(self._bound_wizard, file_refs)

    def _append(self, node):
        if self._head is None:
            self._head = node
        else:
            # A non-empty chain always has a tail.
            cast("RuntimeNode", self._tail).next = node
        self._tail = node


class StateSerializer(tree.Reducer):
    """Bottom-up reducer that flattens a runtime tree into the dict-shaped
    state stored in `request.session`. Branch entries are keyed per arm:
    the active arm's sub-entries land under `selected_arm_id` (omitted
    when empty — a missing key means the arm was never answered) and
    dormant arms are carried back untouched. Trailing holes are trimmed
    at every level."""

    def reduce(self, root: Any) -> State:
        return _trim_trailing_holes(super().reduce(root))

    def visit_step(self, runtime_step: RuntimeStep) -> StateEntry:
        entry: StateEntry = {"step": runtime_step.data}
        if runtime_step.files:
            entry["files"] = runtime_step.files
        if runtime_step.metadata:
            entry["meta"] = runtime_step.metadata
        return entry

    def visit_branch(
        self, runtime_branch: RuntimeBranch, sub_result: State
    ) -> StateEntry:
        arms = dict(runtime_branch.dormant_arms)
        if sub_result:
            # Entries only exist for an arm the walk selected.
            arms[cast(str, runtime_branch.selected_arm_id)] = sub_result
        return {"branch": arms}

    def visit_expand(
        self, runtime_expand: RuntimeExpand, sub_result: State
    ) -> StateEntry:
        return {"expand": sub_result}


class PathFlattener(tree.Transformer):
    """Transformer that turns a runtime tree into a linked chain of
    completed RuntimeStep nodes (the active route). Steps whose `data`
    is None are dropped; branches are spliced by inlining the
    transformed selected arm before the branch's next."""

    def visit_step(
        self, runtime_step: RuntimeStep, next_result: RuntimeStep | None
    ) -> RuntimeStep | None:
        if runtime_step.data is None:
            return next_result
        return replace(runtime_step, next=next_result)

    def visit_preserved_branch(
        self, preserved_branch: PreservedBranch, next_result: RuntimeStep | None
    ) -> RuntimeStep | None:
        return next_result

    def visit_preserved_expand(
        self, preserved_expand: PreservedExpand, next_result: RuntimeStep | None
    ) -> RuntimeStep | None:
        return next_result

    def _splice(
        self,
        transformed_selected_arm: RuntimeStep | None,
        next_result: RuntimeStep | None,
    ) -> RuntimeStep | None:
        if transformed_selected_arm is None:
            return next_result
        tail = transformed_selected_arm
        while tail.next is not None:
            # A flattened arm is a chain of RuntimeStep.
            tail = cast(RuntimeStep, tail.next)
        tail.next = next_result
        return transformed_selected_arm

    def visit_branch(
        self,
        runtime_branch: RuntimeBranch,
        transformed_selected_arm: RuntimeStep | None,
        next_result: RuntimeStep | None,
    ) -> RuntimeStep | None:
        return self._splice(transformed_selected_arm, next_result)

    def visit_expand(
        self,
        runtime_expand: RuntimeExpand,
        transformed_selected_arm: RuntimeStep | None,
        next_result: RuntimeStep | None,
    ) -> RuntimeStep | None:
        return self._splice(transformed_selected_arm, next_result)


class MergeCleanedData(tree.Reducer):
    """Reducer that folds completed step cleaned_data into a single dict
    using last-write-wins on key collisions.

    Intended for `bound_wizard.path` but also works on
    `bound_wizard.runtime_tree`; for each `RuntimeStep` it contributes
    `step.form.cleaned_data`, and any branch sub-fold is merged into the
    accumulator. Subclass and override `combine`, `visit_step`, or
    `visit_branch` for a different merge policy.
    """

    def initial(self) -> dict[str, Any]:
        return {}

    def combine(
        self, accumulator: dict[str, Any], value: dict[str, Any]
    ) -> dict[str, Any]:
        return {**accumulator, **value}

    def visit_step(self, runtime_step: RuntimeStep) -> dict[str, Any]:
        return runtime_step.form.cleaned_data

    def visit_branch(
        self, runtime_branch: RuntimeBranch, sub_result: dict[str, Any]
    ) -> dict[str, Any]:
        return sub_result

    def visit_expand(
        self, runtime_expand: RuntimeExpand, sub_result: dict[str, Any]
    ) -> dict[str, Any]:
        return sub_result
