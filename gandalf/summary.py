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
shows none of them — and fields no spec names keep a line of their own.

Every decision is also a hook: `get_summary_steps()` chooses the steps,
`get_summary_label()` names one, `get_field_specs()` shapes one step's
fields, `include_summary_field()` drops fields, and `format_value()` renders
a value. The defaults suit a plain journey; override what your domain needs.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, TypeAlias, cast

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
    "FieldSpec",
    "Group",
    "Hide",
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


#: One instruction about a step's fields, as `summary_fields` carries them.
FieldSpec: TypeAlias = "Group | Hide"


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
    """

    summary_context_name = "summary"
    summary_label_context_key = "label"

    #: The template an answer renders through when its `Group` names none —
    #: and the one every plain field renders through. Set it to give one
    #: page its own house style for an answer.
    summary_field_template_name = FIELD_TEMPLATE_NAME

    #: How each step's fields are shown, keyed by the step's name. Fields no
    #: spec names keep a line of their own, so a step this mapping does not
    #: mention is left exactly as it was.
    summary_fields: Mapping[str, Sequence[FieldSpec]] = {}

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
        self.check_summary_fields()
        self.check_summary_field_names()
        return [self.build_summary_row(step) for step in self.get_summary_steps()]

    def check_summary_fields(self) -> None:
        """Refuse a `summary_fields` key that names no step of this wizard.

        A renamed step would otherwise take its shaping with it and go
        quietly back to one line per field — the kind of regression a page
        only shows you in production. Checked against what the wizard
        *declares* rather than what this run walked, so a key naming a step
        on the arm not taken is fine.
        """
        if not self.summary_fields:
            return
        declared = self.get_declared_step_names()
        if declared is None:
            return
        unknown = sorted(set(self.summary_fields) - declared)
        if not unknown:
            return
        name = self.__class__.__name__
        raise ImproperlyConfigured(
            f"{name}.summary_fields shapes steps this wizard does not "
            f"declare: {', '.join(unknown)}. Declared steps: "
            f"{', '.join(sorted(declared))}."
        )

    def check_summary_field_names(self) -> None:
        """Refuse a `Group` or `Hide` naming a field its step does not have.

        At render a field a step does not offer is skipped, deliberately —
        a dynamic `get_form_class()` may ask for less and a group has to
        survive that. Which is exactly why a *typo* needs catching here: a
        misspelt `Hide` hides nothing, and the answer it was meant to keep
        off the page is rendered onto it. Checked only where the
        declaration knows the fields: a step whose view picks its form per
        request is taken on trust.
        """
        if not self.summary_fields:
            return
        fields = declared_step_fields(self.request.run.wizard)
        if fields is None:
            return
        for step_name, specs in self.summary_fields.items():
            declared = fields.get(step_name)
            if declared is None:
                continue
            named = {
                field
                for spec in specs
                for field in spec.fields
                if field not in declared
            }
            if not named:
                continue
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name}.summary_fields shapes fields step {step_name!r} does "
                f"not declare: {', '.join(sorted(named))}. Its fields: "
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
            fields=tuple(self.get_summary_fields(step, form)),
        )

    def get_summary_fields(
        self, step: RuntimeStep, form: BaseForm
    ) -> Iterator[SummaryField]:
        """The step's answers as display text, in form order, with its specs
        folded in: a group replaces the first of its fields and swallows the
        rest, a hidden field yields nothing, and everything else keeps a line
        of its own."""
        by_field = self._specs_by_field(step, self.get_field_specs(step))
        grouped: set[int] = set()
        for bound_field in step.answer_fields:
            if not self.include_summary_field(step, bound_field):
                continue
            found = by_field.get(bound_field.name)
            if found is None:
                yield self.build_summary_field(step, form, bound_field)
                continue
            index, spec = found
            if isinstance(spec, Hide) or index in grouped:
                continue
            grouped.add(index)
            yield self.build_group_field(step, form, spec)

    def get_field_specs(self, step: RuntimeStep) -> Sequence[FieldSpec]:
        """How one step's fields are shown. The default reads
        `summary_fields` by step name; override to decide per run."""
        # A summary page is a step of a wizard served over HTTP, and the
        # viewset refuses a wizard whose steps have no name — so every step
        # a row is built from has one to look up.
        name = cast(str, step.name)
        return self.summary_fields.get(name, ())

    def _specs_by_field(
        self, step: RuntimeStep, specs: Sequence[FieldSpec]
    ) -> dict[str, tuple[int, FieldSpec]]:
        """Each named field's spec, by field name, with the spec's position
        — which is what tells two identically written groups apart."""
        by_field: dict[str, tuple[int, FieldSpec]] = {}
        for index, spec in enumerate(specs):
            for field_name in spec.fields:
                if field_name in by_field:
                    raise ImproperlyConfigured(
                        f"{self.__class__.__name__}.summary_fields names "
                        f"{field_name!r} more than once for step "
                        f"{step.name!r}; a field belongs to one spec."
                    )
                by_field[field_name] = (index, spec)
        return by_field

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
        for field_name in spec.fields:
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
        # A group is only ever reached through one of its own fields, and that
        # field is both offered and shown — so there is always a name to take.
        name = shown[0][0]
        parts = tuple(value for _, value in shown if value)
        return SummaryField(
            name=name,
            label=spec.label,
            value=spec.separator.join(parts),
            parts=parts,
            template_name=spec.template_name or self.summary_field_template_name,
            form=form,
        )

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
