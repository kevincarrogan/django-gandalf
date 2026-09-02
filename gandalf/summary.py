"""Check-your-answers pages: the answered steps of a run, as rows to display.

A summary is a flat list, and a row is one thing the user can check and one
thing they can change: the question, the answer as display text, and the URL
of the page that asked it. `SummaryMixin` builds that list and puts it in the
template context, so a review page is one loop with nothing to decide:

    {% for row in summary %}
      <dt>{{ row.question }}</dt>
      <dd>{{ row.answer }}</dd>
      <dd><a href="{{ row.url }}">Change {{ row.question|lower }}</a></dd>
    {% endfor %}

A step reads as one row per field unless it says otherwise, which most steps
want. One that reads otherwise says so in `summary_rows`, keyed by nothing
because it is about itself: `Answer` reads several of a step's fields as one
row — an address is five answers and one line — `Question` names a row the
step could not name for it, and `Hide` keeps an answer off the page. A spec
is anything that names the fields it speaks for and builds the rows it
stands for, so a page can bring one of its own.

`Answer` takes a `template_name`, and Gandalf renders it. That is the only
thing the library renders: one row's *answer*, through a template the caller
named. The page around it — the list, the change links, the headings — is
the application's, and Gandalf ships no templates to build one with. An
answer rendered this way arrives as `row.answer` already, so the page never
asks which spec produced a row.

Reading `RuntimeStep.form` reconstructs and re-validates that step's form,
so a page that reached for it per row would pay a validation per row. Every
row of a step is built from one form, and `RuntimeStep.form` itself is built
once per step per request, so the cost is one reconstruction per step
however many rows it reads as.

Every decision is also a hook: `get_summary_steps()` chooses the steps,
`get_summary_question()` asks what a step's own row asks, `get_row_specs()`
shapes one step, `include_summary_field()` drops fields, and `format_value()`
renders a value. The defaults suit a plain journey; override what your
domain needs.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field, replace
from typing import TYPE_CHECKING, Any, Protocol, cast

from django.core.exceptions import ImproperlyConfigured
from django.core.files import File
from django.forms import BaseForm
from django.forms.boundfield import BoundField
from django.template.loader import render_to_string
from django.utils import formats
from django.utils.text import capfirst
from django.utils.translation import gettext

from gandalf.form_views import StepFormView
from gandalf.runtime import RuntimeStep
from gandalf.types import StrOrPromise
from gandalf.wizard import declared_step_fields, declared_step_names


if TYPE_CHECKING:
    # A mixin has no bases of its own, but it is only ever mixed into a step
    # view — so at type-check time it is given the class it documents itself
    # as extending. At runtime it stays a plain mixin.
    _SummaryMixinBase = StepFormView
else:
    _SummaryMixinBase = object


__all__ = [
    "Answer",
    "Hide",
    "Question",
    "RowSpec",
    "SummaryMixin",
    "SummaryRow",
    "check_row_specs",
    "format_value",
    "hidden_field_names",
]


@dataclass(frozen=True, init=False)
class Answer:
    """Some of a step's fields, read as one row.

    `Answer("line_1", "line_2", "town", "postcode")` turns four answers into
    one: each is rendered as the text it would have shown on its own, the
    empty ones are dropped — a blank second line does not leave ", ," in the
    middle of an address — and what is left is joined with `separator`. An
    answer takes the place of the first of its fields, so the row still
    arrives in form order.

    `template_name` is the row's own markup, rendered by Gandalf and handed
    to the page as `SummaryRow.answer`. An address that reads as lines rather
    than as a comma run-on says so once, here, next to the fields it is
    about — rather than as an `{% if %}` in the review template, which would
    otherwise have to know the name of every step whose answer does not read
    as one line. The template is given the row it is rendering as `row`, so
    `row.parts` is the answers in the order this spec named them and
    `row.form` is the bound, validated form they came from —
    `row.form.cleaned_data` included, which is where a value the form
    derived in `clean()` lives and where a formset's rows are. That is the
    reach a field list cannot offer, and it is offered anyway.

    Naming no fields means *the rest*: every field of the step no other spec
    named. `Answer(template_name="hours.html")` is how a step whose answer
    is not a list of fields at all says so — listing every field of a step
    so that one template can ignore the list is ceremony.

    It carries no question of its own. A row is asked by the step it belongs
    to, or by the `Question` around it when the step's own name is not what
    the row asks; two ways to name one thing is what a summary page does not
    need.

    A field the step's form does not offer is skipped rather than refused: a
    dynamic `get_form_class()` may vary what a step asks, and a row has to
    survive asking for less.
    """

    fields: tuple[str, ...]
    separator: str = ", "
    template_name: str | None = None

    def __init__(
        self,
        *fields: str,
        separator: str = ", ",
        template_name: str | None = None,
    ) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "separator", separator)
        object.__setattr__(self, "template_name", template_name)

    def build_rows(
        self,
        view: SummaryMixin,
        step: RuntimeStep,
        form: BaseForm,
        question: StrOrPromise | None = None,
    ) -> Iterator[SummaryRow]:
        """One row, from the fields this spec names."""
        yield view.build_answer_row(step, form, self, question)


@dataclass(frozen=True, init=False)
class Hide:
    """Fields the summary does not show.

    `Hide("lookup_token")` drops an answer the user never gave in their own
    words — the token an address lookup returned, a hidden nonce — from the
    page that reads their answers back. It claims its fields and builds no
    row, which is what hiding is.
    """

    fields: tuple[str, ...]

    def __init__(self, *fields: str) -> None:
        object.__setattr__(self, "fields", fields)

    def build_rows(
        self,
        view: SummaryMixin,
        step: RuntimeStep,
        form: BaseForm,
        question: StrOrPromise | None = None,
    ) -> Iterator[SummaryRow]:
        """No rows: that is what hiding is."""
        return iter(())


def hidden_field_names(specs: Iterable[Any]) -> frozenset[str]:
    """The fields `specs` keep off the page: every one a `Hide` names.

    Asked by readers that are not the summary page but show a person their
    answers all the same — the driver, describing a step to an agent or a
    panel. A token the summary drops is a token the agent should neither
    read out nor be invited to supply, and the step said so once.

    `Hide` by type rather than by asking a spec what it builds, because
    that question needs a form and a run, and this one is asked of a
    declaration. A custom spec that yields no rows hides nothing here.
    """
    return frozenset(
        field_name
        for spec in specs
        if isinstance(spec, Hide)
        for field_name in spec.fields
    )


@dataclass(frozen=True, init=False)
class Question:
    """A row's name, for a row the step could not name.

    A step is a page, and a page that asked one thing is named by the step:
    the address step's row is called Address without anyone saying so. A
    page that asked three — an address, a date of birth and a nationality —
    reads as three rows sharing one change link, and the step's name will do
    for at most one of them. `Question` is where the other two get theirs:

        summary_rows = [
            Question("Address", Answer("line_1", "line_2", "town")),
            Question("Date of birth", Answer(template_name="dob.html")),
            Hide("lookup_token"),
        ]

    It wraps exactly one spec and does one thing to it — names the row it
    builds. Everything about *what* the row says is the spec's, which is why
    a `Question` takes no separator, no template and no fields of its own:
    the spec inside it already answers all three, and a second way to say
    them is a second way to be wrong.
    """

    text: StrOrPromise
    spec: RowSpec

    def __init__(self, text: StrOrPromise, spec: RowSpec) -> None:
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "spec", spec)

    @property
    def fields(self) -> tuple[str, ...]:
        """The fields its spec names — a question speaks for exactly those."""
        return self.spec.fields

    def build_rows(
        self,
        view: SummaryMixin,
        step: RuntimeStep,
        form: BaseForm,
        question: StrOrPromise | None = None,
    ) -> Iterator[SummaryRow]:
        """Its spec's rows, asked. The question goes *down* rather than being
        applied after, so a template rendering the answer already sees the
        question the page will show it under."""
        yield from self.spec.build_rows(view, step, form, self.text)


class RowSpec(Protocol):
    """One instruction about a step's answers, as `summary_rows` carries
    them. `Answer`, `Hide` and `Question` are the ones Gandalf ships;
    anything answering these two questions is one.

    A spec **names** the fields it speaks for, and **builds** the rows it
    stands for. There is one rule between them, and it is the whole of the
    arrangement:

        A spec speaks for the fields it names. A spec naming none speaks
        for every field no other spec named.

    So `Hide("token")` claims the token and builds nothing. An `Answer`
    naming no fields claims whatever is left, which is usually the lot. And
    an `Answer` beside one is not a conflict to refuse but a sentence that
    parses: these fields on one row, the rest on another.

    A spec speaks once, at the first of its fields the page shows. One
    naming no fields speaks at the first field nothing else claimed — or
    last, and for nothing, when the step had nothing left to give it: an
    empty formset still renders its template, because the template is the
    point rather than the values.
    """

    @property
    def fields(self) -> tuple[str, ...]:
        """The field names this spec speaks for. Empty means the rest."""

    def build_rows(
        self,
        view: SummaryMixin,
        step: RuntimeStep,
        form: BaseForm,
        question: StrOrPromise | None = None,
    ) -> Iterator[SummaryRow]:
        """The rows this spec stands for — none, one, or several.

        `view` is the summary page, so a spec defers to it rather than
        deciding for it: `view.format_value()` renders a value,
        `view.include_summary_field()` says whether an answer is shown at
        all, `view.get_summary_question()` is what a step asks on behalf of a
        row that asks nothing itself, and `view.claimed_field_names()` is
        what a spec naming no fields subtracts to find its own.

        `question` is what a `Question` around it asked, and None when
        nothing did.
        """


@dataclass(frozen=True)
class SummaryRow:
    """One row of a check-your-answers page: the question, the answer, and
    where to go to change it. The page reads what the declaration wrote —
    `Question` and `Answer` there, `row.question` and `row.answer` here.

    `answer` is display text, and the only thing a plain page needs to
    print. It is one answer formatted, or several joined, or — when the spec
    named a `template_name` — that template already rendered, in which case
    it arrives marked safe exactly as a form's `as_p()` does. A page prints
    `{{ row.answer }}` and never asks which of the three it got.

    `parts` are the pieces `answer` was joined from, one per answered field,
    so a template can read an address as lines rather than as a comma
    run-on. `name` is the answer's name — the field's, or the first field a
    multi-field row showed, or the step's when the row showed none.

    `form` is the bound, validated form the answer came from, so a template
    can reach the whole answer rather than the pieces named here:
    `row.form.cleaned_data` is where a form that derives something in
    `clean()` puts it.

    `bound_field` is the escape hatch: the Django `BoundField` the answer
    came from, for templates that need the widget, the help text, or the
    field's own attributes. It is None for a row several fields made, which
    no single `BoundField` can stand for.

    `step` is the underlying `RuntimeStep`, so a template that needs the raw
    submission (`row.step.data`), the step's context, or its name to group
    rows by can still reach them.
    """

    step: RuntimeStep
    question: StrOrPromise
    answer: str
    name: str = ""
    parts: tuple[str, ...] = ()
    form: BaseForm | None = dataclass_field(default=None, repr=False, compare=False)
    bound_field: BoundField | None = dataclass_field(
        default=None, repr=False, compare=False
    )

    @property
    def url(self) -> str | None:
        """The step's own URL — the change link for this row."""
        return self.step.url


def check_row_specs(specs: Sequence[RowSpec], source: str) -> None:
    """Refuse a list of specs that contradicts itself.

    The things a list can say wrong knowing nothing but itself: a field
    claimed by two specs, two specs naming no fields, and a `Question`
    wrapping something that is not one row's worth of answer. All are
    decidable from the declaration, which is why
    `StepFormView.__init_subclass__` asks at import — a step view saying
    something impossible should not wait for someone to open the summary
    page to find out.

    The refusals not here need the step. Whether a spec names a field its
    step has not got waits for the page that knows which step it is
    holding.

    `source` is what declared them, because the fix is there.
    """
    for spec in specs:
        if not isinstance(spec, Question):
            continue
        if isinstance(spec.spec, Question):
            raise ImproperlyConfigured(
                f"{source} has a Question ({spec.text!r}) inside a "
                f"Question. A question names one row; naming it twice "
                f"leaves nothing to decide which name wins."
            )
        if isinstance(spec.spec, Hide):
            raise ImproperlyConfigured(
                f"{source} has a Hide inside a Question ({spec.text!r}), "
                f"which is a row named and then not shown. A Hide drops "
                f"answers and belongs beside a question, not in one."
            )
    seen: set[str] = set()
    for spec in specs:
        for field_name in spec.fields:
            if field_name in seen:
                raise ImproperlyConfigured(
                    f"{source} names {field_name!r} more than once; "
                    f"a field belongs to one spec."
                )
            seen.add(field_name)
    whole = [spec for spec in specs if not spec.fields]
    if len(whole) > 1:
        raise ImproperlyConfigured(
            f"{source} has more than one spec that names no fields, and what "
            f"no other spec named cannot go to both."
        )


def _flatten_choices(choices: Any) -> Iterator[tuple[Any, Any]]:
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            # An optgroup: the label is the group's own choices.
            yield from label
        else:
            yield value, label


def _choice_label(bound_field: BoundField, value: Any) -> str | None:
    """The display label a field's choices give `value`, or None.

    Only consulted for the scalar kinds a choice value takes, so a field
    whose values are objects — a `ModelChoiceField`, say — falls through to
    its own string rather than dragging the whole queryset in to look
    itself up.
    """
    if not isinstance(value, (str, int)):
        return None
    choices = getattr(bound_field.field, "choices", None) or ()
    labels = {
        str(choice_value): str(label)
        for choice_value, label in _flatten_choices(choices)
    }
    return labels.get(str(value))


def format_value(bound_field: BoundField, value: Any) -> str:
    """Render one cleaned answer as display text.

    Choice values become their labels, booleans become Yes/No, dates and
    times take the active locale's format, uploads show their filename, and
    a multi-valued answer is each of those joined with commas. An answer the
    user never gave renders as empty text rather than "None".

    A field carrying `format_value()` is asked instead, and is handed the
    whole answer — a list included, since a field holding several things
    knows how they read together. It is the one place a project's own field
    says how it reads, rather than every page that shows it saying so
    again; without it the fall-through is `str(value)`, and a person
    checking their answers is shown a Python repr. (Django's *widgets*
    carry a `format_value()` of their own, for rendering an input's value.
    This is the answer's display text, and the two are unrelated.)

    The empty answer is decided before asking. That an unanswered field
    shows blank is the page's rule rather than the field's — a page wanting
    "Not provided" says so by overriding `SummaryMixin.format_value`.
    """
    if value is None or value == "":
        return ""
    formatter = getattr(bound_field.field, "format_value", None)
    if formatter is not None:
        return str(formatter(value))
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(bound_field, item) for item in value)
    if isinstance(value, bool):
        return gettext("Yes") if value else gettext("No")
    label = _choice_label(bound_field, value)
    if label is not None:
        return label
    if isinstance(value, datetime.datetime):
        return formats.date_format(value, "DATETIME_FORMAT")
    if isinstance(value, datetime.date):
        return formats.date_format(value, "DATE_FORMAT")
    if isinstance(value, datetime.time):
        return formats.time_format(value, "TIME_FORMAT")
    if isinstance(value, File):
        return value.name or ""
    return str(value)


class SummaryMixin(_SummaryMixinBase):
    """Adds `summary` — a flat list of `SummaryRow` — to a step view's
    template context.

    Mix into the `FormView` of a check-your-answers step:

        from gandalf.form_views import StepFormView
        from gandalf.summary import SummaryMixin


        class ReviewStepView(SummaryMixin, StepFormView):
            form_class = ConfirmForm
            template_name = "checkout/review.html"

    The rows come from `request.run.path`, so they are the answers on the
    run's resolved route, in walk order, with the selected branch arm inlined
    — never an answer the run has left behind in a dormant arm, and never the
    step doing the summarising, which is dropped explicitly because a run
    revisited or re-opened arrives with that answer stored too.

    A step whose answers do not read as one row per field says so in its own
    `summary_rows`. A page that wants one of them read differently *here*
    says so in `summary_overrides`, keyed by step name:

        class ReviewStepView(SummaryMixin, StepFormView):
            summary_overrides = {
                "address": [
                    Answer("line_1", "line_2", "town", "postcode"),
                    Hide("lookup_token"),
                ],
            }

    The page has the last word; the step is where the answer normally
    belongs, being the thing that knows an address is an address.
    """

    summary_context_name = "summary"
    summary_label_context_key = "label"

    #: What this page wants said differently, keyed by step name. A step
    #: this mapping does not mention reads as *it* says it reads — its own
    #: `summary_rows` — and failing that as one row per field. A key with
    #: an empty sequence is an opinion, not a silence: it overrides the step
    #: back to plain.
    summary_overrides: Mapping[str, Sequence[RowSpec]] = {}

    def get_summary_steps(self) -> list[RuntimeStep]:
        """The steps to summarise: every answered step on the route, except
        the one doing the summarising.

        A wizard that only runs forwards never has its own summary step in
        `path` — the step being rendered is the cursor, and the cursor is by
        definition unanswered. A run that has been round the houses does: an
        edit revisited from a change link, or a stashed section re-opened
        with `reopen_at` pointing here, both arrive with every answer
        stored, this page's own confirmation included. Dropping it is what
        stops the page offering to change itself.
        """
        rendering = self.request.run.rendering
        return [
            step for step in self.request.run.path if step.declaration is not rendering
        ]

    def get_summary_rows(self) -> list[SummaryRow]:
        self.check_summary_overrides()
        self.check_summary_row_names()
        fields = declared_step_fields(self.request.run.wizard)
        rows: list[SummaryRow] = []
        for step in self.get_summary_steps():
            # Checked here rather than beside the others because it is the
            # only check that has to ask the step itself, and asking sets
            # the step's view up: done in a second pass it would build every
            # step's view twice, and a summary page is already the most
            # expensive page a run has.
            self.check_step_field_names(step, fields)
            rows.extend(self.build_summary_rows(step))
        return rows

    def build_summary_rows(self, step: RuntimeStep) -> Iterator[SummaryRow]:
        """The rows one step makes: one per field, with its specs folded in.

        An `Answer` replaces the first of its fields and swallows the rest,
        a hidden field yields nothing, and every field no spec named keeps a
        row of its own — which is why a field added to a form appears on the
        summary the moment it is added, whatever else the step says.

        Which of those a spec does is the spec's own answer, not a branch
        here: the walk reaches a field, finds the spec that named it, and
        asks it to speak. A spec speaks once, at the first of its fields the
        page shows, and accounts for the rest of them by saying nothing when
        they come round. Only a spec naming no fields is different, because
        no field brings the walk to it — it speaks for the whole step, and
        the walk never starts.
        """
        specs = self.get_row_specs(step)
        # A page's `summary_overrides` reaches no other check until the walk
        # asks a spec to speak — so the list is checked here, whoever wrote
        # it, and a step view's own is checked twice rather than never.
        check_row_specs(specs, self.row_specs_source(step))
        form = step.form
        by_field = self._specs_by_field(specs)
        whole = self.get_whole_step_spec(specs)
        if whole is not None:
            # It speaks for every field no other spec named, so it stands
            # behind each of them and the walk reaches it like any other.
            # `len(specs)` is a slot of its own: `_specs_by_field` indexes
            # 0 to len(specs) - 1.
            for bound_field in step.answer_fields:
                by_field.setdefault(bound_field.name, (len(specs), whole))
        spoken: set[int] = set()
        for bound_field in step.answer_fields:
            if not self.include_summary_field(step, bound_field):
                continue
            found = by_field.get(bound_field.name)
            if found is None:
                yield self.build_field_row(step, form, bound_field)
                continue
            index, spec = found
            if index in spoken:
                # A spec speaks once, at the first of its fields the page
                # shows; the rest of them are its to account for.
                continue
            spoken.add(index)
            yield from spec.build_rows(self, step, form)
        if whole is not None and len(specs) not in spoken:
            # Nothing was left for it: a step whose every field another spec
            # named, or one with no fields at all — an empty formset. It
            # still speaks, because its template is the point.
            yield from whole.build_rows(self, step, form)

    def check_step_field_names(
        self,
        step: RuntimeStep,
        fields: Mapping[str, Mapping[str, Any] | None] | None,
    ) -> None:
        """Refuse a step's *own* specs naming a field it has not got.

        The same rule the page's specs answer to, and for the same reason: a
        misspelt `Hide` hides nothing and renders the answer it was meant to
        keep off the page. A step this page overrides is checked as the
        page's, once, in `check_summary_row_names()`.
        """
        if fields is None:
            return
        name = cast(str, step.name)
        if name in self.summary_overrides:
            return
        self.check_field_names(
            name,
            self.get_row_specs(step),
            fields,
            f"step {name!r}'s own summary_rows",
        )

    def check_summary_overrides(self) -> None:
        """Refuse a `summary_overrides` key that names no step of this
        wizard.

        A renamed step would otherwise take its shaping with it and go
        quietly back to one row per field — the kind of regression a page
        only shows you in production. Checked against what the wizard
        *declares* rather than what this run walked, so a key naming a step
        on the arm not taken is fine.
        """
        if not self.summary_overrides:
            return
        declared = self.get_declared_step_names()
        if declared is None:
            return
        unknown = sorted(set(self.summary_overrides) - declared)
        if not unknown:
            return
        name = self.__class__.__name__
        raise ImproperlyConfigured(
            f"{name}.summary_overrides shapes steps this wizard does not "
            f"declare: {', '.join(unknown)}. Declared steps: "
            f"{', '.join(sorted(declared))}."
        )

    def check_summary_row_names(self) -> None:
        """Refuse a spec naming a field its step does not have, whether this
        page named it or the step did.

        At render a field a step does not offer is skipped, deliberately —
        a dynamic `get_form_class()` may ask for less and a row has to
        survive that. Which is exactly why a *typo* needs catching here: a
        misspelt `Hide` hides nothing, and the answer it was meant to keep
        off the page is rendered onto it. Checked only where the
        declaration knows the fields: a step whose view picks its form per
        request is taken on trust.
        """
        if not self.summary_overrides:
            return
        fields = declared_step_fields(self.request.run.wizard)
        if fields is None:
            return
        page = f"{self.__class__.__name__}.summary_overrides"
        for step_name, specs in self.summary_overrides.items():
            self.check_field_names(step_name, specs, fields, page)

    def check_field_names(
        self,
        step_name: str,
        specs: Sequence[RowSpec],
        fields: Mapping[str, Mapping[str, Any] | None],
        source: str,
    ) -> None:
        """Refuse `specs` naming a field step `step_name` does not declare.

        `source` is what said so — this page, or the step itself — because
        the fix is in one place or the other and the message should say
        which.
        """
        declared = fields.get(step_name)
        if declared is None or not specs:
            return
        named = {
            field for spec in specs for field in spec.fields if field not in declared
        }
        if not named:
            return
        raise ImproperlyConfigured(
            f"{source} shapes fields step {step_name!r} does not "
            f"declare: {', '.join(sorted(named))}. Its fields: "
            f"{', '.join(sorted(declared))}."
        )

    def get_declared_step_names(self) -> set[str] | None:
        """Every step name the wizard declares, or None when the declaration
        is not the whole story: an `Expand` builds its steps mid-walk, so
        theirs cannot be known before the walk reaches them, and a name that
        looks unknown may simply not have been grown yet.
        """
        return declared_step_names(self.request.run.wizard)

    def get_whole_step_spec(self, specs: Sequence[RowSpec]) -> RowSpec | None:
        """The spec that speaks for what no other spec named, if the step
        has one: the spec naming no fields.

        Two of them is refused by `check_row_specs()`, which the walk has
        already run — what is left over cannot go to both, and a page
        rendering half its answers through one template and half through
        another, silently, is a mistake being made quietly.
        """
        whole = [spec for spec in specs if not spec.fields]
        if not whole:
            return None
        return whole[0]

    def get_row_specs(self, step: RuntimeStep) -> Sequence[RowSpec]:
        """How one step's answers read as rows.

        This page's `summary_overrides` by step name, and failing that what
        the step says about itself — a step view's own `summary_rows`. The
        page has the last word, and says nothing about the steps it has no
        opinion on: an address that reads as an address wherever it is asked
        says so once, next to the address.

        Override to decide per run.
        """
        # A summary page is a step of a wizard served over HTTP, and the
        # viewset refuses a wizard whose steps have no name — so every step
        # a row is built from has one to look up.
        name = cast(str, step.name)
        if name in self.summary_overrides:
            return self.summary_overrides[name]
        return cast("Sequence[RowSpec]", list(step.summary_rows))

    def _specs_by_field(
        self, specs: Sequence[RowSpec]
    ) -> dict[str, tuple[int, RowSpec]]:
        """Each named field's spec, by field name, with the spec's position
        — which is what tells two identically written specs apart."""
        by_field: dict[str, tuple[int, RowSpec]] = {}
        for index, spec in enumerate(specs):
            for field_name in spec.fields:
                by_field[field_name] = (index, spec)
        return by_field

    def row_specs_source(self, step: RuntimeStep) -> str:
        """What declared the specs a step is being shown with — this page,
        or the step. Names the place a refusal should be fixed."""
        name = cast(str, step.name)
        if name in self.summary_overrides:
            return f"{self.__class__.__name__}.summary_overrides[{name!r}]"
        return f"step {name!r}'s own summary_rows"

    def build_field_row(
        self, step: RuntimeStep, form: BaseForm, bound_field: BoundField
    ) -> SummaryRow:
        """One answer, on a row of its own, named by the field that asked it.

        The cleaned value comes from the bound field's *own* form, which is
        `form` itself for all but a repeated step — where the fields belong
        to a row rather than to the step, and the step's own `cleaned_data`
        is the list of rows.
        """
        value = self.format_value(
            bound_field, bound_field.form.cleaned_data.get(bound_field.name)
        )
        return SummaryRow(
            step=step,
            question=bound_field.label,
            answer=value,
            name=bound_field.name,
            parts=(value,) if value else (),
            form=bound_field.form,
            bound_field=bound_field,
        )

    def build_answer_row(
        self,
        step: RuntimeStep,
        form: BaseForm,
        spec: Answer,
        question: StrOrPromise | None = None,
    ) -> SummaryRow:
        """Several answers, on one row.

        The pieces are joined in the order the spec names them, not the
        order the form asks them, because that order is the point: an address
        reads street, town, postcode whatever the form does. Empty answers
        drop out, so a blank second line costs the address nothing.

        `question` is the `Question`'s if one asked this row, and the step's
        own name when nothing did — a page that asked one thing having
        already named it.
        """
        shown: list[tuple[str, str]] = []
        for bound_field in self.answered_bound_fields(step, form, spec):
            if not self.include_summary_field(step, bound_field):
                continue
            value = self.format_value(
                bound_field, bound_field.form.cleaned_data.get(bound_field.name)
            )
            shown.append((bound_field.name, value))
        parts = tuple(value for _, value in shown if value)
        row = SummaryRow(
            step=step,
            question=(
                question if question is not None else self.get_summary_question(step)
            ),
            answer=spec.separator.join(parts),
            name=shown[0][0] if shown else (step.name or ""),
            parts=parts,
            form=form,
        )
        return self.render_row(row, spec.template_name)

    def render_row(self, row: SummaryRow, template_name: str | None) -> SummaryRow:
        """The row with its answer rendered, when its spec named a template.

        The one thing Gandalf renders, and never one of its own: the
        template is the caller's, and what comes back is marked safe the way
        any rendered template is, so the page prints `{{ row.answer }}`
        without knowing which kind of row it holds.

        Rendered now rather than lazily in the template, so a template that
        does not exist fails while the page is being built — with a
        traceback naming the step — rather than halfway through the markup.
        """
        if template_name is None:
            return row
        rendered = render_to_string(
            template_name,
            {"row": row, "view": self},
            request=self.request,
        )
        return replace(row, answer=rendered)

    def claimed_field_names(self, step: RuntimeStep) -> set[str]:
        """Every field name some spec of this step names.

        What is left over is what a spec naming none speaks for, which is
        the only reason anything asks. The walk itself never does: a named
        field's spec answers for it when the walk arrives.
        """
        return {name for spec in self.get_row_specs(step) for name in spec.fields}

    def answered_bound_fields(
        self, step: RuntimeStep, form: BaseForm, spec: Answer
    ) -> Sequence[BoundField]:
        """The bound fields one row joins: the ones its spec names, in its
        own order.

        A spec naming none takes what no other spec named, in form order —
        the same rule every spec answers to, which here reads as *the rest
        of this step, on one row*. Those come from `step.answer_fields`
        rather than by name, because a repeated step's rows share their
        field names and looking one up would collapse seven days into one.

        A field the step's form does not offer is skipped rather than
        refused: a dynamic `get_form_class()` may ask for less, and a row
        has to survive it.
        """
        if not spec.fields:
            claimed = self.claimed_field_names(step)
            return [
                bound_field
                for bound_field in step.answer_fields
                if bound_field.name not in claimed
            ]
        found: list[BoundField] = []
        for field_name in spec.fields:
            try:
                found.append(form[field_name])
            except KeyError:
                continue
        return found

    def include_summary_field(self, step: RuntimeStep, bound_field: BoundField) -> bool:
        """Whether `bound_field` earns a place on the summary. Override to
        hide fields the user should not be shown their own answer to."""
        return True

    def get_summary_question(self, step: RuntimeStep) -> StrOrPromise:
        """What a row asks when the step itself has to say: the step's
        `label` context if it declares one (`.step(Form, name="billing",
        label="Billing")`), otherwise its name made readable.

        A row an `Answer` built takes this when no `Question` asked it,
        because a page that asked one thing is named by the step. A row one
        field built is asked by the field."""
        context = step.declaration.context or {}
        label: StrOrPromise | None = context.get(self.summary_label_context_key)
        if label is not None:
            return label
        name = step.name or ""
        return capfirst(name.replace("_", " ").replace("-", " "))

    def format_value(self, bound_field: BoundField, value: Any) -> str:
        """Render one answer as display text. Override for domain formatting,
        deferring to `super()` for the fields you do not special-case."""
        return format_value(bound_field, value)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context[self.summary_context_name] = self.get_summary_rows()
        return context
