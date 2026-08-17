"""Drive a wizard from Python: schemas in, submissions in, answers out.

A wizard is normally driven by a person and a browser, but the walk does
not care where a submission came from. What a programmatic caller needs
is small — *what does the current step want, here are its answers, what
has been answered so far, finish the run* — and none of it is HTML. A
data import, a management command, a test, or an AI agent holding
somebody's details can all say exactly that.

Nothing here is a second implementation of anything. Every operation is
the one the viewset performs for a request, so branching, expansion,
dormant memory, escapes and re-validation behave identically whichever
door the run is reached through — including when both doors are used on
the same run, one after the other.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import InMemoryUploadedFile, UploadedFile
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import (
    BaseValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.forms import BaseForm
from django.http import HttpResponseBase

from gandalf import tree
from gandalf.context import WizardContext, WizardSession
from gandalf.escapes import Advance, Escape, Obliterate, Park
from gandalf.file_storage import FileRef
from gandalf.runtime import BoundWizard, Cursor, RuntimeStep, StepNotFound, Walk
from gandalf.summary import _flatten_choices
from gandalf.types import FileRefs, Metadata, Submission
from gandalf.viewsets import WizardViewSet

if TYPE_CHECKING:
    from django.views.generic.edit import FormView

    from gandalf.form_views import StepViewClass

__all__ = [
    "CheckResult",
    "PrefillResult",
    "RunComplete",
    "RunDriver",
    "RunIncomplete",
    "ConfirmationRequired",
    "Placement",
    "StepDescription",
    "SubmitResult",
    "field_json_schema",
    "form_json_schema",
    "outline_steps",
]

# Validation errors as data: `form.errors.get_json_data()`'s shape — field
# name to a list of {"message", "code"} dicts.
Errors = dict[str, list[dict[str, Any]]]


class RunComplete(Exception):
    """Raised when a submission is placed on a run that has already reached
    completion — there is no step left to answer."""


class RunIncomplete(Exception):
    """Raised when `finish()` is called on a run whose cursor still sits at
    a step — `done()` must not fire until every answer holds."""


class ConfirmationRequired(Exception):
    """Raised by `finish()` on a driver that was not told it may conclude a
    run — see `RunDriver.may_finish`."""


def _context(
    context: WizardContext | None,
    actor: Any,
    session: WizardSession | None,
    url_kwargs: dict[str, Any],
) -> WizardContext:
    """The environment a driver runs against.

    Given one, it is used as it stands — except for url kwargs named
    alongside it, which are the one part a caller varies while holding the
    same context. A conversation's context outlives the item it is
    addressing. Otherwise one is built from what the caller named: `actor`
    for a durable storage to scope runs by, `session` to share a
    session-backed one with another driver or with a browser.
    """
    if context is not None:
        return context.addressing(**url_kwargs) if url_kwargs else context
    return WizardContext(actor=actor, session=session, url_kwargs=url_kwargs)


@dataclass(frozen=True)
class Placement:
    """One answered step: everything stored where the answer went.

    A step's entry in state has three parts, and until this they could
    only be read one and a half at a time. `answers` is the cleaned data,
    `files` the stored references to anything uploaded with it, and
    `metadata` whatever the placement recorded about itself — empty when
    it recorded nothing, which is not the same as the step being
    unanswered. A step that is unanswered has no `Placement` at all.

    That distinction is the point. Asking *whose is this answer* used to
    take two reads and a comparison of their key sets, because the
    mapping that held the metadata dropped the steps whose metadata was
    empty and so could not tell "a person answered this" from "nobody
    did".
    """

    answers: dict[str, Any]
    files: FileRefs
    metadata: Metadata


@dataclass(frozen=True)
class StepDescription:
    """Where a run is, described as data a caller can act on.

    `step` is the current step's routable name (None once the run is
    complete), `schema` the JSON Schema of its form, `answers` the cleaned
    data of every answered step keyed by step name, and `errors` the field
    errors of the last submission made through this driver ({} when it
    validated)."""

    step: str | None
    schema: dict[str, Any] | None
    answers: dict[str, dict[str, Any]]
    errors: Errors
    complete: bool


@dataclass(frozen=True)
class SubmitResult:
    """What one submission did.

    `status` is "advanced" (stored; the run moved on), "invalid" (stored
    but not satisfied; `errors` says why), "complete" (stored and it was
    the last answer needed — call `finish()`), or "escaped" (the step
    raised an escape; `escape` names it and the run is wherever the escape
    left it). `next_step` names the step now at the cursor."""

    status: Literal["advanced", "invalid", "complete", "escaped"]
    errors: Errors
    next_step: str | None
    escape: str | None = None


@dataclass(frozen=True)
class PrefillResult:
    """What one `prefill()` pass managed to place.

    `placed` lists the steps filled, in walk order. `errors` holds the
    field errors of an answer that was reached but rejected (the pass stops
    there). `unused` lists answers the walk never asked for — a dormant
    branch arm, a step past a gap, or a run that was already complete.
    `next_step` and `complete` say where the run stands afterwards, and
    `escape` names an escape a placed answer raised."""

    placed: list[str]
    errors: dict[str, Errors]
    unused: list[str]
    next_step: str | None
    complete: bool
    escape: str | None = None


@dataclass(frozen=True)
class CheckResult:
    """What a bag of answers *would* do, worked out without doing it.

    A dry run exists so a caller can ask a person for everything it needs
    in one message rather than discovering the problems one placement at a
    time. Each candidate answer is bound to its step's form and validated
    on its own — no walking, nothing stored.

    `ok` is not a promise. A standalone form knows nothing about the walk,
    so an answer that passes here is still re-proved when it is really
    placed; what `ok` means is "nothing to ask the person about". `missing`
    lists steps the run will certainly reach with no answer to give them —
    steps behind a branch are left out, since asking for every arm would
    be asking for things the person will never be shown. `unchecked` names
    the steps that could not be judged at all, and why. `unknown` holds
    answers naming no declared step: a typo, or a step an expansion has
    not grown yet.
    """

    ok: list[str]
    invalid: dict[str, Errors]
    missing: list[str]
    unchecked: dict[str, str]
    unknown: list[str]


class RunDriver:
    """One wizard run, driven as data.

    The programmatic counterpart of clicking through the forms: `describe()`
    says where the run is and what its current step wants, `submit()` places
    answers (at the cursor, or at any reachable step via `step=`),
    `answers()` reads back everything answered so far, and `finish()` fires
    `done()` once the walk has nothing left to ask. Storage, branching,
    expansion and escapes all behave exactly as they do over HTTP because
    the same walk decides them.
    """

    #: Whether this driver may fire `done()`. False by default, so
    #: `finish()` raises `ConfirmationRequired` until a caller says
    #: otherwise — see `finish()`. Set it per driver (`may_finish=True`) or
    #: on a subclass.
    may_finish: bool = False

    def __init__(
        self,
        view: WizardViewSet,
        bound_wizard: BoundWizard,
        *,
        may_finish: bool | None = None,
    ) -> None:
        self.view = view
        self.bound_wizard = bound_wizard
        self._last_errors: Errors = {}
        if may_finish is not None:
            self.may_finish = may_finish

    @classmethod
    def begin(
        cls,
        viewset_class: type[WizardViewSet],
        *,
        context: WizardContext | None = None,
        actor: Any = None,
        session: WizardSession | None = None,
        may_finish: bool | None = None,
        **url_kwargs: Any,
    ) -> RunDriver:
        """A driver over a fresh run of `viewset_class`'s wizard.

        `actor` is whoever the run is for, which a durable storage scopes
        by; `session` shares a session-backed one with another driver or
        with a browser. Pass a whole `context` instead when you have one —
        url kwargs named beside it still apply, so a context held for a
        conversation can address one item of a collection and then the
        next.
        """
        view, bound_wizard = viewset_class.begin_for(
            _context(context, actor, session, url_kwargs)
        )
        return cls(view, bound_wizard, may_finish=may_finish)

    @classmethod
    def resume(
        cls,
        viewset_class: type[WizardViewSet],
        run_id: str,
        *,
        context: WizardContext | None = None,
        actor: Any = None,
        session: WizardSession | None = None,
        may_finish: bool | None = None,
        **url_kwargs: Any,
    ) -> RunDriver:
        """A driver over an existing run. Raises `RunNotFound` for a run the
        storage does not hold — pass the `session` the run lives in, or the
        `actor` a durable storage scopes it to."""
        view, bound_wizard = viewset_class.inspect_for(
            _context(context, actor, session, url_kwargs), run_id
        )
        return cls(view, bound_wizard, may_finish=may_finish)

    @property
    def run_id(self) -> str:
        return self.bound_wizard.run_id

    def describe(self, *, json_safe: bool = False) -> StepDescription:
        """The run as the agent should see it right now.

        `json_safe` is `answers()`'s, and is here so that a caller
        serialising the whole description does not have to read the answers
        a second time to convert them — reading them is a walk. Everything
        else a description carries is JSON already.
        """
        cursor = self.bound_wizard.cursor()
        # Reading the answers walks for the runtime tree, and this cursor is
        # already holding it. `walking()` hands that tree over for the read,
        # which is the difference between describing a run in one walk and
        # in two. Without it this method pays the very cost `json_safe` is
        # documented above as sparing its caller.
        with self.bound_wizard.walking(cursor.state):
            answers = self.answers(json_safe=json_safe)
        if cursor.node is None:
            return StepDescription(
                step=None, schema=None, answers=answers, errors={}, complete=True
            )
        return StepDescription(
            step=_step_name(cursor.node),
            schema=form_json_schema(self._unbound_form(cursor.node)),
            answers=answers,
            errors=self._last_errors,
            complete=False,
        )

    def placements(self, *, json_safe: bool = False) -> dict[str, Placement]:
        """Every answered step, keyed by step name in walk order.

        The single read of a run: the answers, the files stored with them,
        and what each placement recorded about itself, all from one walk.
        `answers()` is this with the other two dropped, and anything asking
        a question that spans them — *whose is this answer*, *did this step
        carry a file* — should ask here rather than read twice and hope the
        two views line up.

        `json_safe` is `answers()`'s and applies throughout: the answers,
        and the metadata, which is a caller's own mapping and so need not
        have been JSON to begin with.
        """
        # The steps are held once: `path` walks per access, and each node
        # validates its form at most once.
        steps = list(self.bound_wizard.path)
        return {
            cast(str, step.name): self._placement(step, json_safe=json_safe)
            for step in steps
        }

    def _placement(self, step: RuntimeStep, *, json_safe: bool) -> Placement:
        files: FileRefs = dict(step.files or {})
        answers = dict(step.form.cleaned_data)
        metadata = dict(step.metadata or {})
        if json_safe:
            # An uploaded file is not JSON and never will be. Its stored
            # reference is, and names the same bytes — so a caller
            # serialising a run gets told a file is here and which one,
            # where before this it got a `TypeError` and no run at all.
            answers = _json_safe({**answers, **files})
            metadata = _json_safe(metadata)
        return Placement(answers=answers, files=files, metadata=metadata)

    def open_file(self, ref: FileRef) -> InMemoryUploadedFile:
        """Open a file stored with a placement, as the bytes it holds.

        Takes the reference rather than a step and field name, because the
        caller already has one from `placements()` and looking it up again
        would be a second walk for something it is holding.

        This is the read a browser never needs and a driver's caller often
        does: a person uploads a document and hands the run on, and
        whatever picks it up has to be able to look at what was uploaded
        rather than only at the fact that something was. `ref["size"]` is
        there before the bytes are, so a caller that must not read a large
        file can decline without opening it.
        """
        return self.bound_wizard.file_storage.open(ref)

    def answers(self, *, json_safe: bool = False) -> dict[str, dict[str, Any]]:
        """Every answered step's `cleaned_data`, keyed by step name.

        Cleaned values are Python objects rather than the strings they were
        posted as — a `DateField` gives a `datetime.date`. `submit()` takes
        them back as they are, so a step can be read, changed and
        resubmitted without converting anything.

        `json_safe=True` renders those same values as JSON holds them, for
        a caller that has to serialise them — an agent adapter, an API, a
        log. It is the same answers either way; only the values differ, and
        they still feed straight back into `submit()`. Note that it is the
        *cleaned* answer that is rendered, not the raw submission: a ticked
        checkbox is `True` rather than the `"on"` a browser posted.

        There is no sensible default here, which is why it is asked. A
        management command wants the `date`; anything speaking JSON cannot
        hold one.

        The exception to feeding straight back is a file: `json_safe=True`
        renders an uploaded file as the stored reference `placements()`
        carries, because an open file is not JSON, and `submit()` cannot
        take a file back either way. Reading a run that has one works;
        replaying it does not. See `submit()`.
        """
        return {
            name: placement.answers
            for name, placement in self.placements(json_safe=json_safe).items()
        }

    #: Recorded against everything this driver places, unless the caller
    #: says otherwise. A driver is not a person, and the answers alone
    #: cannot say so.
    default_metadata: ClassVar[Metadata] = {"unattended": True}

    def submit(
        self,
        data: dict[str, Any],
        *,
        files: Mapping[str, UploadedFile] | None = None,
        step: str | None = None,
        metadata: Metadata | None = None,
    ) -> SubmitResult:
        """Place `data` (bare field names) at the cursor step, or at the
        step `step` names.

        `metadata` is recorded against the placement and read back from
        `metadata()` — who answered this, and how. Defaults to
        `default_metadata`; pass your own to describe a placement this
        driver is making on somebody else's behalf, or `{}` to record
        nothing at all.

        Values are taken as a browser would have posted them, and the
        cleaned values `answers()` hands back are converted to that form
        first, so a step's answers can be read, changed and submitted
        straight back.

        Raises `RunComplete` when there is nothing left to answer and
        `StepNotFound` when the named step cannot be reached — exactly the
        cases where the submission would otherwise be silently dropped.

        `files` places uploads, keyed by form field name, exactly as a
        multipart POST would — they are saved under the run and the
        submission carries their references. Pass Django's own
        `UploadedFile`; a file belongs in `files` and not in `data`, where
        it would raise, because `data` is stored as state and state is
        JSON.

        Omitting `files` says nothing about files rather than clearing
        them: a step re-answered without them keeps the upload it has, so
        reading a step, changing one field and submitting it back does not
        quietly discard the document attached to it.
        """
        bound_wizard = self.bound_wizard
        if step is None:
            cursor = bound_wizard.cursor()
            if cursor.node is None:
                raise RunComplete(
                    "The run is complete; call finish() rather than submitting."
                )
            declaration: tree.Step | None = cursor.node
            # Claim by name, not by declaration object: a step grown by
            # `.expand()` is rebuilt fresh on every walk, so only its
            # context survives from one walk to the next. Every step has a
            # name — `_validate_routable` refused the wizard otherwise.
            claim: dict[str, Any] = {"name": cast(str, _step_name(cursor.node))}
        else:
            declaration = self._declaration(step)
            claim = {"name": step}
        submission = self._prefixed(declaration, data)
        stored_files = bound_wizard.store_uploads(files or {})
        walk = bound_wizard.walk(
            claim=claim,
            submission=submission,
            files=stored_files,
            metadata=self.default_metadata if metadata is None else metadata,
        )
        if not walk.reached:
            # The uploads were saved before the walk could say whether the
            # step was reachable, so a submission that goes nowhere must
            # take its bytes with it rather than leave them under the run.
            bound_wizard.delete_file_refs(stored_files)
            raise StepNotFound({"name": step})
        target = cast(RuntimeStep, walk.target)
        escape = walk.cursor.escape_for(target.declaration)
        if escape is not None:
            return self._escaped(escape, walk, stored_files)
        bound_wizard.persist(walk)
        next_cursor = self._refresh(walk)
        if target.form.errors:
            self._last_errors = cast(Errors, target.form.errors.get_json_data())
            return SubmitResult(
                status="invalid",
                errors=self._last_errors,
                # An unsatisfied answer keeps the cursor at its step, so a
                # walk that just stored one cannot end complete.
                next_step=_step_name(cast(tree.Step, next_cursor.node)),
            )
        self._last_errors = {}
        if next_cursor.node is None:
            return SubmitResult(status="complete", errors={}, next_step=None)
        return SubmitResult(
            status="advanced", errors={}, next_step=_step_name(next_cursor.node)
        )

    def outline(self) -> list[dict[str, Any]]:
        """The wizard's declared shape as data, before any answers exist.

        Entries are `{"kind": "step", "step": <name>, "schema": ...}`,
        `{"kind": "branch", "arms": [...], "default": [...]}` — all
        *possible* routes are shown, since which arm runs depends on
        answers, and each arm carries its predicate's name and docstring
        (`when` / `description`) alongside its `steps` — and
        `{"kind": "switch", "decided_by": ..., "cases": [...], "default":
        [...]}` — whose cases are *named* outcomes, and which carries a
        `source` naming the deciding step and field when the selector is
        an `on_field` — and `{"kind": "expand"}` — a marker,
        because an expansion's steps do not exist until the answer that
        shapes them does. A step whose view cannot compose its form yet
        (it reads answers that are still missing) carries `schema: None`;
        `describe()` supplies the schema once the walk reaches it. A
        dynamic `get_wizard()` is outlined as currently resolved.
        """
        return self._with_schemas(self.bound_wizard.wizard.outline())

    def prefill(self, answers: dict[str, dict[str, Any]]) -> PrefillResult:
        """Place as many of `answers` (step name → submission) as the tree
        will take, and report the residue.

        Repeatedly submits the cursor step's answer for as long as the bag
        holds one — so a placement that selects a branch arm or grows an
        expansion lets the pass keep consuming answers for the steps it
        just revealed. Stops at the first step the bag cannot answer, the
        first rejected answer, or an escape; the result says what was
        placed, what was rejected and why, what was never asked for, and
        where the run now is.
        """
        remaining = dict(answers)
        placed: list[str] = []
        errors: dict[str, Errors] = {}
        escape: str | None = None

        # One walk to find where the run is; after that each submission
        # already reports where it left the run, so asking again would
        # re-prove every stored answer to learn what was just returned.
        cursor = self.bound_wizard.cursor()
        step = None if cursor.node is None else _step_name(cursor.node)
        complete = cursor.node is None

        while step is not None and step in remaining:
            result = self.submit(remaining.pop(step))
            if result.status == "invalid":
                errors[step] = result.errors
                step = result.next_step
                break
            if result.status == "escaped":
                escape = result.escape
                # An escape leaves the run wherever its disposition put it,
                # and only a walk can say where that is.
                cursor = self.bound_wizard.cursor()
                step = None if cursor.node is None else _step_name(cursor.node)
                complete = cursor.node is None
                break
            placed.append(step)
            complete = result.status == "complete"
            step = result.next_step

        return PrefillResult(
            placed=placed,
            errors=errors,
            unused=list(remaining),
            next_step=step,
            complete=complete,
            escape=escape,
        )

    def check(self, answers: dict[str, dict[str, Any]]) -> CheckResult:
        """Judge `answers` against the wizard without placing any of them.

        Nothing is walked and nothing is stored: each candidate is bound to
        its own step's form and validated alone. That is weaker than a real
        placement — see `CheckResult` — but it is the only way to learn
        about a problem behind a step that has not been answered yet, and
        so the only way to ask a person for everything at once.
        """
        remaining = dict(answers)
        ok: list[str] = []
        invalid: dict[str, Errors] = {}
        missing: list[str] = []
        unchecked: dict[str, str] = {}
        answered = self.answers()
        for declaration, conditional in self._declared_steps(
            self.bound_wizard.wizard.tree, conditional=False
        ):
            name = cast(str, _step_name(declaration))
            if name in remaining:
                status, payload = self._check_step(declaration, remaining.pop(name))
                if status == "ok":
                    ok.append(name)
                elif status == "invalid":
                    invalid[name] = payload
                else:
                    unchecked[name] = payload
            elif not conditional and name not in answered:
                missing.append(name)
        return CheckResult(
            ok=ok,
            invalid=invalid,
            missing=missing,
            unchecked=unchecked,
            unknown=list(remaining),
        )

    def _declared_steps(
        self, node: tree.Node | None, conditional: bool
    ) -> Iterator[tuple[tree.Step, bool]]:
        """Every declared step, flagged with whether reaching it depends on
        an answer. An expansion has no static subtree to descend into."""
        while node is not None:
            if isinstance(node, tree.Step):
                yield node, conditional
            elif isinstance(node, tree.Branch):
                for _, arm in node.arms:
                    yield from self._declared_steps(arm, conditional=True)
                yield from self._declared_steps(node.default, conditional=True)
            node = node.next

    def _check_step(
        self, declaration: tree.Step, data: dict[str, Any]
    ) -> tuple[str, Any]:
        try:
            form = self._bound_form(declaration, data)
            form.is_valid()
        except Escape as escape:
            # A check is a question, not a submission: an escape raised
            # here is reported and emphatically not acted on.
            return "unchecked", (
                f"validating it raised {type(escape).__name__.lower()}, which "
                "a check does not act on — place the answer to escape"
            )
        except Exception as error:
            return "unchecked", (
                "its form cannot be built from the answers available yet "
                f"({type(error).__name__})"
            )
        if form.errors:
            return "invalid", cast(Errors, form.errors.get_json_data())
        return "ok", {}

    def _bound_form(self, declaration: tree.Step, data: dict[str, Any]) -> BaseForm:
        """The step's form, bound to `data` — composed exactly as a real
        placement composes it, so the same overrides apply."""
        form_view_class = cast("StepViewClass", declaration.form_view)
        request = self.bound_wizard.dispatcher.build_request(
            "POST", submission=self._prefixed(declaration, data)
        )
        view = form_view_class()
        view.setup(request)
        form: BaseForm = view.get_form()
        return form

    def finish(self) -> HttpResponseBase:
        """Fire `done()` and retire the run — `WizardViewSet.finish()`,
        guarded twice: a run whose cursor still sits at a step refuses, and
        so does a driver that was not told it may conclude one.

        `done()` is where the irreversible things live, and a driver is the
        unattended path by definition — somebody clicking Confirm reaches
        `finish()` through the viewset's own dispatch, never through here.
        So concluding a run is opt-in, per driver:

            RunDriver.begin(QuoteViewSet, may_finish=True)

        It is a plain flag rather than anything cleverer because the
        interesting question is *when* it should be true, not how to spell
        it, and that answer belongs to the caller. Agreement collected
        before the answers exist is not agreement about the answers, so a
        caller that means "once somebody has seen these" should construct
        the driver at the point it knows that, rather than teaching the
        library the rule.
        """
        cursor = self.bound_wizard.cursor()
        if cursor.node is not None:
            raise RunIncomplete(
                f"The run is still at step {_step_name(cursor.node)!r}."
            )
        if not self.may_finish:
            raise ConfirmationRequired(
                "This driver may not conclude a run; hand it back so a "
                "person can confirm it, or construct the driver with "
                "may_finish=True."
            )
        return self.view.finish(self.bound_wizard)

    def _refresh(self, walk: Walk) -> Cursor:
        """Where the run is now that this walk has been persisted.

        A dynamic `get_wizard()` reads stored state, so a write can change
        the tree the walk was made against: answering the step that decides
        a shape — a count, a branch key — yields a tree that does not yet
        hold the steps it implies, and judging the run against the stale
        one would call it finished mid-way.

        So the wizard is re-resolved, and *only* when that produces a
        different tree is the run walked again. When it does not — which is
        every static wizard, meaning almost every wizard — the walk just
        performed already ended at the run's new position, and walking a
        second time would re-prove every stored answer to learn what is
        already known. That doubling is what `benchmarks/driven.py`
        measures.
        """
        previous = self.bound_wizard.wizard
        self.view._resolve_wizard(self.bound_wizard)
        if self.bound_wizard.wizard is previous:
            return walk.cursor
        return self.bound_wizard.cursor()

    def _escaped(
        self, escape: Escape, walk: Walk, files: FileRefs | None = None
    ) -> SubmitResult:
        """Settle what the escape leaves behind — the viewset's dispositions
        without the redirect (the caller gets the escape's name instead)."""
        if isinstance(escape, Obliterate):
            self.bound_wizard.obliterate()
        elif isinstance(escape, Advance):
            self.bound_wizard.persist(walk)
            self._refresh(walk)
        elif isinstance(escape, Park):
            # Nothing was persisted, so the uploads this submission brought
            # have nowhere to belong.
            self.bound_wizard.delete_file_refs(files)
        else:
            raise ImproperlyConfigured(
                "Raise Park, Advance or Obliterate to escape a wizard; "
                f"{type(escape).__name__} names no disposition for the run."
            )
        self._last_errors = {}
        return SubmitResult(
            status="escaped",
            errors={},
            next_step=None,
            escape=type(escape).__name__.lower(),
        )

    def _declaration(self, step_name: str) -> tree.Step | None:
        """The declared step `step_name` names, or None for one the static
        tree does not hold (a step grown by `.expand()`)."""
        finder = tree.ContextFinder({"name": step_name})
        finder.visit(self.bound_wizard.wizard.tree)
        return cast("tree.Step | None", finder.one())

    def _prefixed(
        self, declaration: tree.Step | None, data: dict[str, Any]
    ) -> Submission:
        """Map bare field names through the step view's form prefix, so the
        caller never has to know one is configured — and reduce the values to
        the ones a browser would have posted."""
        data = _json_safe(data)
        if declaration is None:
            return data
        prefix = self._view_for(declaration).get_prefix()
        if prefix is None:
            return data
        return {f"{prefix}-{name}": value for name, value in data.items()}

    def _view_for(self, declaration: tree.Step) -> FormView[Any]:
        form_view_class = cast("StepViewClass", declaration.form_view)
        view = form_view_class()
        view.setup(self.bound_wizard.dispatcher.build_request("GET"))
        return view

    @classmethod
    def outline_for(
        cls,
        viewset_class: type[WizardViewSet],
        *,
        context: WizardContext | None = None,
        actor: Any = None,
        session: WizardSession | None = None,
        **url_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """The shape of `viewset_class`'s wizard, without starting a run.

        What a caller deciding whether to begin needs: the journey ahead,
        answerable before there is anything to answer it with. No run is
        created, so nothing is left behind by asking — which matters to a
        caller describing several wizards to choose between them.
        """
        view, bound_wizard = viewset_class.resolve_for(
            _context(context, actor, session, url_kwargs)
        )
        driver = cls(view, bound_wizard)
        return driver._with_schemas(bound_wizard.wizard.outline())

    def _with_schemas(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Swap each step's declaration for a JSON Schema of its form.

        The half of an outline that needs a request rather than only the
        declaration: building a form runs the step view's composition API,
        which is where a schema comes from.
        """
        described = []
        for entry in entries:
            entry = dict(entry)
            if entry["kind"] == "step":
                entry["step"] = entry.pop("name")
                entry["schema"] = self._schema_or_none(entry.pop("declaration"))
                entry.pop("context")
            elif entry["kind"] == "branch":
                entry["arms"] = [
                    {**arm, "steps": self._with_schemas(arm["steps"])}
                    for arm in entry["arms"]
                ]
                entry["default"] = self._with_schemas(entry["default"])
            elif entry["kind"] == "switch":
                entry["cases"] = [
                    {**case, "steps": self._with_schemas(case["steps"])}
                    for case in entry["cases"]
                ]
                entry["default"] = self._with_schemas(entry["default"])
            described.append(entry)
        return described

    def _schema_or_none(self, declaration: tree.Step) -> dict[str, Any] | None:
        # A hand-written FormView composes its form through arbitrary user
        # code that may read answers the run does not hold yet; any failure
        # means "no schema until reached", not a broken outline.
        try:
            return form_json_schema(self._unbound_form(declaration))
        except Exception:
            return None

    def _unbound_form(self, declaration: tree.Step) -> BaseForm:
        """The step's form, unbound, through the view's composition API — a
        GET-shaped request, so no phantom "this field is required" errors."""
        form: BaseForm = self._view_for(declaration).get_form()
        return form


def _step_name(declaration: tree.Step) -> str | None:
    return cast("str | None", (declaration.context or {}).get("name"))


def _json_safe(data: dict[str, Any]) -> dict[str, Any]:
    """`data` with every value rendered as one JSON can hold.

    Used at both of the driver's doors, for reasons that are the same
    mechanism and different problems.

    Going *in*, a submission is stored with the run's state, and state is
    JSON. Over HTTP that holds for free — a POST is strings — but a
    driver's caller has richer values to hand, and the obvious source of
    them is `answers()`, which returns `cleaned_data`: a `DateField` gives
    a `datetime.date`. Read a step's answers, change one field, submit the
    result, and until this converted them the date went in unremarked and
    the run only failed later, when its state was written, by which time
    nothing could say which answer was at fault.

    Coming *out*, the same values have to reach a caller that speaks JSON
    and nothing else — which is most of what a driver is for.

    `DjangoJSONEncoder` renders exactly the types Django's own fields
    produce — dates, times, decimals, UUIDs — in the form those fields
    parse back, so a value survives the trip out and in again as itself. A
    value it cannot render still raises, but at the door it was handed to.
    """
    return cast("dict[str, Any]", json.loads(json.dumps(data, cls=DjangoJSONEncoder)))


def outline_steps(entries: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Every step an outline declares, however deeply an arm buries it.

    An outline is a tree, not a list of steps: a branch carries `arms`, a
    switch carries `cases`, and both may carry a `default`. So a caller
    that wants to ask something of every step — how many are there, does
    any of them take a file, is one of them named this — has to recurse,
    and every caller was writing the same eight lines to do it.

    Yields the step entries themselves rather than their names, because
    the interesting question is usually about the `schema` beside the
    name. Order is the declared one, arms before what follows them.

    A plain function over plain data on purpose. An outline is JSON by
    the time most callers see it — it has been through a tool call, an
    API, a log — so the thing that walks it must not need the driver that
    produced it.

    An `expand` entry yields nothing: the steps it grows do not exist
    until an answer makes them, and describing them before that would be
    inventing them.
    """
    for entry in entries:
        if entry["kind"] == "step":
            yield entry
        for arm in entry.get("arms", []) + entry.get("cases", []):
            yield from outline_steps(arm["steps"])
        yield from outline_steps(entry.get("default") or [])


def form_json_schema(form: BaseForm) -> dict[str, Any]:
    """Describe `form` as a JSON Schema object.

    Property names are the form's bare field names — the driver owns any
    prefixing — and `required` lists the fields Django would reject an
    empty answer for. `additionalProperties` is false so a schema-checked
    caller learns about a misspelled field before validation does.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, field in form.fields.items():
        properties[name] = field_json_schema(field)
        if field.required:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def field_json_schema(field: forms.Field) -> dict[str, Any]:
    """Describe one form field as a JSON Schema property.

    The mapping is deliberately submission-shaped: it describes what to
    *send* (choice values as posted, dates as ISO strings), not what
    `cleaned_data` holds afterwards. A field kind this module does not
    understand degrades to a string with a note saying so, because the
    walk will still validate whatever is sent.
    """
    schema, note = _base_schema(field)
    pattern = _pattern(field, schema)
    if pattern is not None:
        schema["pattern"] = pattern
    if field.label is not None:
        schema["title"] = str(field.label)
    # The author's words and this module's stay apart. Joined into one
    # sentence there was no telling a step's own guidance from a remark
    # generated here, and only one of the two is ever the author's to change
    # — or anybody else's to say differently.
    if field.help_text:
        schema["description"] = str(field.help_text)
    if note is not None:
        schema["x-note"] = note
    return schema


def _base_schema(field: forms.Field) -> tuple[dict[str, Any], str | None]:
    """The type-shaped half of a field's schema, plus an optional note
    destined for the property's `x-note`."""
    # `ModelMultipleChoiceField` subclasses `ModelChoiceField` rather than
    # `MultipleChoiceField`, so it would otherwise fall through to the
    # single-choice branch below and be described as a string. It takes a
    # list, like its non-model sibling, and belongs here with it.
    if isinstance(field, (forms.MultipleChoiceField, forms.ModelMultipleChoiceField)):
        values, legend = _choice_values(field)
        array_schema: dict[str, Any] = {
            "type": "array",
            "items": {"type": "string", "enum": values},
        }
        # `type: array` says a list is allowed, not that anything has to be in
        # it. Where the field is required the floor is one, and without this
        # only the prose ever said so.
        if field.required:
            array_schema["minItems"] = 1
        return array_schema, legend
    if isinstance(field, forms.ChoiceField):
        values, legend = _choice_values(field)
        return {"type": "string", "enum": values}, legend
    # Before `BooleanField`, which it subclasses. Its `validate()` is a no-op,
    # so it never rejects anything: true, false and none are all answers and
    # `required` decides nothing. Its parent's `const: true` would say the
    # opposite.
    if isinstance(field, forms.NullBooleanField):
        return {"type": ["boolean", "null"]}, None
    if isinstance(field, forms.BooleanField):
        boolean_schema: dict[str, Any] = {"type": "boolean"}
        # A required BooleanField is "you must tick this": the only value
        # that validates is true, so the schema pins it.
        if field.required:
            boolean_schema["const"] = True
        return boolean_schema, None
    # FloatField and DecimalField subclass IntegerField, so the wider
    # number kinds are picked off first.
    if isinstance(field, (forms.FloatField, forms.DecimalField)):
        return _bounded_schema({"type": "number"}, field), None
    if isinstance(field, forms.IntegerField):
        return _bounded_schema({"type": "integer"}, field), None
    if isinstance(field, forms.DateTimeField):
        return {"type": "string", "format": "date-time"}, None
    if isinstance(field, forms.DateField):
        return {"type": "string", "format": "date"}, None
    if isinstance(field, forms.TimeField):
        return {"type": "string", "format": "time"}, None
    if isinstance(field, forms.EmailField):
        return _string_schema(field, format="email"), None
    # Before `CharField`, which it subclasses. Its `URLValidator` is a
    # `RegexValidator` carrying a kilobyte of alternation; `format` says the
    # same thing in the vocabulary a reader already knows.
    if isinstance(field, forms.URLField):
        return _string_schema(field, format="uri"), None
    if isinstance(field, forms.CharField):
        return _string_schema(field), None
    # `ImageField` and friends subclass this, so the whole family is caught.
    if isinstance(field, forms.FileField):
        # `format: binary` is how a JSON Schema says "this is a file", and
        # it is the only part of this a caller should ever branch on. The
        # note beside it is prose for whoever reads it — a person or a
        # model — and prose is a bad thing to make load-bearing.
        #
        # It is said at all because the generic note below is actively
        # wrong here: a file is the one answer that cannot travel in a
        # submission, so telling a caller to send its raw value sends it
        # to the one door that refuses it.
        return {"type": "string", "format": "binary"}, (
            "This field takes an uploaded file. A file cannot be sent as "
            "part of a submission — supply it alongside one, keyed by this "
            "field name."
        )
    return {"type": "string"}, (
        f"{type(field).__name__} is not supported by the schema mapping; "
        "submit its raw form value."
    )


def _pattern(field: forms.Field, schema: dict[str, Any]) -> str | None:
    """The regex a field enforces, where the schema can carry it.

    Without this a format lives only in the help text, which makes a sentence
    load-bearing: reword it and the field becomes unanswerable without the
    schema having changed at all.

    A `format` already in hand wins — it says what the pattern would say, and
    says it in the vocabulary a reader already knows.
    """
    if schema.get("type") != "string" or "format" in schema:
        return None
    for validator in field.validators:
        if isinstance(validator, RegexValidator):
            # Annotated `str | Pattern[str]`, but `__init__` compiles whatever
            # it was given, so by the time anyone holds one it is a pattern.
            compiled = cast("re.Pattern[str]", validator.regex)
            return compiled.pattern
    return None


def _bounded_schema(
    schema: dict[str, Any], field: forms.IntegerField
) -> dict[str, Any]:
    minimum = _bound(field, MinValueValidator, field.min_value, max)
    if minimum is not None:
        schema["minimum"] = minimum
    maximum = _bound(field, MaxValueValidator, field.max_value, min)
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def _bound(
    field: forms.IntegerField,
    validator_class: type[BaseValidator],
    declared: Any,
    tightest: Callable[[list[Any]], Any],
) -> Any:
    """The tightest of a field's declared bound and any it validates for.

    `min_value=` is sugar for a `MinValueValidator`, so a field may carry a
    bound either way, and a field given the validator directly was being
    described as though it had no bound at all. Django runs everything it
    holds, so where both exist an answer has to satisfy both.

    A `limit_value` that is callable is left out: it has no value to state
    until it is called, and calling it would mean evaluating somebody's code
    in order to describe a form.
    """
    limits = [] if declared is None else [declared]
    for validator in field.validators:
        if isinstance(validator, validator_class) and not callable(
            validator.limit_value
        ):
            limits.append(validator.limit_value)
    return tightest(limits) if limits else None


def _string_schema(field: forms.CharField, **extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", **extra}
    if field.max_length is not None:
        schema["maxLength"] = field.max_length
    if field.min_length is not None:
        schema["minLength"] = field.min_length
    return schema


def _choice_values(field: forms.ChoiceField) -> tuple[list[str], str]:
    pairs = list(_flatten_choices(field.choices))
    # The empty choice is a prompt — "Select..." — rather than an answer, and
    # a required field rejects it. Advertising it would invite a caller to
    # send the one value the field is certain to refuse. Where the field is
    # optional it really is submittable: it is how somebody says nothing.
    if field.required:
        pairs = [(value, label) for value, label in pairs if str(value) != ""]
    values = [str(value) for value, _ in pairs]
    legend = ", ".join(f"{value} ({label})" for value, label in pairs)
    return values, f"Choices: {legend}."
