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
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.forms import BaseForm
from django.http import HttpRequest, HttpResponseBase
from django.test import RequestFactory

from gandalf import tree
from gandalf.escapes import Advance, Escape, Obliterate, Park
from gandalf.runtime import BoundWizard, Cursor, RuntimeStep, StepNotFound, Walk
from gandalf.summary import _flatten_choices
from gandalf.types import Metadata, Submission
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
    "StepDescription",
    "SubmitResult",
    "fabricate_request",
    "field_json_schema",
    "form_json_schema",
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


class _MemorySession(dict):  # type: ignore[type-arg]
    """The dict-with-a-`modified`-flag shape `SessionStorage` needs; what a
    fabricated request carries instead of a browser-backed session."""

    modified = False


def fabricate_request(*, user: Any = None, session: Any = None) -> HttpRequest:
    """A request good enough to drive a wizard with — no middleware, no
    browser, no response cycle.

    Step validation dispatches synthetic requests copied from this one, so
    it needs only a method, a path, and a session-shaped object. Pass
    `session` to share storage between drivers (or with a real session);
    pass `user` when a step's view reads `request.user`.
    """
    request = RequestFactory().get("/agent/")
    if session is None:
        session = _MemorySession()
    request.session = session
    if user is not None:
        request.user = user
    return request


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
        url_kwargs: dict[str, Any] | None = None,
        *,
        may_finish: bool | None = None,
    ) -> None:
        self.view = view
        self.bound_wizard = bound_wizard
        self._url_kwargs = url_kwargs if url_kwargs is not None else {}
        self._last_errors: Errors = {}
        if may_finish is not None:
            self.may_finish = may_finish

    @classmethod
    def begin(
        cls,
        viewset_class: type[WizardViewSet],
        *,
        request: HttpRequest | None = None,
        may_finish: bool | None = None,
        **url_kwargs: Any,
    ) -> RunDriver:
        """A driver over a fresh run of `viewset_class`'s wizard."""
        if request is None:
            request = fabricate_request()
        view = viewset_class()
        view.setup(request, **url_kwargs)
        bound_wizard = viewset_class.begin(request, **url_kwargs)
        return cls(view, bound_wizard, url_kwargs, may_finish=may_finish)

    @classmethod
    def resume(
        cls,
        viewset_class: type[WizardViewSet],
        run_id: str,
        *,
        request: HttpRequest | None = None,
        may_finish: bool | None = None,
        **url_kwargs: Any,
    ) -> RunDriver:
        """A driver over an existing run. Raises `RunNotFound` for a run the
        request's storage does not hold — pass the `session` the run lives
        in via `fabricate_request(session=...)`, or use a durable storage."""
        if request is None:
            request = fabricate_request()
        view = viewset_class()
        view.setup(request, **url_kwargs)
        bound_wizard = viewset_class.inspect(request, run_id, **url_kwargs)
        return cls(view, bound_wizard, url_kwargs, may_finish=may_finish)

    @property
    def run_id(self) -> str:
        return self.bound_wizard.run_id

    def describe(self) -> StepDescription:
        """The run as the agent should see it right now."""
        cursor = self.bound_wizard.cursor()
        answers = self.answers()
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

    def answers(self) -> dict[str, dict[str, Any]]:
        """Every answered step's `cleaned_data`, keyed by step name.

        Cleaned values are Python objects rather than the strings they were
        posted as — a `DateField` gives a `datetime.date`. `submit()` takes
        them back as they are, so a step can be read, changed and
        resubmitted without converting anything.
        """
        # The steps are held once: `path` walks per access, and each node
        # validates its form at most once.
        steps = list(self.bound_wizard.path)
        return {cast(str, step.name): dict(step.form.cleaned_data) for step in steps}

    #: Recorded against everything this driver places, unless the caller
    #: says otherwise. A driver is not a person, and the answers alone
    #: cannot say so.
    default_metadata: ClassVar[Metadata] = {"unattended": True}

    def metadata(self) -> dict[str, Metadata]:
        """What each answered step's placement recorded about itself, keyed
        by step name. Steps that recorded nothing are absent."""
        steps = list(self.bound_wizard.path)
        return {cast(str, step.name): step.metadata for step in steps if step.metadata}

    def submit(
        self,
        data: dict[str, Any],
        *,
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
        walk = bound_wizard.walk(
            claim=claim,
            submission=submission,
            metadata=self.default_metadata if metadata is None else metadata,
        )
        if not walk.reached:
            raise StepNotFound({"name": step})
        target = cast(RuntimeStep, walk.target)
        escape = walk.cursor.escape_for(target.declaration)
        if escape is not None:
            return self._escaped(escape, walk)
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

    def _escaped(self, escape: Escape, walk: Walk) -> SubmitResult:
        """Settle what the escape leaves behind — the viewset's dispositions
        without the redirect (the caller gets the escape's name instead)."""
        if isinstance(escape, Obliterate):
            self.bound_wizard.obliterate()
        elif isinstance(escape, Advance):
            self.bound_wizard.persist(walk)
            self._refresh(walk)
        elif not isinstance(escape, Park):
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
        data = _as_posted(data)
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
        request: HttpRequest | None = None,
        **url_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """The shape of `viewset_class`'s wizard, without starting a run.

        What a caller deciding whether to begin needs: the journey ahead,
        answerable before there is anything to answer it with. No run is
        created, so nothing is left behind by asking — which matters to a
        caller describing several wizards to choose between them.
        """
        if request is None:
            request = fabricate_request()
        bound_wizard = viewset_class.resolve(request, **url_kwargs)
        driver = cls(viewset_class(), bound_wizard, url_kwargs)
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


def _as_posted(data: dict[str, Any]) -> dict[str, Any]:
    """`data` reduced to the values a browser would have posted.

    A submission is stored with the run's state, and state is JSON. Over
    HTTP that holds for free — a POST is strings — but a driver's caller
    has richer values to hand, and the obvious source of them is
    `answers()`, which returns `cleaned_data`: a `DateField` gives a
    `datetime.date`. Read a step's answers, change one field, submit the
    result, and until this converted them the date went in unremarked and
    the run only failed later, when its state was written, by which time
    nothing could say which answer was at fault.

    `DjangoJSONEncoder` renders exactly the types Django's own fields
    produce — dates, times, decimals, UUIDs — in the form those fields
    parse back, so a value survives the trip out and in again as itself. A
    value it cannot render still raises, but here, where the caller can see
    what it passed.
    """
    return cast("dict[str, Any]", json.loads(json.dumps(data, cls=DjangoJSONEncoder)))


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
    if field.label is not None:
        schema["title"] = str(field.label)
    notes = []
    if field.help_text:
        notes.append(str(field.help_text))
    if note is not None:
        notes.append(note)
    if notes:
        schema["description"] = " ".join(notes)
    return schema


def _base_schema(field: forms.Field) -> tuple[dict[str, Any], str | None]:
    """The type-shaped half of a field's schema, plus an optional note
    destined for the property's description."""
    if isinstance(field, forms.MultipleChoiceField):
        values, legend = _choice_values(field)
        return {"type": "array", "items": {"type": "string", "enum": values}}, legend
    if isinstance(field, forms.ChoiceField):
        values, legend = _choice_values(field)
        return {"type": "string", "enum": values}, legend
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
    if isinstance(field, forms.CharField):
        return _string_schema(field), None
    return {"type": "string"}, (
        f"{type(field).__name__} is not supported by the schema mapping; "
        "submit its raw form value."
    )


def _bounded_schema(
    schema: dict[str, Any], field: forms.IntegerField
) -> dict[str, Any]:
    if field.min_value is not None:
        schema["minimum"] = field.min_value
    if field.max_value is not None:
        schema["maximum"] = field.max_value
    return schema


def _string_schema(field: forms.CharField, **extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", **extra}
    if field.max_length is not None:
        schema["maxLength"] = field.max_length
    if field.min_length is not None:
        schema["minLength"] = field.min_length
    return schema


def _choice_values(field: forms.ChoiceField) -> tuple[list[str], str]:
    pairs = list(_flatten_choices(field.choices))
    values = [str(value) for value, _ in pairs]
    legend = ", ".join(f"{value} ({label})" for value, label in pairs)
    return values, f"Choices: {legend}."
