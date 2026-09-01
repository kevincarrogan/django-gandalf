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
import logging
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from itertools import islice
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import UploadedFile
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
from gandalf.file_storage import FileRef, StoredUpload
from gandalf.form_views import answer_errors, answer_submission
from gandalf.runtime import (
    Run,
    Cursor,
    RunMetadata,
    RuntimeStep,
    StepNotFound,
    Walk,
)
from gandalf.summary import _flatten_choices
from gandalf.types import Answer, FileRefs, JourneyStore, Metadata, Submission
from gandalf.add_another import AddAnotherPage, AddAnotherViewSet
from gandalf.tasklists import (
    Entry,
    EntryNotFound,
    Journey,
    Row,
    TaskListViewSet,
)
from gandalf.viewsets import DoorRefused, WizardViewSet

if TYPE_CHECKING:
    from django.views.generic.edit import FormView

    from gandalf.form_views import StepViewClass

__all__ = [
    "CheckResult",
    "MAX_DESCRIBED_CHOICES",
    "PrefillResult",
    "RunComplete",
    "RunDriver",
    "JourneyDriver",
    "JourneyIncomplete",
    "RunIncomplete",
    "ConfirmationRequired",
    "DoorRefused",
    "Placement",
    "StepDescription",
    "SubmitResult",
    "field_json_schema",
    "form_json_schema",
    "outline_steps",
]

logger = logging.getLogger(__name__)

# Validation errors as data: `form.errors.get_json_data()`'s shape — field
# name to a list of {"message", "code"} dicts.
Errors = dict[str, list[dict[str, Any]]]

#: How many of a choice field's values a description will list. Past this it
#: says there are more instead of naming them, because a description travels
#: to a model and a reference table does not belong in a prompt. See
#: `field_json_schema`.
MAX_DESCRIBED_CHOICES = 50


class RunComplete(Exception):
    """Raised when a submission is placed on a run that has already reached
    completion — there is no step left to answer."""


class JourneyIncomplete(Exception):
    """Raised when `JourneyDriver.submit()` is called on a journey with a
    row still to finish — the page refuses its own button there."""


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

    answers: Answer
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
    answers: dict[str, Answer]
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
        run: Run,
        *,
        may_finish: bool | None = None,
    ) -> None:
        self.view = view
        self.run = run
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
        conversation can address one item of an add-another list and then
        the next.
        """
        view, run = viewset_class.begin_driven_for(
            _context(context, actor, session, url_kwargs)
        )
        return cls(view, run, may_finish=may_finish)

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
        view, run = viewset_class.inspect_driven_for(
            _context(context, actor, session, url_kwargs), run_id
        )
        return cls(view, run, may_finish=may_finish)

    @property
    def run_id(self) -> str:
        return self.run.run_id

    def describe(self, *, json_safe: bool = False) -> StepDescription:
        """The run as the agent should see it right now.

        `json_safe` is `answers()`'s, and is here so that a caller
        serialising the whole description does not have to read the answers
        a second time to convert them — reading them is a walk. Everything
        else a description carries is JSON already.
        """
        cursor = self.run.cursor()
        # Reading the answers walks for the runtime tree, and this cursor is
        # already holding it. `walking()` hands that tree over for the read,
        # which is the difference between describing a run in one walk and
        # in two. Without it this method pays the very cost `json_safe` is
        # documented above as sparing its caller.
        with self.run.walking(cursor.state):
            answers = self.answers(json_safe=json_safe)
        if cursor.node is None:
            return StepDescription(
                step=None, schema=None, answers=answers, errors={}, complete=True
            )
        return StepDescription(
            step=_step_name(cursor.node),
            schema=self._schema_for(cursor.node),
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
        steps = list(self.run.path)
        return {
            cast(str, step.name): self._placement(step, json_safe=json_safe)
            for step in steps
        }

    def _placement(self, step: RuntimeStep, *, json_safe: bool) -> Placement:
        files: FileRefs = dict(step.files or {})
        answers = dict(step.answer) if isinstance(step.answer, dict) else step.answer
        metadata = dict(step.metadata or {})
        if json_safe:
            # An uploaded file is not JSON and never will be. Its stored
            # reference is, and names the same bytes — so a caller
            # serialising a run gets told a file is here and which one,
            # where before this it got a `TypeError` and no run at all.
            # A step whose answer is not a mapping has nowhere to fold a
            # file into; its files are listed on the placement regardless.
            if isinstance(answers, dict):
                answers = {**answers, **files}
            answers = _json_safe(answers)
            metadata = _json_safe(metadata)
        return Placement(answers=answers, files=files, metadata=metadata)

    @property
    def metadata(self) -> RunMetadata:
        """This run's metadata bag — what the run did outside itself.

        The same bag a step view or `done()` reads, so a driver picking up a
        run somebody else started sees the record that run created, and one
        that starts a run sees whatever `run_started()` put there. Read and
        written as a dict; see `RunMetadata`.

        Not `placements()`. That carries what each *placement* claimed about
        itself — `{"unattended": True}` and the like — which is a fact about
        an answer. This is a fact about the run.
        """
        return self.run.metadata

    def open_file(self, ref: FileRef) -> StoredUpload:
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
        return self.run.file_storage.open(ref)

    def answers(self, *, json_safe: bool = False) -> dict[str, Answer]:
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
        data: Answer,
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
        run = self.run
        if step is None:
            cursor = run.cursor()
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
        submission = self._submission(declaration, data)
        stored_files = run.store_uploads(files or {})
        walk = run.walk(
            claim=claim,
            submission=submission,
            files=stored_files,
            metadata=self.default_metadata if metadata is None else metadata,
        )
        if not walk.reached:
            # The uploads were saved before the walk could say whether the
            # step was reachable, so a submission that goes nowhere must
            # take its bytes with it rather than leave them under the run.
            run.delete_file_refs(stored_files)
            raise StepNotFound({"name": step})
        target = cast(RuntimeStep, walk.target)
        escape = walk.cursor.escape_for(target.declaration)
        if escape is not None:
            return self._escaped(escape, walk, stored_files)
        run.persist(walk)
        next_cursor = self._refresh(walk)
        errors = target.errors
        if errors:
            self._last_errors = errors
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
        `describe()` supplies the schema once the walk reaches it, and
        `schema_unavailable` beside it names the exception's class — a
        step that could not be described has to be tellable from one that
        asks nothing. A dynamic `get_wizard()` is outlined as currently
        resolved.
        """
        return self._with_schemas(self.run.wizard.outline())

    def prefill(self, answers: dict[str, Answer]) -> PrefillResult:
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
        cursor = self.run.cursor()
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
                cursor = self.run.cursor()
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

    def check(self, answers: dict[str, Answer]) -> CheckResult:
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
            self.run.wizard.tree, conditional=False
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

    def _check_step(self, declaration: tree.Step, data: Answer) -> tuple[str, Any]:
        try:
            view = self._bound_view(declaration, data)
            if getattr(view, "consumes_what_it_checks", False):
                # The one question a dry run must not ask. Validating this
                # step performs its check, and its check cannot be
                # performed twice — so judging the candidate would spend
                # the very thing being judged, and record no proof of
                # having done so, leaving the real placement to fail on an
                # answer that was right when it was offered.
                return "unchecked", (
                    "validating it performs a check that cannot be performed "
                    "twice, which a check does not do — place the answer to "
                    "perform it"
                )
            form = view.get_form()
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
        errors = answer_errors(view, form)
        if errors:
            return "invalid", errors
        return "ok", {}

    def _bound_view(self, declaration: tree.Step, data: Answer) -> FormView[Any]:
        """The step's view, set up with `data` — composed exactly as a real
        placement composes it, so the same overrides apply.

        The view rather than just its form, because what a step refused is
        the view's to say: a formset's `errors` is truthy when every row is
        valid, so a check reading it directly concludes the opposite of the
        truth."""
        form_view_class = cast("StepViewClass", declaration.form_view)
        request = self.run.dispatcher.build_request(
            "POST", submission=self._submission(declaration, data)
        )
        view = form_view_class()
        view.setup(request)
        return view

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
        cursor = self.run.cursor()
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
        return self.view.finish(self.run)

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
        previous = self.run.wizard
        self.view._resolve_wizard(self.run)
        if self.run.wizard is previous:
            return walk.cursor
        return self.run.cursor()

    def _escaped(
        self, escape: Escape, walk: Walk, files: FileRefs | None = None
    ) -> SubmitResult:
        """Settle what the escape leaves behind — the viewset's dispositions
        without the redirect (the caller gets the escape's name instead)."""
        if isinstance(escape, Obliterate):
            self.run.obliterate()
        elif isinstance(escape, Advance):
            self.run.persist(walk)
            self._refresh(walk)
        elif isinstance(escape, Park):
            # Nothing was persisted, so the uploads this submission brought
            # have nowhere to belong.
            self.run.delete_file_refs(files)
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
        finder.visit(self.run.wizard.tree)
        return cast("tree.Step | None", finder.one())

    def _submission(self, declaration: tree.Step | None, answer: Answer) -> Submission:
        """`answer` as the POST that would have produced it.

        Asked of the step view (`get_submission()`), so the caller never
        has to know that a prefix is configured, or that a formset is
        posted as a management form and n numbered rows. Values are reduced
        to the ones a browser would have sent first, because that is true
        whatever shape the step answers in.
        """
        answer = _json_safe(answer)
        if declaration is None:
            return cast("Submission", answer)
        return answer_submission(self._view_for(declaration), answer)

    def _view_for(self, declaration: tree.Step) -> FormView[Any]:
        form_view_class = cast("StepViewClass", declaration.form_view)
        view = form_view_class()
        view.setup(self.run.dispatcher.build_request("GET"))
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

        What a caller deciding whether to begin needs: the whole wizard
        ahead, answerable before there is anything to answer it with. No run is
        created, so nothing is left behind by asking — which matters to a
        caller describing several wizards to choose between them.
        """
        view, run = viewset_class.resolve_for(
            _context(context, actor, session, url_kwargs)
        )
        driver = cls(view, run)
        return driver._with_schemas(run.wizard.outline())

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
                entry.update(self._outline_schema(entry.pop("declaration")))
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

    def _outline_schema(self, declaration: tree.Step) -> dict[str, Any]:
        """The `schema` half of one step's outline entry.

        Composing a step's form and describing the form it composed fail
        for different reasons, and only the first is the application's to
        fail at: a hand-written `FormView` builds its form through
        arbitrary user code that may read answers the run does not hold
        yet, so *no schema until reached* is the truthful answer for a step
        the walk has not come to. Describing carries no such excuse — the
        form object is in hand — so a failure there is the library's, and
        it raises rather than passing for a step that asks nothing.

        The two used to be one swallow, which is how a formset went a
        release describing itself as `None` here while `describe()` raised
        on the same step (#109). Nothing failed, so nothing was noticed.
        """
        try:
            view, form = self._compose_form(declaration)
        except Exception as exc:
            # Kept out of the entry itself: the message can quote answers,
            # and an outline is read by a model. The class is enough to
            # tell a failure from an absence; the log has the rest.
            logger.debug(
                "Outline could not compose the form for step %r",
                _step_name(declaration),
                exc_info=True,
            )
            return {
                "schema": None,
                "schema_unavailable": (
                    "This step's form could not be built from where the run "
                    f"stands ({type(exc).__name__}). That is expected of a "
                    "view composing its form from answers the run does not "
                    "hold yet, and the step describes itself once the walk "
                    "reaches it — but the cause is not known here, and a "
                    "view that fails for its own reasons reads the same."
                ),
            }
        return {"schema": self._describe_form(view, form)}

    def _schema_for(self, declaration: tree.Step) -> dict[str, Any]:
        """The step as JSON Schema, asked of its view."""
        return self._describe_form(*self._compose_form(declaration))

    def _compose_form(self, declaration: tree.Step) -> tuple[FormView[Any], Any]:
        """The step's view and the form object it builds — user code, both.

        The half of describing a step that can legitimately fail before the
        walk arrives, which is why it is a method of its own rather than
        two lines of `_schema_for`.
        """
        view = self._view_for(declaration)
        # GET-shaped, so no phantom "this field is required" errors.
        return view, view.get_form()

    def _describe_form(self, view: FormView[Any], form: Any) -> dict[str, Any]:
        """`form` as JSON Schema, asked of the view that built it.

        The view built the form object, so it is the one that knows how to
        describe it — `form_json_schema()` walks `form.fields`, which only
        a `BaseForm` has. A step declared with a bare Django `FormView` has
        no say and gets the form reading.
        """
        builder = getattr(view, "get_answer_schema", None)
        if builder is None:
            return form_json_schema(form)
        return cast("dict[str, Any]", builder(form))


class JourneyDriver:
    """A task list driven without a browser.

    `RunDriver` drives one run. A journey is several of them, and which are
    open, which are finished and what the whole thing is still waiting on
    are the page's to say — so until this the only way to ask was to render
    it. What that cost is visible in the demo, which reached into
    `get_items()` and `add_item()` from its own toolset because the library
    offered nothing; that is the shape of a gap rather than of a recipe.

    Everything here goes through the page's own methods, so a `get_entries()`
    that chooses per user, an `entry_hidden()` that spans rows, a
    `get_entry_status()` an application overrode — all of them apply, and a
    driver sees the page the person would.

        journey = JourneyDriver.begin(GrantApplicationViewSet, actor=user)
        contact = journey.section("contact", may_finish=True)
        contact.prefill({"name": {"full_name": "Ada"}})
        journey.url   # where to send them to check it over

    `submit()` is guarded like `RunDriver.finish()` and for the same
    reason — `journey_done()` is where the irreversible things live.
    """

    #: Whether this driver may fire `journey_done()`. False by default, so
    #: `submit()` raises `ConfirmationRequired` until a caller says
    #: otherwise.
    may_submit: bool = False

    def __init__(
        self,
        journey: Journey,
        context: WizardContext,
        *,
        may_submit: bool | None = None,
    ) -> None:
        self.journey = journey
        self.context = context
        if may_submit is not None:
            self.may_submit = may_submit

    @classmethod
    def begin(
        cls,
        task_list_viewset: type[TaskListViewSet],
        *,
        context: WizardContext | None = None,
        actor: Any = None,
        session: WizardSession | None = None,
        journey: str | None = None,
        may_submit: bool | None = None,
        **url_kwargs: Any,
    ) -> JourneyDriver:
        """A driver over a fresh journey on `task_list_viewset`.

        `TaskListViewSet.begin()` takes a request and this takes a context,
        which is the whole difference. It used to be a bigger one: this
        fabricated a request to get through a request-shaped door, and the
        mount kwargs had to be handed over twice — once to the context and
        again to `begin()` — because the door read them from somewhere the
        context could not reach. `begin_for()` takes the context whole.

        `journey` names one instead of having one made up, for a page
        mounted under a `<journey>` segment. A page without one keeps a
        single journey per session and ignores it — see `Journey.id`.
        """
        environment = _context(context, actor, session, url_kwargs)
        return cls(
            task_list_viewset.begin_for(environment, journey),
            environment,
            may_submit=may_submit,
        )

    @classmethod
    def resume(
        cls,
        task_list_viewset: type[TaskListViewSet],
        journey_id: str,
        *,
        context: WizardContext | None = None,
        actor: Any = None,
        session: WizardSession | None = None,
        may_submit: bool | None = None,
        **url_kwargs: Any,
    ) -> JourneyDriver:
        """A driver over a journey that already exists.

        There is nothing to retrieve — a journey is a key, and its record
        is whatever has been written under it — so an id naming nothing
        yields an empty page rather than raising. That is what the page
        does with the same id, and a journey nobody has answered is a real
        state rather than a missing one.
        """
        environment = _context(context, actor, session, url_kwargs)
        return cls(
            Journey(task_list_viewset, environment, journey_id),
            environment,
            may_submit=may_submit,
        )

    @property
    def journey_id(self) -> str:
        """This journey's identity — the key its page reads, which for a
        page with no `<journey>` segment is its fixed one."""
        return self.journey.id

    @property
    def url(self) -> str:
        """The page. The handover, one level up from `run.entry_url()`: an
        agent that has filled what it can hands this over and the person
        picks up where the rows say they are."""
        return self.journey.url

    @property
    def store(self) -> JourneyStore:
        """The journey's record — its section runs, stashes and data."""
        return self.journey.store

    @property
    def page(self) -> TaskListViewSet:
        """The page, set up for this journey. Rebuilt per access because it
        caches its rows, and a driver that placed an answer since must not
        report the page as it was before."""
        view = self.journey.task_list_viewset()
        view.setup(self.context.http_request(), **self.journey.page_kwargs)
        return view

    @property
    def is_complete(self) -> bool:
        """Whether every row is complete — whether `submit()` would run."""
        return self.page.get_page().is_complete

    @classmethod
    def outline_for(
        cls,
        task_list_viewset: type[TaskListViewSet],
        *,
        context: WizardContext | None = None,
        actor: Any = None,
        session: WizardSession | None = None,
        **url_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """The declared shape of a whole journey, without beginning one.

        `RunDriver.outline_for()` one level up, and for the same reason: a
        caller deciding what to ask for needs everything the journey will
        want, before there is anything to answer it with. Every entry gives
        its `key`, `title` and `kind`; a section gives `steps`, which is
        that wizard's own outline, and a group gives `entries`, which is
        this again.

        Declaration-level throughout, so nothing here depends on a journey
        existing — including which entries are listed. A `hidden()` that
        turns on an answer hides a row from `rows()`, not from this.
        """
        environment = _context(context, actor, session, url_kwargs)
        view = task_list_viewset()
        view.setup(environment.http_request(), **url_kwargs)
        return cls._outline(view, environment)

    @classmethod
    def _outline(
        cls, page: TaskListViewSet, context: WizardContext
    ) -> list[dict[str, Any]]:
        entries = []
        for entry in page.get_entries():
            described: dict[str, Any] = {
                "key": entry.key,
                "title": str(page.get_entry_title(entry)),
                "kind": _entry_kind(entry),
            }
            viewset = entry.viewset
            if viewset is not None and issubclass(viewset, TaskListViewSet):
                # A group or an add-another: a page in its own right, so
                # what it holds is this again rather than a list of steps.
                nested = viewset()
                nested.setup(context.http_request(), **page.entry_url_kwargs(entry))
                described["entries"] = cls._outline(nested, context)
            elif viewset is not None:
                described["steps"] = RunDriver.outline_for(
                    viewset, context=context, **page.entry_url_kwargs(entry)
                )
            # A `Link` has no viewset and so neither key: it names somewhere
            # else, and what is over there is not this journey's to describe.
            entries.append(described)
        return entries

    def outline(self) -> list[dict[str, Any]]:
        """`outline_for()` for this journey's page."""
        return self._outline(self.page, self.context)

    def rows(self) -> tuple[Row, ...]:
        """The page as a person would see it: one `Row` per listed entry,
        with its title, its status and where its link goes.

        Hidden entries are absent, exactly as they are for the person — a
        hidden entry is not a row.
        """
        return self.page.get_page().rows

    def section(self, key: str, *, may_finish: bool | None = None) -> RunDriver:
        """A `RunDriver` over the entry `key` names — resuming its run, or
        starting one.

        The page resolves the entry's viewset and its URL kwargs, so a
        caller names the row rather than knowing which viewset a `Section`
        generated and which kwargs it takes.

        Raises `EntryNotFound` for a key this page does not list, and
        `DoorRefused` for one it will not open: `check_door()` is the
        section's, so a blocked or hidden section, or a submitted journey,
        refuses here exactly as it does at the page's own door.
        """
        page = self.page
        return self._entry_driver(page, page.get_entry(key), may_finish)

    def _entry_driver(
        self, page: TaskListViewSet, entry: Entry, may_finish: bool | None
    ) -> RunDriver:
        """A driver over one entry's run: the recorded one, or a fresh one.

        Resume before begin, for the reason `enter()` gives: a second run
        on every access would leave the first one's answers unreachable.
        """
        viewset = page.entry_viewset(entry)
        url_kwargs = page.entry_url_kwargs(entry)
        store = page.get_journey_store()
        run_id = store.get_run(page.full_key(entry))
        if run_id is not None:
            return RunDriver.resume(
                viewset,
                run_id,
                context=self.context,
                may_finish=may_finish,
                **url_kwargs,
            )
        driver = RunDriver.begin(
            viewset, context=self.context, may_finish=may_finish, **url_kwargs
        )
        # What `enter()` does, and the reason a section's run is findable at
        # all: a run nobody recorded is one the page cannot show as
        # Incomplete and the next caller cannot resume.
        store.set_run(page.full_key(entry), driver.run_id)
        return driver

    def _list(self, key: str) -> AddAnotherViewSet:
        """The add-another page behind the entry `key` names."""
        page = self.page
        entry = page.get_entry(key)
        viewset = entry.viewset
        if viewset is None or not issubclass(viewset, AddAnotherViewSet):
            raise EntryNotFound(
                f"{key!r} is not a list: only an AddAnother entry has items."
            )
        view = viewset()
        view.setup(self.context.http_request(), **page.entry_url_kwargs(entry))
        return view

    def items(self, key: str) -> AddAnotherPage:
        """The add-another entry `key` names, as its own page: a row per
        item, and whether the person has said there are no more."""
        return self._list(key).get_items()

    def add(self, key: str, *, may_finish: bool | None = None) -> RunDriver:
        """Put a new item on the list `key` names, and drive it.

        One call, rather than adding an item and then reading the ids back
        to work out which one is new. Registering an item enters it, which
        starts its run, so this resumes that one rather than starting a
        second — which is what `enter()` does for the same reason.
        """
        page = self._list(key)
        page.add_item()
        item_id = page.get_item_ids()[-1]
        return self._entry_driver(page, page.get_item_entry(item_id), may_finish)

    def remove(self, key: str, item_id: str) -> None:
        """Take an item off the list: its run, its stash, its title and its
        place in the registry, exactly as the person's Remove does."""
        self._list(key).remove_item(item_id)

    def submit(self) -> HttpResponseBase:
        """Press the page's button: `journey_done()`, then the tombstone.

        Guarded twice, as `RunDriver.finish()` is. A journey with a row
        still to finish raises `JourneyIncomplete` — the page refuses its
        own button there and says so on the page, and a driver has no page
        to say it on. And a driver that was not told it may conclude one
        raises `ConfirmationRequired`, because `journey_done()` is where
        the irreversible things live and a driver is the unattended path by
        definition.
        """
        if not self.may_submit:
            raise ConfirmationRequired(
                "This driver may not submit a journey. Pass may_submit=True, "
                "or hand the person `url` and let them press it."
            )
        page = self.page
        if not page.get_page().is_complete:
            raise JourneyIncomplete(
                "The journey has rows still to finish; `rows()` says which."
            )
        return page.submit()


def _entry_kind(entry: Entry) -> str:
    """An entry's kind as a word: what a caller branches on before it looks
    at anything else. Taken from the declared class, which is where the
    author said it."""
    return {
        "Section": "section",
        "AddAnother": "add-another",
        "Group": "group",
        "Link": "link",
    }.get(type(entry).__name__, type(entry).__name__.lower())


def _step_name(declaration: tree.Step) -> str | None:
    return cast("str | None", (declaration.context or {}).get("name"))


def _json_safe(data: Any) -> Any:
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
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


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

    A field that carries `json_schema()` is asked instead of guessed at —
    the one place a project's own field can say what it takes, once, rather
    than each step rewriting its whole schema to describe it.
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
    destined for the property's `x-note`.

    A field carrying `json_schema()` says this itself and is believed —
    before the ladder below, so a field may correct a description it would
    otherwise have been given rather than only supply a missing one. It
    replaces the type-shaped half only: `title`, `description` and the rest
    are added around it either way, so a field cannot lose its own label by
    answering. And the note is dropped, because the note apologises for not
    knowing.
    """
    described = getattr(field, "json_schema", None)
    if described is not None:
        return cast("dict[str, Any]", described()), None
    # `ModelMultipleChoiceField` subclasses `ModelChoiceField` rather than
    # `MultipleChoiceField`, so it would otherwise fall through to the
    # single-choice branch below and be described as a string. It takes a
    # list, like its non-model sibling, and belongs here with it.
    if isinstance(field, (forms.MultipleChoiceField, forms.ModelMultipleChoiceField)):
        # The values belong to the items, so the enum — or the note saying
        # there is no enum — belongs on the items too.
        items, legend = _choice_schema(field)
        array_schema: dict[str, Any] = {"type": "array", "items": items}
        # `type: array` says a list is allowed, not that anything has to be in
        # it. Where the field is required the floor is one, and without this
        # only the prose ever said so.
        if field.required:
            array_schema["minItems"] = 1
        return array_schema, legend
    if isinstance(field, forms.ChoiceField):
        return _choice_schema(field)
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
    if "pattern" in schema:
        # The field stated one itself, which is the last word on it.
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


def _choice_schema(field: forms.ChoiceField) -> tuple[dict[str, Any], str]:
    """What one of a choice field's values may be, and the prose naming them.

    The choices are read lazily and stopped one past `MAX_DESCRIBED_CHOICES`.
    A `ModelChoiceField`'s `choices` is a queryset in disguise, so listing
    them ran it — and `RunDriver.outline_for()` describes every declared
    step, so a reference table was read once per such field per description,
    and arrived in the prompt as an enum of primary keys beside a legend of
    `str(obj)`.

    Past the cap the enum is dropped rather than cut short, because a short
    enum that does not say it is short is worse than none: a caller reads
    `enum` as the whole list and rules out every value below the cut. What
    is left says so twice over — `x-choices-omitted` for a reader that
    branches on the schema, prose beside it for one that reads.

    A field whose values are worth listing however many there are says so
    with a `json_schema()` of its own, which is asked before any of this.
    """
    pairs = _flatten_choices(field.choices)
    # The empty choice is a prompt — "Select..." — rather than an answer, and
    # a required field rejects it. Advertising it would invite a caller to
    # send the one value the field is certain to refuse. Where the field is
    # optional it really is submittable: it is how somebody says nothing.
    if field.required:
        pairs = ((value, label) for value, label in pairs if str(value) != "")
    # One past the cap, which is what tells a full list from a long one.
    listed = list(islice(pairs, MAX_DESCRIBED_CHOICES + 1))
    if len(listed) > MAX_DESCRIBED_CHOICES:
        return {"type": "string", "x-choices-omitted": True}, (
            f"More than {MAX_DESCRIBED_CHOICES} choices, so they are not "
            "listed here. Send the value the form expects; it is checked "
            "against the real list when the answer is submitted."
        )
    values = [str(value) for value, _ in listed]
    legend = ", ".join(f"{value} ({label})" for value, label in listed)
    return {"type": "string", "enum": values}, f"Choices: {legend}."
