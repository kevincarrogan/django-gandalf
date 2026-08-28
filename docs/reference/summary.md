# Summary

`gandalf.summary` — a check-your-answers page: the answered steps of a run
as rows of display text, each with the URL that changes it. An optional
module; nothing in the core depends on it.

```python
from gandalf.summary import (
    FieldSpec,
    Group,
    Hide,
    SummaryField,
    SummaryMixin,
    SummaryRow,
    format_value,
)
```

---

## Reference

### `SummaryMixin`

Adds a list of `SummaryRow`s to a step view's template context. Mix it into
the `FormView` of a check-your-answers step, ahead of
[`StepFormView`](step-views.md):

```python
class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
```

The rows come from `request.wizard.path`, so they are the answers on the
run's resolved route, in walk order, with the selected branch arm inlined —
never an answer left behind in a dormant arm, and never the step doing the
summarising.

**Attributes**

| Attribute | Default | What it is |
| --- | --- | --- |
| `summary_context_name` | `"summary"` | the template context variable the rows go in |
| `summary_label_context_key` | `"label"` | the step-context key a row's heading is read from |
| `summary_fields` | `{}` | `Mapping[str, Sequence[FieldSpec]]` — how each step's fields are shown, keyed by step name. A step this mapping does not mention is left as one line per field. |

**Hooks** — override on the view, deferring to `super()` for the cases you
do not special-case:

| Hook | Returns | Default |
| --- | --- | --- |
| `get_summary_steps()` | `list[RuntimeStep]` | every step in `request.wizard.path` whose declaration is not `request.wizard.rendering` — the step being rendered |
| `get_summary_rows()` | `list[SummaryRow]` | runs `check_summary_fields()`, then `build_summary_row()` per summarised step |
| `check_summary_fields()` | `None` | raises `ImproperlyConfigured` for a `summary_fields` key naming no declared step (see below) |
| `get_declared_step_names()` | `set[str] \| None` | every `name` the wizard's tree declares; `None` when the tree contains an `.expand()`, whose steps are not known until walked |
| `build_summary_row(step)` | `SummaryRow` | reads `step.form` once and builds the row from it |
| `get_summary_fields(step, form)` | `Iterator[SummaryField]` | the step's fields in form order with its specs folded in: a `Group` takes the place of its first field and swallows the rest, a `Hide` yields nothing |
| `get_field_specs(step)` | `Sequence[FieldSpec]` | `summary_fields.get(step.name, ())`; override to decide per run |
| `build_summary_field(step, form, bound_field)` | `SummaryField` | one answer on a line of its own |
| `build_group_field(step, form, spec)` | `SummaryField` | several answers on one line (see `Group`) |
| `include_summary_field(step, bound_field)` | `bool` | `True`; return `False` to drop a field. Consulted for plain fields and for each member of a group. |
| `get_summary_label(step)` | `StrOrPromise` | the step's `label` context if it declares one, otherwise its name with `_` and `-` replaced by spaces and the first letter capitalised (`"business_name"` → `"Business name"`) |
| `format_value(bound_field, value)` | `str` | the module-level `format_value` |
| `get_context_data(**kwargs)` | `dict` | `super()`'s context with `summary_context_name` set to `get_summary_rows()` |

**Caveats**

- **The summarising step is excluded from its own rows.** A wizard that
  only runs forwards never has its summary step in `path` — the step being
  rendered is the cursor, and the cursor is unanswered. A run that has been
  round the houses does: an edit revisited from a change link, or a stashed
  member re-opened with `reopen_step` pointing here, arrives with the
  confirmation stored too. `get_summary_steps()` drops it by comparing each
  step's declaration with `request.wizard.rendering`, which is what stops
  the page offering to change itself.
- **One form per row.** Reading a step's answers means reconstructing and
  re-validating its form. The mixin builds each row from a single
  `step.form`, and `RuntimeStep.form` is itself built once per step per
  request, so a template may read `row.form`, `row.fields` and
  `field.bound_field` freely. A summary render still costs two validations
  per answered step — the walk proves each answer, then the row reads it
  back — where an ordinary step page costs one. See
  [Walk costs](walk-costs.md).
- The mixin reads `self.request.wizard`, so it works only on a view
  dispatched inside a wizard.

### `summary_fields` validation

`check_summary_fields()` runs before rows are built and raises
`django.core.exceptions.ImproperlyConfigured` when:

| Condition | Message |
| --- | --- |
| a key names a step the wizard does not declare | `<View>.summary_fields shapes steps this wizard does not declare: <keys>. Declared steps: <names>.` |
| a field name appears in two specs for the same step | `<View>.summary_fields names '<field>' more than once for step '<step>'; a field belongs to one spec.` |

The first check is against what the wizard *declares*, not what this run
walked, so a key naming a step on the arm not taken is fine. It is skipped
entirely for a wizard containing an `.expand()`, because a name that looks
unknown may simply not have been grown yet. A field a spec names that the
step's form does not offer is skipped, not refused.

### `Group(*fields, label=None, separator=", ")`

Several of a step's fields, shown as one answer.

**Parameters**

- `*fields` — field names, in the order the pieces should read. The join
  order is the group's, not the form's: an address reads street, town,
  postcode whatever the form asks first.
- `label` — the `SummaryField.label`. Optional; `None` leaves the row's
  heading to name it.
- `separator` — what the non-empty pieces are joined with. Default `", "`.

**Attributes** — `fields` (a tuple), `label`, `separator`. Frozen.

**Caveats**

- Each piece is rendered through the view's `format_value()`, and the empty
  ones are dropped, so a blank second address line does not leave `", ,"`.
- The group takes the place of the first of its fields in form order and
  swallows the rest; the resulting `SummaryField.name` is the first field
  actually shown.
- A field the form does not offer is skipped. A group none of whose fields
  the form offers never speaks for the row at all.
- Members the view's `include_summary_field()` rejects are left out of the
  join.

### `Hide(*fields)`

Fields the summary does not show — an address lookup token, a hidden
nonce. **Attributes** — `fields` (a tuple). Frozen.

### `FieldSpec`

Type alias: `Group | Hide`. What a `summary_fields` value is a sequence of.

### `SummaryRow`

One answered step. Frozen dataclass.

| Attribute | Type | What it is |
| --- | --- | --- |
| `step` | `RuntimeStep` | the underlying step; `row.step.data` is the raw submission, `row.step.declaration.context` its context |
| `label` | `StrOrPromise` | from `get_summary_label(step)` — a `str` or a lazy translation |
| `fields` | `tuple[SummaryField, ...]` | default `()` |
| `name` | `str \| None` | property — `step.name` |
| `url` | `str \| None` | property — `step.url`, the step's own URL: the change link. `None` without a URL reverser (programmatic use) |
| `form` | `BaseForm` | property — `step.form`, the bound, validated form behind the row |

### `SummaryField`

One answer as display text. Frozen dataclass.

| Attribute | Type | What it is |
| --- | --- | --- |
| `name` | `str` | the field's name; for a group, the first field shown |
| `label` | `str \| None` | the bound field's `label`; a group's `label`, which may be `None` |
| `value` | `str` | the display text; `""` for an unanswered field |
| `parts` | `tuple[str, ...]` | what `value` was joined from: one per non-empty answer for a group, `(value,)` for an answered plain field, `()` for an empty one. Default `()` |
| `bound_field` | `BoundField \| None` | the Django `BoundField` the value came from — the widget, help text, field attributes. `None` for a group. Excluded from `repr` and equality. |

### `format_value(bound_field, value)`

Module-level. Render one cleaned value as display text; the mixin's
`format_value()` hook calls it.

| `value` | Renders as |
| --- | --- |
| `None` or `""` | `""` |
| a `list` or `tuple` (a `MultipleChoiceField` answer) | each item formatted and joined with `", "`; `[]` is `""` |
| a `bool` | `Yes` / `No`, via `gettext` |
| a `str` or `int` matching one of the field's `choices` (optgroups flattened) | the choice's label |
| a `datetime.datetime` | `formats.date_format(value, "DATETIME_FORMAT")` — the active locale |
| a `datetime.date` | `formats.date_format(value, "DATE_FORMAT")` |
| a `datetime.time` | `formats.time_format(value, "TIME_FORMAT")` |
| a `django.core.files.File` (an upload) | `value.name`, or `""` |
| anything else | `str(value)` |

Checks run in that order, so a choice value no longer in `choices` renders
as itself, and a `ModelChoiceField`'s model instance — not a `str` or `int`
— falls through to its own `__str__` without the queryset being consulted.

---

## Usage

### A review step

```python
from django import forms

from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ConfirmForm(forms.Form):
    """No fields. The button is the confirmation."""


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"


class GrantApplicationViewSet(WizardViewSet):
    url_name = "grant"
    template_name = "grants/step.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant", label="About you")
        .step(OrganisationForm, name="organisation", label="Your organisation")
        .step(ReviewStepView, name="review")
    )
```

```django
<h1>Check your answers</h1>
<dl>
  {% for row in summary %}
    <dt>{{ row.label }}</dt>
    <dd>
      {% for field in row.fields %}
        <span>{% if field.label %}{{ field.label }}: {% endif %}{{ field.value }}</span>
      {% endfor %}
      <a href="{{ row.url }}">Change {{ row.label }}</a>
    </dd>
  {% endfor %}
</dl>
<form method="post">
  {% csrf_token %}
  <button type="submit">Confirm and continue</button>
</form>
```

An empty submission is still a submission, so a fieldless `ConfirmForm`
satisfies the step on POST.

### Shaping an address into one line

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Group, Hide, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
    summary_fields = {
        "organisation_address": [
            Group("line_1", "line_2", "town", "postcode"),
            Hide("lookup_token"),
        ],
    }
```

```django
{% for part in field.parts %}<span>{{ part }}</span><br>{% endfor %}
```

`field.parts` renders the address as lines; `field.value` is the same
pieces joined with `", "`.

### Formatting a domain value

```python
from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"

    def format_value(self, bound_field, value):
        if bound_field.name == "amount_requested":
            return f"£{value:,.2f}"
        return super().format_value(bound_field, value)
```

Group members are formatted through the same hook, so the override shapes
what a group joins too.

### Choosing specs per run

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Group, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"

    def get_field_specs(self, step):
        if step.name == "referee" and step.form.cleaned_data.get("same_address"):
            return [Group("name", "role")]
        return super().get_field_specs(step)
```

`step.form` here is the same memoised form the row is built from, so the
read costs nothing extra.

---

## Troubleshooting

### `ImproperlyConfigured: ReviewStepView.summary_fields shapes steps this wizard does not declare: …`

A key in `summary_fields` names no step of the wizard the view is mounted
in — usually a step renamed since the spec was written, or a review view
shared between wizards of which only some have that step. Rename the key,
or subclass the view per wizard so each carries only the specs its steps
need.

### `ImproperlyConfigured: … names 'town' more than once for step 'address'`

A field belongs to one spec. Two `Group`s (or a `Group` and a `Hide`) for the
same step both name it; remove it from one.

### The summary offers to change itself

`get_summary_steps()` drops the step whose declaration is
`request.wizard.rendering`, which the viewset sets for a routed GET. A
summary built outside a step render — where `rendering` is `None` — excludes
nothing; filter `get_summary_steps()` yourself there.

### A choice field shows its stored value, not its label

The value is no longer in the field's `choices`, or the value is not a `str`
or `int`. A withdrawn choice renders as itself by design; override
`format_value()` to map old values.

### `field.bound_field` is `None`

The field is a `Group`; no single `BoundField` can stand for several. Reach
the members through `row.form[name]` instead.

### The summary page is slow

Each row costs one form reconstruction, and the walk that reached the page
already validated each answer once, so a summary is two validations per
answered step. If a step's `clean()` is expensive, that is where the time
goes; see [Walk costs](walk-costs.md). Reading `request.wizard.path` again
inside the template — rather than the `summary` rows — rebuilds every form
a second time.

---

**Learn:** [Chapter 6 — The summary](../learn/06-the-summary.md) · **Related:** [Step views](step-views.md), [`BoundWizard`](bound-wizard.md), [Walk costs](walk-costs.md)
