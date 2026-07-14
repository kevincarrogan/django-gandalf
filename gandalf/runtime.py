import logging
from copy import copy
from dataclasses import dataclass, field as dataclass_field, replace
from http import HTTPStatus
from typing import Any

from django.utils.datastructures import MultiValueDict

from gandalf import tree


logger = logging.getLogger(__name__)


class StepNotFound(LookupError):
    """Raised when a context-based edit targets a step that is not on the
    active runtime path or has no stored submission."""


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
    data: dict | None = None
    files: dict | None = None
    next: "RuntimeStep | RuntimeBranch | None" = None
    bound_wizard: "BoundWizard | None" = dataclass_field(
        default=None, repr=False, compare=False
    )

    @property
    def form(self):
        """Reconstruct a bound, validated form for this step.

        Drives the step's `FormView` through its public composition API:
        instantiates the view, calls `view.setup()` with a synthetic POST
        request carrying the stored submission, then returns `view.get_form()`
        after calling `is_valid()` to populate `cleaned_data`. This honors
        `form_class`, `get_form_class()`, `get_form_kwargs()`, `get_initial()`,
        and `get_prefix()` overrides on the user's FormView.

        Note: the synthetic request is built from `bound_wizard.request` — the
        *current* request, not the request that originally submitted the step.
        For typical single-user flows they're equivalent; for flows where one
        user edits another's run, `request.user` reflects the editor.

        Customizations beyond composition (overrides of `form_valid()`,
        `post()`, `dispatch()`, or `setup()`) are not surfaced here — `.form`
        does not run the FormView's dispatch pipeline.
        """
        form_view_class = self.declaration.form_view
        request = self.bound_wizard.dispatcher.build_request(
            "POST",
            submission=self.data or {},
            files=_open_file_refs(self.bound_wizard, self.files),
        )
        view = form_view_class()
        view.setup(request)
        form = view.get_form()
        form.is_valid()
        return form

    def matches_context(self, **context):
        return self.declaration.matches_context(**context)

    def accept_reduce(self, reducer):
        return reducer.visit_step(self)

    def accept_transform(self, transformer):
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
    selected_arm: "RuntimeStep | RuntimeBranch | None" = None
    selected_arm_id: str | None = None
    dormant_arms: dict = dataclass_field(default_factory=dict)
    next: "RuntimeStep | RuntimeBranch | None" = None

    def accept_reduce(self, reducer):
        sub_result = reducer.reduce(self.selected_arm)
        return reducer.visit_branch(self, sub_result)

    def accept_transform(self, transformer):
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

    entry: dict
    next: "RuntimeStep | RuntimeBranch | PreservedBranch | None" = None

    # ContextFinder treats nodes carrying a `selected_arm` attribute as
    # runtime branches and skips them when it is None — preserved regions
    # are opaque to context lookups.
    selected_arm = None

    def accept_reduce(self, reducer):
        return self.entry


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


def _trim_trailing_holes(entries):
    """Drop trailing hole entries so persisted state stays minimal: a
    trailing `{"step": None}` or empty branch slot carries no information
    (walkers treat a missing entry the same way). Interior holes are kept —
    they preserve positional alignment for answered entries that come
    after them."""
    trimmed = list(entries)
    while trimmed and _is_empty_entry(trimmed[-1]):
        trimmed.pop()
    return trimmed


def _is_empty_entry(entry):
    if "branch" in entry:
        return not entry["branch"]
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
    """

    node: tree.Step | None
    state: RuntimeStep | RuntimeBranch | None
    response: Any = None


class StepDispatcher:
    """HTTP adapter: builds request snapshots, dispatches step form views,
    decides whether a step's response represents a valid submission, and
    renders a cursor as an HTTP response.
    """

    def __init__(self, bound_wizard):
        self._bound_wizard = bound_wizard

    def dispatch(self, step, request, *args, initial=None, **kwargs):
        view_kwargs = {} if initial is None else {"initial": initial}
        step_view = step.form_view.as_view(**view_kwargs)
        return step_view(request, *args, **kwargs)

    def build_request(self, method, submission=None, files=None):
        request = copy(self._bound_wizard.request)
        request.method = method
        request.wizard = self._bound_wizard
        if method == "POST":
            request.POST = submission
            if files is not None:
                request._files = files
        return request

    def response_satisfies_step(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def render_cursor(self, cursor, *args, **kwargs):
        if cursor.response is not None:
            return cursor.response
        return self.dispatch(
            cursor.node,
            self.build_request("GET"),
            *args,
            **kwargs,
        )


class BoundWizard:
    def __init__(self, request, storage, wizard=None):
        self.wizard = wizard
        self.request = request
        self.storage = storage
        self.run_id = None
        self._predicate_runtime_tree = None
        self._dispatcher = None
        self._file_storage = None

    @property
    def dispatcher(self):
        if self._dispatcher is None:
            self._dispatcher = self.wizard.step_dispatcher_class(self)
        return self._dispatcher

    @property
    def file_storage(self):
        if self._file_storage is None:
            self._file_storage = self.wizard.file_storage_class()
        return self._file_storage

    def bind(self, wizard):
        self.wizard = wizard

    def initialise(self):
        self.run_id = self.storage.initialise_run()
        logger.debug("Initialise BoundWizard: %s", self.run_id)

    def retrieve(self, run_id):
        self.run_id = self.storage.retrieve_run(run_id)
        logger.debug("Retrieving BoundWizard: %s", self.run_id)

    def get_run_data(self):
        return self.storage.get_run_data(self.run_id)

    def get_state(self):
        return self.storage.get_state(self.run_id)

    @property
    def runtime_tree(self):
        builder = self.wizard.runtime_tree_builder_class(self, self.get_state())
        builder.walk(self.wizard.tree)
        return builder.head

    @property
    def path(self):
        return PathFlattener().transform(self.runtime_tree)

    def _current_runtime_tree(self):
        if self._predicate_runtime_tree is not None:
            return self._predicate_runtime_tree
        return self.runtime_tree

    def find_step(self, **context):
        finder = tree.ContextFinder(context)
        finder.visit(self._current_runtime_tree())
        return finder.one()

    def find_step_at(self, cursor, **context):
        """Locate a step matching `context` on the walked tree behind
        `cursor` — the validated prefix plus the verbatim-preserved tail.

        Unlike `find_step` this never evaluates branch predicates past the
        cursor, so it is safe on incomplete runs; steps parked in dormant
        arms are not visible (their branch regions are opaque)."""
        finder = tree.ContextFinder(context)
        finder.visit(cursor.state)
        return finder.one()

    def filter_steps(self, **context):
        finder = tree.ContextFinder(context)
        finder.visit(self._current_runtime_tree())
        return finder.all()

    def submit(self, submission, *args, files=None, **kwargs):
        walker = self.wizard.cursor_walker_class(
            self.dispatcher,
            self.get_state(),
            submission,
            args,
            kwargs,
            self,
            pending_files=files,
        )
        walker.walk(self.wizard.tree)
        serializer = self.wizard.state_serializer_class()
        entries = serializer.reduce(walker.cursor().state)
        self.storage.set_state(self.run_id, entries)

    def cursor(self, *args, **kwargs):
        """Walk stored state and return the run's current Cursor."""
        walker = self.wizard.cursor_walker_class(
            self.dispatcher, self.get_state(), None, args, kwargs, self
        )
        walker.walk(self.wizard.tree)
        return walker.cursor()

    def render_edit(self, *args, url_kwargs=None, **context):
        if url_kwargs is None:
            url_kwargs = {}
        runtime_step = self._resolve_edit_target(context)
        initial = dict(runtime_step.data or {})
        for field, ref in (runtime_step.files or {}).items():
            initial[field] = self.file_storage.open(ref)
        return self.dispatcher.dispatch(
            runtime_step.declaration,
            self.dispatcher.build_request("GET"),
            *args,
            initial=initial,
            **url_kwargs,
        )

    def edit(self, submission, *args, files=None, url_kwargs=None, **context):
        """Replace the target step's stored submission and re-validate the run.

        Transactional: the new submission is validated against the target
        step's form view first. On failure (or when the target cannot be
        resolved) the newly stored uploads are deleted while stored state
        and previously persisted file refs stay untouched; a validation
        failure returns the rendered error response. On success the
        submission is spliced into the runtime tree, the walker re-validates
        downstream state, the rebuilt state is persisted, replaced old file
        refs are deleted only after that persist, and None is returned.
        """
        if url_kwargs is None:
            url_kwargs = {}
        runtime = self.runtime_tree
        try:
            runtime_step = self._resolve_edit_target(context, runtime=runtime)
        except StepNotFound:
            self._delete_file_refs(files)
            raise
        response = self._validate_edit(
            runtime_step, submission, files, args, url_kwargs
        )
        if response is not None:
            self._delete_file_refs(files)
            return response
        merged_files, replaced_refs = _overlay_file_refs(
            runtime_step.files or {}, files or {}
        )
        spliced = SpliceSubmission(
            runtime_step, submission, files=merged_files or None
        ).transform(runtime)
        serializer = self.wizard.state_serializer_class()
        rebuilt_entries = serializer.reduce(spliced)
        walker = self.wizard.cursor_walker_class(
            self.dispatcher, rebuilt_entries, None, args, url_kwargs, self
        )
        walker.walk(self.wizard.tree)
        entries = serializer.reduce(walker.cursor().state)
        self.storage.set_state(self.run_id, entries)
        for ref in replaced_refs:
            self.file_storage.delete(ref)
        return None

    def _validate_edit(self, runtime_step, submission, files, args, kwargs):
        """Dispatch the new submission through the target step's form view.

        The request carries the stored files overlaid with the new uploads,
        mirroring what a replay of the accepted edit would see. Returns the
        rendered response when the submission does not satisfy the step,
        None when it does. The error render happens at the step's own URL,
        so resubmitting the corrected form re-targets the same step.
        """
        validation_refs, _ = _overlay_file_refs(
            runtime_step.files or {}, files or {}
        )
        request = self.dispatcher.build_request(
            "POST",
            submission=submission,
            files=_open_file_refs(self, validation_refs),
        )
        response = self.dispatcher.dispatch(
            runtime_step.declaration, request, *args, **kwargs
        )
        if self.dispatcher.response_satisfies_step(response):
            return None
        return response

    def _delete_file_refs(self, refs):
        for ref in (refs or {}).values():
            self.file_storage.delete(ref)

    def cleanup_files(self):
        """Remove all files persisted under this run's prefix.

        Intended to be called from `WizardViewSet.done()` overrides after the
        final submission has been consumed. Idempotent on empty runs.
        """
        self.file_storage.delete_run(self.run_id)

    def _resolve_edit_target(self, context, runtime=None):
        if runtime is None:
            runtime = self.runtime_tree
        finder = tree.ContextFinder(context, require_data=True)
        finder.visit(runtime)
        match = finder.one_with_path()
        if match is None:
            raise StepNotFound(context)
        _, runtime_step = match
        return runtime_step

    def _select_branch_arm(self, branch_node, partial_runtime_head=None):
        """Derive the active arm for a branch, returning `(arm_id, subtree)`.

        `arm_id` is the arm's declaration-order index as a string, or
        `"default"` — the key its sub-entries are stored under. The decision
        itself is never persisted; only per-arm memory is keyed by it.
        """
        request = self.dispatcher.build_request("GET")
        self._predicate_runtime_tree = partial_runtime_head
        try:
            for index, (predicate, subtree) in enumerate(branch_node.arms):
                if predicate(request):
                    return str(index), subtree
            return "default", branch_node.default
        finally:
            self._predicate_runtime_tree = None


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
        dispatcher,
        entries,
        pending_submission,
        args,
        kwargs,
        bound_wizard,
        pending_files=None,
    ):
        self._dispatcher = dispatcher
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self._pending_submission = pending_submission
        self._pending_files = pending_files
        self._args = args
        self._kwargs = kwargs
        self._head: RuntimeStep | RuntimeBranch | None = None
        self._tail: RuntimeStep | RuntimeBranch | None = None
        self._cursor = None

    @property
    def _sealed(self):
        return self._cursor is not None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        stored = entry["step"] if entry is not None else None
        stored_files = entry.get("files") if entry is not None else None
        if not self._sealed:
            if stored is None:
                self._park(step, keep_data=None, keep_files=stored_files)
                return
            response = self._dispatcher.dispatch(
                step,
                self._dispatcher.build_request(
                    "POST",
                    submission=stored,
                    files=self._open_files(stored_files),
                ),
                *self._args,
                **self._kwargs,
            )
            if not self._dispatcher.response_satisfies_step(response):
                self._park(
                    step, keep_data=stored, keep_files=stored_files, response=response
                )
                return
        self._append(
            RuntimeStep(
                declaration=step,
                data=stored,
                files=stored_files,
                bound_wizard=self._bound_wizard,
            )
        )

    def visit_branch(self, branch):
        entry = next(self._entries_iter, None)
        if self._sealed:
            self._append(
                PreservedBranch(entry=entry if entry is not None else {"branch": {}})
            )
            return
        arm_id, arm = self._bound_wizard._select_branch_arm(branch, self._head)
        sub_entries, dormant_arms = _branch_sub_entries(entry, arm_id)
        sub = type(self)(
            self._dispatcher,
            sub_entries,
            self._pending_submission,
            self._args,
            self._kwargs,
            self._bound_wizard,
            pending_files=self._pending_files,
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
        if sub._cursor is not None:
            self._cursor = Cursor(
                node=sub._cursor.node,
                state=self._head,
                response=sub._cursor.response,
            )

    def cursor(self):
        if self._cursor is not None:
            return self._cursor
        return Cursor(node=None, state=self._head)

    def _park(self, step, keep_data, keep_files, response=None):
        """Mark `step` as the cursor; setting it seals the rest of the walk.
        The pending submission lands here; without one, the stored data
        (invalid, or None for a hole) is kept so replay can re-render it
        with errors. Stored file refs are kept unless the pending
        submission replaces them — browsers never re-send file inputs, so
        a correction POST without a new upload must not drop the
        previously stored files."""
        if self._pending_submission is not None:
            data = self._pending_submission
            files, _ = _overlay_file_refs(
                keep_files or {}, self._pending_files or {}
            )
            if not files:
                files = None
        else:
            data, files = keep_data, keep_files
        self._append(
            RuntimeStep(
                declaration=step,
                data=data,
                files=files,
                bound_wizard=self._bound_wizard,
            )
        )
        self._cursor = Cursor(node=step, state=self._head, response=response)

    def _open_files(self, file_refs):
        return _open_file_refs(self._bound_wizard, file_refs)

    def _append(self, node):
        if self._head is None:
            self._head = node
        else:
            self._tail.next = node
        self._tail = node


class StateSerializer(tree.Reducer):
    """Bottom-up reducer that flattens a runtime tree into the dict-shaped
    state stored in `request.session`. Branch entries are keyed per arm:
    the active arm's sub-entries land under `selected_arm_id` (omitted
    when empty — a missing key means the arm was never answered) and
    dormant arms are carried back untouched. Trailing holes are trimmed
    at every level."""

    def reduce(self, root):
        return _trim_trailing_holes(super().reduce(root))

    def visit_step(self, runtime_step):
        entry = {"step": runtime_step.data}
        if runtime_step.files:
            entry["files"] = runtime_step.files
        return entry

    def visit_branch(self, runtime_branch, sub_result):
        arms = dict(runtime_branch.dormant_arms)
        if sub_result:
            arms[runtime_branch.selected_arm_id] = sub_result
        return {"branch": arms}


class PathFlattener(tree.Transformer):
    """Transformer that turns a runtime tree into a linked chain of
    completed RuntimeStep nodes (the active route). Steps whose `data`
    is None are dropped; branches are spliced by inlining the
    transformed selected arm before the branch's next."""

    def visit_step(self, runtime_step, next_result):
        if runtime_step.data is None:
            return next_result
        return replace(runtime_step, next=next_result)

    def visit_branch(self, runtime_branch, transformed_selected_arm, next_result):
        if transformed_selected_arm is None:
            return next_result
        tail = transformed_selected_arm
        while tail.next is not None:
            tail = tail.next
        tail.next = next_result
        return transformed_selected_arm


class MergeCleanedData(tree.Reducer):
    """Reducer that folds completed step cleaned_data into a single dict
    using last-write-wins on key collisions.

    Intended for `bound_wizard.path` but also works on
    `bound_wizard.runtime_tree`; for each `RuntimeStep` it contributes
    `step.form.cleaned_data`, and any branch sub-fold is merged into the
    accumulator. Subclass and override `combine`, `visit_step`, or
    `visit_branch` for a different merge policy.
    """

    def initial(self):
        return {}

    def combine(self, accumulator, value):
        return {**accumulator, **value}

    def visit_step(self, runtime_step):
        return runtime_step.form.cleaned_data

    def visit_branch(self, runtime_branch, sub_result):
        return sub_result


class RuntimeTreeBuilder(tree.Interpreter):
    """Builds a runtime tree mirroring the declaration tree, applying stored
    state data to runtime steps along the active path.

    Unlike `CursorWalker` this never seals: introspection is allowed to
    look ahead past holes (`find_step` on a fresh run locates future
    steps), and per-arm branch memory makes the lookahead lossless — even
    if a predicate past a hole derives a different arm than the entries
    were stored under, the stored sub-entries simply ride along as
    dormant memory."""

    def __init__(self, bound_wizard, entries):
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self.head: RuntimeStep | RuntimeBranch | None = None
        self._tail: RuntimeStep | RuntimeBranch | None = None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        if entry is None:
            data = None
            files = None
        else:
            data = entry["step"]
            files = entry.get("files")
        self._append(
            RuntimeStep(
                declaration=step,
                data=data,
                files=files,
                bound_wizard=self._bound_wizard,
            )
        )

    def visit_branch(self, branch):
        entry = next(self._entries_iter, None)
        arm_id, selected_decl = self._bound_wizard._select_branch_arm(
            branch, self.head
        )
        sub_entries, dormant_arms = _branch_sub_entries(entry, arm_id)

        sub_builder = type(self)(self._bound_wizard, sub_entries)
        sub_builder.walk(selected_decl)

        self._append(
            RuntimeBranch(
                declaration=branch,
                selected_arm=sub_builder.head,
                selected_arm_id=arm_id,
                dormant_arms=dormant_arms,
            )
        )

    def _append(self, node):
        if self.head is None:
            self.head = node
        else:
            self._tail.next = node
        self._tail = node


class SpliceSubmission(tree.Transformer):
    """Transformer over a runtime tree that replaces the `data` (and `files`)
    on a target RuntimeStep (identified by identity) with a new submission.
    All other nodes are structurally cloned."""

    def __init__(self, target, submission, files=None):
        self._target = target
        self._submission = submission
        self._files = files

    def visit_step(self, runtime_step, next_result):
        if runtime_step is self._target:
            data = self._submission
            files = self._files
        else:
            data = runtime_step.data
            files = runtime_step.files
        return RuntimeStep(
            declaration=runtime_step.declaration,
            data=data,
            files=files,
            next=next_result,
            bound_wizard=runtime_step.bound_wizard,
        )

    def visit_branch(self, runtime_branch, transformed_arm, next_result):
        return RuntimeBranch(
            declaration=runtime_branch.declaration,
            selected_arm=transformed_arm,
            selected_arm_id=runtime_branch.selected_arm_id,
            dormant_arms=runtime_branch.dormant_arms,
            next=next_result,
        )


