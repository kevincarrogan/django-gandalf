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

Every decision is a hook: `get_summary_steps()` chooses the steps,
`get_summary_label()` names one, `include_summary_field()` drops fields, and
`format_value()` renders a value. The defaults suit a plain journey; override
what your domain needs.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any

from django.core.files import File
from django.forms import BaseForm
from django.forms.boundfield import BoundField
from django.utils import formats
from django.utils.text import capfirst
from django.utils.translation import gettext

from gandalf.form_views import StepFormView
from gandalf.runtime import RuntimeStep
from gandalf.types import StrOrPromise


if TYPE_CHECKING:
    # A mixin has no bases of its own, but it is only ever mixed into a step
    # view — so at type-check time it is given the class it documents itself
    # as extending. At runtime it stays a plain mixin.
    _SummaryMixinBase = StepFormView
else:
    _SummaryMixinBase = object


__all__ = [
    "SummaryField",
    "SummaryMixin",
    "SummaryRow",
    "format_value",
]


@dataclass(frozen=True)
class SummaryField:
    """One answered field, as display text.

    `bound_field` is the escape hatch: the Django `BoundField` the value came
    from, for templates that need the widget, the help text, or the field's
    own attributes.
    """

    name: str
    label: StrOrPromise
    value: str
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
    """
    if value is None or value == "":
        return ""
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

    The rows come from `request.wizard.path`, so they are the answers on the
    run's resolved route, in walk order, with the selected branch arm inlined
    — never an answer the run has left behind in a dormant arm, and never the
    step doing the summarising, which is dropped explicitly because a run
    revisited or re-opened arrives with that answer stored too.
    """

    summary_context_name = "summary"
    summary_label_context_key = "label"

    def get_summary_steps(self) -> list[RuntimeStep]:
        """The steps to summarise: every answered step on the route, except
        the one doing the summarising.

        A wizard that only runs forwards never has its own summary step in
        `path` — the step being rendered is the cursor, and the cursor is by
        definition unanswered. A run that has been round the houses does: an
        edit revisited from a change link, or a stashed section re-opened
        with `reopen_step` pointing here, both arrive with every answer
        stored, this page's own confirmation included. Dropping it is what
        stops the page offering to change itself.
        """
        rendering = self.request.wizard.rendering
        return [
            step
            for step in self.request.wizard.path
            if step.declaration is not rendering
        ]

    def get_summary_rows(self) -> list[SummaryRow]:
        return [self.build_summary_row(step) for step in self.get_summary_steps()]

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
        cleaned_data = form.cleaned_data
        for bound_field in form:
            if not self.include_summary_field(step, bound_field):
                continue
            yield SummaryField(
                name=bound_field.name,
                label=bound_field.label,
                value=self.format_value(
                    bound_field, cleaned_data.get(bound_field.name)
                ),
                bound_field=bound_field,
            )

    def include_summary_field(self, step: RuntimeStep, bound_field: BoundField) -> bool:
        """Whether `bound_field` earns a line on the summary. Override to
        hide fields the user should not be shown their own answer to."""
        return True

    def get_summary_label(self, step: RuntimeStep) -> StrOrPromise:
        """The heading for a step's row: its `label` context if it declares
        one (`.step(Form, name="billing", context={"label": "Billing"})`),
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
