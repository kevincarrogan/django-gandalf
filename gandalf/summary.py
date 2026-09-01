"""Check-your-answers pages: the answered steps of a run, ready to display.

A summary step asks the same three questions of every answer — what is it
called, what does it say, and where do I go to change it — so `SummaryMixin`
answers them once. Mix it into the step's `FormView` and the template gets a
`summary` list: one `SummaryRow` per answered step, carrying its label, its
fields as display text, and the URL that edits it.

Reading `RuntimeStep.form` reconstructs and re-validates that step's form, so
a page that reaches for it per field would pay a validation per field. The
mixin builds each row from a single form, and `RuntimeStep.form` itself is
built once per step per request, so the cost is one reconstruction per row
however much the template reads.

One field per answer suits most steps and not all of them: an address is
five answers and one line. `summary_fields` says so declaratively, keyed by
step name — `Group` shows several of a step's fields as one answer, `Hide`
shows none of them, `Render` gives them to one template — and fields no
spec names keep a line of their own. A spec is anything that names the
fields it speaks for and builds the answers it stands for, so a page can
bring one of its own.

Every decision is also a hook: `get_summary_steps()` chooses the steps,
`get_summary_label()` names one, `get_field_specs()` shapes one step's
fields, `include_summary_field()` drops fields, and `format_value()` renders
a value. The defaults suit a plain journey; override what your domain needs.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, Protocol, cast

from django.core.exceptions import ImproperlyConfigured
from django.core.files import File
from django.forms import BaseForm
from django.forms.boundfield import BoundField
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


#: The template one answer renders through when nothing names another. It
#: renders `{{ field.value }}` and nothing else, so the markup around an
#: answer stays the page's. A project changes it for every page by shadowing
#: the path in its own template directory, or for one page with
#: `SummaryMixin.summary_field_template_name`.
FIELD_TEMPLATE_NAME = "gandalf/summary/field.html"


__all__ = [
    "FIELD_TEMPLATE_NAME",
    "check_field_specs",
    "FieldSpec",
    "Group",
    "Hide",
    "Render",
    "SummaryField",
    "SummaryMixin",
    "SummaryRow",
    "format_value",
]


@dataclass(frozen=True, init=False)
class Group:
    """Several of a step's fields, shown as one answer.

    `Group("line_1", "line_2", "town", "postcode")` turns four lines into
    one: each answer is rendered as the text it would have shown on its own,
    the empty ones are dropped — a blank second line does not leave ", ," in
    the middle of an address — and what is left is joined with `separator`.
    A group takes the place of the first of its fields, so the row still
    reads in form order.

    `label` is optional because a step whose every field is grouped is
    already named by its row, and repeating that name would say the same
    thing twice. A group without one leaves the row's heading to speak, and
    its `SummaryField.label` is None.

    `template_name` is the group's own markup: the template the summary
    page renders this answer through, reached as `SummaryField.template_name`
    and included by the page. An address that reads as lines rather than as a
    comma run-on says so once, here, next to the fields it is about — rather
    than as an `{% if %}` in the review template, which would otherwise have
    to know the name of every step whose answers do not read as one line.

    A field the step's form does not offer is skipped rather than refused: a
    dynamic `get_form_class()` may vary what a step asks, and a group has to
    survive asking for less.
    """

    fields: tuple[str, ...]
    label: StrOrPromise | None = None
    separator: str = ", "
    template_name: str | None = None

    def __init__(
        self,
        *fields: str,
        label: StrOrPromise | None = None,
        separator: str = ", ",
        template_name: str | None = None,
    ) -> None:
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "separator", separator)
        object.__setattr__(self, "template_name", template_name)

    def build_fields(
        self, view: SummaryMixin, step: RuntimeStep, form: BaseForm
    ) -> Iterator[SummaryField]:
        """One answer, from the fields this group names."""
        yield view.build_group_field(step, form, self)


@dataclass(frozen=True, init=False)
class Hide:
    """Fields the summary does not show.

    `Hide("lookup_token")` drops an answer the user never gave in their own
    words — the token an address lookup returned, a hidden nonce — from the
    page that reads their answers back.
    """

    fields: tuple[str, ...]

    def __init__(self, *fields: str) -> None:
        object.__setattr__(self, "fields", fields)

    def build_fields(
        self, view: SummaryMixin, step: RuntimeStep, form: BaseForm
    ) -> Iterator[SummaryField]:
        """Nothing: that is what hiding is."""
        return iter(())


@dataclass(frozen=True)
class Render:
    """The step's answer, rendered through one template.

    `Group` says which fields read as one answer; `Render` says the step
    does, and needs no field list to say it — listing every field of a step
    so that one template can ignore the list is ceremony. Naming no fields,
    it speaks for every field no other spec named: a `Hide` beside it still
    hides, and a `Group` beside it takes its own fields and leaves the rest.
    Two specs naming no fields is the one shape refused — what is left over
    cannot go to both.

    The template is handed the `SummaryField`, and through it the form:
    `field.form.cleaned_data` is where a value the form derived in `clean()`
    lives, and where a formset's rows are. That is the reach `Group` cannot
    offer, because a value no field holds cannot be named in a field list.

    Rendering from `cleaned_data` gives up `format_value` — a choice is its
    key rather than its label, a boolean is `True` rather than Yes, a date
    is not in the active locale — so the field still carries the formatted
    answers in `parts` and `value`. A template takes whichever it wants.

    It takes the template and nothing else. A group carries a `label` and a
    `separator` because a group without a template is still rendered by the
    library — the join and the sub-heading are the only say the page has.
    Past `Render` the markup is the caller's, and the two would be the
    library shaping output it is not producing. A group is usually one
    answer among a row's several, where a `Render` is usually the only one:
    `row.label` names it, and a template written for one step can write any
    sub-heading it likes.
    """

    template_name: str

    @property
    def fields(self) -> tuple[str, ...]:
        """No fields: a `Render` names none, and takes them all."""
        return ()

    def build_fields(
        self, view: SummaryMixin, step: RuntimeStep, form: BaseForm
    ) -> Iterator[SummaryField]:
        """One answer, from the whole step."""
        yield view.build_render_field(step, form, self)


class FieldSpec(Protocol):
    """One instruction about a step's answers, as `summary_fields` carries
    them. `Group`, `Hide` and `Render` are the ones Gandalf ships; anything
    answering these two questions is one.

    A spec **names** the fields it speaks for, and **builds** the answers it
    stands for. There is one rule between them, and it is the whole of the
    arrangement:

        A spec speaks for the fields it names. A spec naming none speaks
        for every field no other spec named.

    So `Hide("token")` claims the token and yields nothing, which is what
    hiding is. `Render("hours.html")` claims whatever is left, which is
    usually the lot. And a `Group` beside a `Render` is not a conflict to
    refuse but a sentence that parses: these fields on one line, the rest
    through that template.

    A spec speaks once, at the first of its fields the page shows. One
    naming no fields speaks at the first field nothing else claimed — or
    last, and for nothing, when the step had nothing left to give it: an
    empty formset still renders its template, because the template is the
    point rather than the values.
    """

    @property
    def fields(self) -> tuple[str, ...]:
        """The field names this spec speaks for. Empty means the rest."""

    def build_fields(
        self, view: SummaryMixin, step: RuntimeStep, form: BaseForm
    ) -> Iterator[SummaryField]:
        """The answers this spec stands for — none, one, or several.

        `view` is the summary page, so a spec defers to it rather than
        deciding for it: `view.format_value()` renders a value,
        `view.include_summary_field()` says whether an answer is shown at
        all, and `view.claimed_field_names()` is what a spec naming no
        fields subtracts to find its own.
        """


@dataclass(frozen=True)
class SummaryField:
    """One answered field, as display text.

    `label` is None for a `Group` carrying no label of its own — the row's
    heading names it instead. `parts` are the pieces `value` was joined
    from: one per answered field for a group, and the field's own text for
    a plain field, so a template can render an address as lines rather than
    as a comma run-on.

    `template_name` is the template this answer renders through — the
    group's own if it named one, otherwise the page's default. A summary
    template includes it rather than branching on which answer it is
    holding:

        {% for field in row.fields %}{% include field.template_name %}{% endfor %}

    `form` is the bound, validated form the answer came from, so a template
    rendering this field can read the whole answer rather than the pieces
    named here — `field.form.cleaned_data` included, which is where a form
    that derives something in `clean()` puts it. A group has no single
    `BoundField` to reach it through, and this is how it gets there anyway.

    `bound_field` is the escape hatch: the Django `BoundField` the value came
    from, for templates that need the widget, the help text, or the field's
    own attributes. It is None for a group, which no single `BoundField` can
    stand for.
    """

    name: str
    label: StrOrPromise | None
    value: str
    parts: tuple[str, ...] = ()
    template_name: str = FIELD_TEMPLATE_NAME
    form: BaseForm | None = dataclass_field(default=None, repr=False, compare=False)
    bound_field: BoundField | None = dataclass_field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True)
class SummaryRow:
    """One answered step: what it is called, what it says, and where to
    change it. `step` is the underlying `RuntimeStep`, so a template that
    needs the raw submission (`row.step.data`) or the step's context can
    still reach them."""

    step: RuntimeStep
    label: StrOrPromise
    fields: tuple[SummaryField, ...] = ()

    @property
    def name(self) -> str | None:
        """The step's routable name."""
        return self.step.name

    @property
    def url(self) -> str | None:
        """The step's own URL — the change link for this answer."""
        return self.step.url

    @property
    def form(self) -> BaseForm:
        """The bound, validated form behind this row."""
        return self.step.form


def check_field_specs(specs: Sequence[FieldSpec], source: str) -> None:
    """Refuse a list of specs that contradicts itself.

    The two things a list can say wrong knowing nothing but itself: a field
    claimed by two specs, and two specs naming no fields. Both are decidable
    from the declaration, which is why `StepFormView.__init_subclass__` asks
    at import — a step view saying something impossible should not wait for
    someone to open the summary page to find out.

    The third refusal is not here. Whether a spec names a field its step has
    not got needs the step, so it stays with the page that knows which step
    it is holding.

    `source` is what declared them, because the fix is there.
    """
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
    """Adds `summary` — one `SummaryRow` per answered step — to a step
    view's template context.

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

    A step whose answers do not read as one line per field says so in
    `summary_fields`:

        class ReviewStepView(SummaryMixin, StepFormView):
            summary_fields = {
                "address": [
                    Group("line_1", "line_2", "town", "postcode"),
                    Hide("lookup_token"),
                ],
            }

    A step whose answer is not a list of fields at all says so with
    `Render`, which names a template and no fields:

        class ReviewStepView(SummaryMixin, StepFormView):
            summary_fields = {
                "opening-hours": [Render("hours/summary.html")],
            }
    """

    summary_context_name = "summary"
    summary_label_context_key = "label"

    #: The template an answer renders through when its `Group` names none —
    #: and the one every plain field renders through. Set it to give one
    #: page its own house style for an answer.
    summary_field_template_name = FIELD_TEMPLATE_NAME

    #: What this page wants said differently, keyed by step name. A step
    #: this mapping does not mention reads as *it* says it reads — its own
    #: `summary_fields` — and failing that as one line per field. A key with
    #: an empty sequence is an opinion, not a silence: it overrides the step
    #: back to plain.
    summary_overrides: Mapping[str, Sequence[FieldSpec]] = {}

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
        self.check_summary_field_names()
        fields = declared_step_fields(self.request.run.wizard)
        rows = []
        for step in self.get_summary_steps():
            # Checked here rather than beside the others because it is the
            # only check that has to ask the step itself, and asking sets
            # the step's view up: done in a second pass it would build every
            # step's view twice, and a summary page is already the most
            # expensive page a run has.
            self.check_step_field_names(step, fields)
            rows.append(self.build_summary_row(step))
        return rows

    def check_step_field_names(
        self,
        step: RuntimeStep,
        fields: Mapping[str, Mapping[str, Any] | None] | None,
    ) -> None:
        """Refuse a step's *own* specs naming a field it has not got.

        The same rule the page's specs answer to, and for the same reason: a
        misspelt `Hide` hides nothing and renders the answer it was meant to
        keep off the page. A step this page overrides is checked as the
        page's, once, in `check_summary_field_names()`.
        """
        if fields is None:
            return
        name = cast(str, step.name)
        if name in self.summary_overrides:
            return
        self.check_field_names(
            name,
            self.get_field_specs(step),
            fields,
            f"step {name!r}'s own summary_fields",
        )

    def check_summary_overrides(self) -> None:
        """Refuse a `summary_overrides` key that names no step of this
        wizard.

        A renamed step would otherwise take its shaping with it and go
        quietly back to one line per field — the kind of regression a page
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

    def check_summary_field_names(self) -> None:
        """Refuse a spec naming a field its step does not have, whether this
        page named it or the step did.

        At render a field a step does not offer is skipped, deliberately —
        a dynamic `get_form_class()` may ask for less and a group has to
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
        specs: Sequence[FieldSpec],
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

    def build_summary_row(self, step: RuntimeStep) -> SummaryRow:
        form = step.form
        return SummaryRow(
            step=step,
            label=self.get_summary_label(step),
            fields=tuple(self.build_summary_fields(step, form)),
        )

    def build_summary_fields(
        self, step: RuntimeStep, form: BaseForm
    ) -> Iterator[SummaryField]:
        """The step's answers as display text, in form order, with its specs
        folded in: a group replaces the first of its fields and swallows the
        rest, a hidden field yields nothing, and everything else keeps a line
        of its own.

        Which of those a spec does is the spec's own answer, not a branch
        here: the walk reaches a field, finds the spec that named it, and
        asks it to speak. A spec speaks once, at the first of its fields the
        page shows, and accounts for the rest of them by saying nothing when
        they come round. Only a spec naming no fields is different, because
        no field brings the walk to it — it speaks for the whole step, and
        the walk never starts.
        """
        specs = self.get_field_specs(step)
        by_field = self._specs_by_field(step, specs)
        whole = self.get_whole_step_spec(step, specs)
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
                yield self.build_summary_field(step, form, bound_field)
                continue
            index, spec = found
            if index in spoken:
                # A spec speaks once, at the first of its fields the page
                # shows; the rest of them are its to account for.
                continue
            spoken.add(index)
            yield from spec.build_fields(self, step, form)
        if whole is not None and len(specs) not in spoken:
            # Nothing was left for it: a step whose every field another spec
            # named, or one with no fields at all — an empty formset. It
            # still speaks, because its template is the point.
            yield from whole.build_fields(self, step, form)

    def get_whole_step_spec(
        self, step: RuntimeStep, specs: Sequence[FieldSpec]
    ) -> FieldSpec | None:
        """The spec that speaks for what no other spec named, if the step
        has one: the spec naming no fields.

        Two of them is refused by `check_field_specs()`, which the walk has
        already run — what is left over cannot go to both, and a page
        rendering half its answers through one template and half through
        another, silently, is a mistake being made quietly.
        """
        whole = [spec for spec in specs if not spec.fields]
        if not whole:
            return None
        return whole[0]

    def get_field_specs(self, step: RuntimeStep) -> Sequence[FieldSpec]:
        """How one step's fields are shown.

        This page's `summary_overrides` by step name, and failing that
        what the step says about itself — a step view's or form's own
        `summary_fields`. The page has the last word, and says nothing about
        the steps it has no opinion on: an address that reads as an address
        wherever it is asked says so once, next to the address.

        Override to decide per run.
        """
        # A summary page is a step of a wizard served over HTTP, and the
        # viewset refuses a wizard whose steps have no name — so every step
        # a row is built from has one to look up.
        name = cast(str, step.name)
        if name in self.summary_overrides:
            return self.summary_overrides[name]
        return cast("Sequence[FieldSpec]", list(step.summary_fields))

    def _specs_by_field(
        self, step: RuntimeStep, specs: Sequence[FieldSpec]
    ) -> dict[str, tuple[int, FieldSpec]]:
        """Each named field's spec, by field name, with the spec's position
        — which is what tells two identically written groups apart.

        The list is checked first. A step view's own specs were checked at
        import; these may not have been — `get_field_specs()` can decide per
        run, and a page's `summary_overrides` is a mapping nothing walks
        until now.
        """
        check_field_specs(specs, self.field_specs_source(step))
        by_field: dict[str, tuple[int, FieldSpec]] = {}
        for index, spec in enumerate(specs):
            for field_name in spec.fields:
                by_field[field_name] = (index, spec)
        return by_field

    def field_specs_source(self, step: RuntimeStep) -> str:
        """What declared the specs a step is being shown with — this page,
        or the step. Names the place a refusal should be fixed."""
        name = cast(str, step.name)
        if name in self.summary_overrides:
            return f"{self.__class__.__name__}.summary_overrides[{name!r}]"
        return f"step {name!r}'s own summary_fields"

    def build_summary_field(
        self, step: RuntimeStep, form: BaseForm, bound_field: BoundField
    ) -> SummaryField:
        """One answer, on a line of its own.

        The cleaned value comes from the bound field's *own* form, which is
        `form` itself for all but a repeated step — where the fields belong
        to a row rather than to the step, and the step's own `cleaned_data`
        is the list of rows.
        """
        value = self.format_value(
            bound_field, bound_field.form.cleaned_data.get(bound_field.name)
        )
        return SummaryField(
            name=bound_field.name,
            label=bound_field.label,
            value=value,
            parts=(value,) if value else (),
            template_name=self.summary_field_template_name,
            form=bound_field.form,
            bound_field=bound_field,
        )

    def build_group_field(
        self, step: RuntimeStep, form: BaseForm, spec: Group
    ) -> SummaryField:
        """Several answers, on one line.

        The pieces are joined in the order the group names them, not the
        order the form asks them, because that order is the point: an address
        reads street, town, postcode whatever the form does. Empty answers
        drop out, so a blank second line costs the address nothing.
        """
        shown: list[tuple[str, str]] = []
        for field_name in self.grouped_field_names(step, spec):
            try:
                bound_field = form[field_name]
            except KeyError:
                # A dynamic `get_form_class()` need not offer every field a
                # group names, and a group has to survive asking for less.
                continue
            if not self.include_summary_field(step, bound_field):
                continue
            value = self.format_value(bound_field, form.cleaned_data.get(field_name))
            shown.append((field_name, value))
        parts = tuple(value for _, value in shown if value)
        return SummaryField(
            name=shown[0][0] if shown else (step.name or ""),
            label=spec.label,
            value=spec.separator.join(parts),
            parts=parts,
            template_name=spec.template_name or self.summary_field_template_name,
            form=form,
        )

    def claimed_field_names(self, step: RuntimeStep) -> set[str]:
        """Every field name some spec of this step names.

        What is left over is what a spec naming none speaks for, which is
        the only reason anything asks. The walk itself never does: a named
        field's spec answers for it when the walk arrives.
        """
        return {name for spec in self.get_field_specs(step) for name in spec.fields}

    def build_render_field(
        self,
        step: RuntimeStep,
        form: BaseForm,
        spec: Render,
    ) -> SummaryField:
        """The whole step's answer, on one template.

        Every field the step shows, in form order — a `Hide` and
        `include_summary_field()` still drop what they drop — formatted as
        `Group` would format them, so a template that wants the library's
        display text has it and one that wants past it has `form`.

        The name is the first answer shown, as a group's is, and the step's
        own when there is none to take: a `Render` renders whatever the
        step holds, an empty answer included, because the template is the
        point rather than the values.

        `value` is the answers joined plainly, for a template that wants
        the one-line reading. A template wanting another join has `parts`
        and Django's `join` filter, which is why the spec takes no
        separator; `label` is None for the same kind of reason, the row's
        heading being the only name a one-field row needs.
        """
        claimed = self.claimed_field_names(step)
        shown: list[tuple[str, str]] = []
        for bound_field in step.answer_fields:
            if bound_field.name in claimed:
                continue
            if not self.include_summary_field(step, bound_field):
                continue
            value = self.format_value(
                bound_field, bound_field.form.cleaned_data.get(bound_field.name)
            )
            shown.append((bound_field.name, value))
        parts = tuple(value for _, value in shown if value)
        return SummaryField(
            name=shown[0][0] if shown else (step.name or ""),
            label=None,
            value=", ".join(parts),
            parts=parts,
            template_name=spec.template_name,
            form=form,
        )

    def grouped_field_names(self, step: RuntimeStep, spec: Group) -> Sequence[str]:
        """The fields a group joins: the ones it names, in its own order.

        A group naming none takes what no other spec named, in form order —
        the same rule every spec answers to, which here reads as *the rest
        of this step, on one line*.
        """
        if spec.fields:
            return spec.fields
        claimed = self.claimed_field_names(step)
        return [
            bound_field.name
            for bound_field in step.answer_fields
            if bound_field.name not in claimed
        ]

    def include_summary_field(self, step: RuntimeStep, bound_field: BoundField) -> bool:
        """Whether `bound_field` earns a line on the summary. Override to
        hide fields the user should not be shown their own answer to."""
        return True

    def get_summary_label(self, step: RuntimeStep) -> StrOrPromise:
        """The heading for a step's row: its `label` context if it declares
        one (`.step(Form, name="billing", label="Billing")`),
        otherwise its name made readable."""
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
