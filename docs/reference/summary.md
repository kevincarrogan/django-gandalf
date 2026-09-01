# Summary

`gandalf.summary` — a check-your-answers page: the answered steps of a run
as rows of display text, each with the URL that changes it. An optional
module; nothing in the core depends on it.

```python
from gandalf.summary import (
    FieldSpec,
    Group,
    Hide,
    Render,
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

The rows come from `request.run.path`, so they are the answers on the
run's resolved route, in walk order, with the selected branch arm inlined —
never an answer left behind in a dormant arm, and never the step doing the
summarising.

**Attributes**

| Attribute | Default | What it is |
| --- | --- | --- |
| `summary_context_name` | `"summary"` | the template context variable the rows go in |
| `summary_label_context_key` | `"label"` | the step-context key a row's heading is read from |
| `summary_fields` | `{}` | `Mapping[str, Sequence[FieldSpec]]` — how each step's answers are shown, keyed by step name. A step this mapping does not mention is left as one line per field. |
| `summary_field_template_name` | `FIELD_TEMPLATE_NAME` | the template an answer renders through when its `Group` names none, and the one every plain field renders through |

**Hooks** — override on the view, deferring to `super()` for the cases you
do not special-case:

| Hook | Returns | Default |
| --- | --- | --- |
| `get_summary_steps()` | `list[RuntimeStep]` | every step in `request.run.path` whose declaration is not `request.run.rendering` — the step being rendered |
| `get_summary_rows()` | `list[SummaryRow]` | runs `check_summary_fields()`, then `build_summary_row()` per summarised step |
| `check_summary_fields()` | `None` | raises `ImproperlyConfigured` for a `summary_fields` key naming no declared step (see below) |
| `get_declared_step_names()` | `set[str] \| None` | every `name` the wizard's tree declares; `None` when the tree contains an `.expand()`, whose steps are not known until walked |
| `build_summary_row(step)` | `SummaryRow` | reads `step.form` once and builds the row from it |
| `get_summary_fields(step, form)` | `Iterator[SummaryField]` | the step's fields — `step.answer_fields`, so the *step view* decides what they are — in form order with its specs folded in. What a spec contributes is the spec's own answer (`FieldSpec.build_fields()`), not a branch here: it speaks once, at the first of its fields the page shows |
| `get_field_specs(step)` | `Sequence[FieldSpec]` | `summary_fields.get(step.name, ())`; override to decide per run |
| `get_whole_step_spec(step, specs)` | `FieldSpec \| None` | the spec naming no fields, which speaks for what no other spec named; raises `ImproperlyConfigured` for a second one |
| `build_render_field(step, form, spec)` | `SummaryField` | what a `Render` speaks for, on its template |
| `grouped_field_names(step, spec)` | `Sequence[str]` | the fields a group joins: the ones it names, or — naming none — what no other spec named, in form order |
| `claimed_field_names(step)` | `set[str]` | every field name some spec of this step names. What is left is what a spec naming none speaks for |
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
  section re-opened with `reopen_at` pointing here, arrives with the
  confirmation stored too. `get_summary_steps()` drops it by comparing each
  step's declaration with `request.run.rendering`, which is what stops
  the page offering to change itself.
- **One form per row.** Reading a step's answers means reconstructing and
  re-validating its form. The mixin builds each row from a single
  `step.form`, and `RuntimeStep.form` is itself built once per step per
  request, so a template may read `row.form`, `row.fields` and
  `field.bound_field` freely. A summary render still costs two validations
  per answered step — the walk proves each answer, then the row reads it
  back — where an ordinary step page costs one. See
  [Walk costs](walk-costs.md).
- The mixin reads `self.request.run`, so it works only on a view
  dispatched inside a wizard.

### A step whose answer is not one form's worth

A summary lists `step.answer_fields`, which the step's own view decides —
so a step holding a formset lists every row's fields, row by row, rather
than iterating the formset and finding sub-*forms* where bound fields were
expected (see [Step views](step-views.md)).

That default is plain rather than pretty on purpose. How three organisers
should read on a check-your-answers page is this page's decision, and
[`Render`](#rendertemplate_name) is the short way to
make it — one template for the whole step, reaching its rows through
`field.form.cleaned_data`:

```python
from gandalf.summary import Render, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    summary_fields = {
        "opening-hours": [Render("grants/summary/hours.html")],
    }
```

For several `SummaryField`s for one step — one per row, each with its own
label — write a spec of your own: see [Writing a spec](#writing-a-spec).
`build_summary_row(step)` is the longest way, and the only one that can
also decide the row's own label.

```python
from gandalf.summary import SummaryField, SummaryMixin, SummaryRow


class ReviewStepView(SummaryMixin, StepFormView):
    def build_summary_row(self, step):
        if step.name != "opening-hours":
            return super().build_summary_row(step)
        return SummaryRow(
            step=step,
            label="Opening hours",
            fields=tuple(
                SummaryField(name=f"row-{index}", label=row["day"], value=row["opens"])
                for index, row in enumerate(step.answer)
            ),
        )
```

`Group` and `Hide` address a step's *own* declared fields, and a formset
step declares none at step level, so neither reaches into its rows.
`Render` names no fields, so it does not need to.

### `summary_fields` validation

`check_summary_fields()` runs before rows are built and raises
`django.core.exceptions.ImproperlyConfigured` when:

| Condition | Message |
| --- | --- |
| a key names a step the wizard does not declare | `<View>.summary_fields shapes steps this wizard does not declare: <keys>. Declared steps: <names>.` |
| a spec names a field its step does not declare | `<View>.summary_fields shapes fields step '<step>' does not declare: <fields>. Its fields: <names>.` |
| a field name appears in two specs for the same step | `<View>.summary_fields names '<field>' more than once for step '<step>'; a field belongs to one spec.` |

Both name checks read the *declaration*, not what this run walked, so a key
naming a step on the arm not taken is fine. Both are skipped entirely for a
wizard containing an `.expand()`, because a name that looks unknown may
simply not have been grown yet, and the field check is skipped for a step
whose view chooses its form class per request — what such a step asks
cannot be read off the declaration.

That last exemption is the point of the check. At render, a field a spec
names but the step does not offer is skipped rather than refused, so a
group survives a dynamic form asking for less. Where the fields *are*
declared, the same silence would swallow a typo: a misspelt `Hide` hides
nothing and renders the answer it was meant to keep off the page.

### `Group(*fields, label=None, separator=", ", template_name=None)`

Several of a step's fields, shown as one answer.

**Parameters**

- `*fields` — field names, in the order the pieces should read. The join
  order is the group's, not the form's: an address reads street, town,
  postcode whatever the form asks first.
- `label` — the `SummaryField.label`. Optional; `None` leaves the row's
  heading to name it.
- `separator` — what the non-empty pieces are joined with. Default `", "`.
- `template_name` — the template this answer renders through, reached as
  `SummaryField.template_name`. `None` takes the page's
  `summary_field_template_name`. See
  [Rendering an answer through its own template](#rendering-an-answer-through-its-own-template).

**Attributes** — `fields` (a tuple), `label`, `separator`, `template_name`.
Frozen.

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

### `Render(template_name)`

The whole step's answer, rendered through one template. Names no fields:
listing every field of a step so that one template can ignore the list is
ceremony, and a value no field holds cannot be named in a field list at all.

**Parameters**

- `template_name` — the template this step's answer renders through. Lands
  on `SummaryField.template_name`, like a `Group`'s. The only parameter:
  past `Render` the markup is the caller's, so a `label` and a `separator`
  would be the library shaping output it is not producing. `Group` carries
  both because a group with no template is still rendered by the library.

**Attributes** — `template_name`, and `fields`, which is always `()`.
Frozen.

**Caveats**

- It speaks for every field no other spec named — usually all of them, so
  usually the row has exactly one `SummaryField`.
- The formatted answers are still built: `parts` is one per non-empty
  answer in form order and `value` is them joined with `", "`, so a template
  that wants the library's display text has it — and one wanting another
  join has `parts` and Django's `join` filter. Rendering from `cleaned_data` gives up
  `format_value` — a choice is its key rather than its label, a boolean is
  `True` rather than `Yes`, a date is not in the active locale, and a
  field's own `format_value()` never runs.
- A `Hide` beside a `Render` still hides, and `include_summary_field()` is
  still consulted; both drop the answer from `parts` and `value` without
  hiding it from `form`.
- A `Group` beside a `Render` takes its own fields and leaves the rest —
  they compose rather than conflict. Two specs naming no fields is refused.
- A `Render` left with nothing still speaks, so a step with no answers at
  all renders its template.
- `SummaryField.name` is the first answer shown, or the step's name when
  the step shows none — a `Render` renders whatever the step holds, an
  empty answer included. `SummaryField.label` is `None`: a `Render` is the
  only field its row has, so `row.label` names it.
- For a formset step, `field.form` is the formset, so
  `field.form.cleaned_data` is the list of row dicts.

### `FieldSpec`

A `Protocol`. `Group`, `Hide` and `Render` are the specs Gandalf ships;
anything answering these two questions is one.

| Member | Type | What it says |
| --- | --- | --- |
| `fields` | `tuple[str, ...]` | the field names this spec speaks for. Empty means the rest |
| `build_fields(view, step, form)` | `Iterator[SummaryField]` | the answers it stands for — none, one, or several |

One rule holds them together, and it is the whole of the arrangement:

> A spec speaks for the fields it names. A spec naming none speaks for
> every field no other spec named.

Everything else follows from it. `Hide("token")` claims the token and
yields nothing, which is what hiding is. `Render("hours.html")` names none,
so it claims what is left — usually the lot. A `Group` beside a `Render` is
not a conflict but a sentence that parses: these fields on one line, the
rest through that template. And `Group()` naming nothing means *the rest of
this step, on one line*.

A spec speaks once, at the first of its fields the page shows. One naming
no fields speaks at the first field nothing else claimed — or last, and for
nothing, when the step had nothing left to give it: an empty formset still
renders its template, because the template is the point rather than the
values. Two specs naming no fields is the one shape refused, because what
is left over cannot go to both.

`get_summary_fields()` asks; it does not decide. It knows none of the three
by type, which is what makes a spec of your own an ordinary one.

#### Writing a spec

`build_fields()` may yield several answers, which no spec Gandalf ships
does — one row of a repeated step per answer, say:

```python
from gandalf.summary import SummaryField


class Repeat:
    """Each row of a repeated step as its own answer."""

    def __init__(self, label_field, value_field):
        self.label_field = label_field
        self.value_field = value_field

    @property
    def fields(self):
        return ()

    def build_fields(self, view, step, form):
        for index, row in enumerate(step.answer):
            yield SummaryField(
                name=f"row-{index}",
                label=row[self.label_field],
                value=row[self.value_field],
                form=form,
            )
```

```python
summary_fields = {"opening-hours": [Repeat("day", "opens")]}
```

`view` is the summary page, so defer to it rather than deciding for it:
`view.format_value()` renders a value, `view.include_summary_field()` says
whether an answer is shown at all, and `view.claimed_field_names()` is what
a spec naming no fields subtracts to find its own.

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
| `template_name` | `str` | the template this answer renders through: the `Group`'s if it named one, otherwise the page's `summary_field_template_name`. Default `FIELD_TEMPLATE_NAME` |
| `form` | `BaseForm \| None` | the bound, validated form the answer came from — `form.cleaned_data` included, which is where a value derived in `clean()` lives. For a plain field it is the bound field's own form, which differs from the step's for a repeated step. Excluded from `repr` and equality. |
| `bound_field` | `BoundField \| None` | the Django `BoundField` the value came from — the widget, help text, field attributes. `None` for a group. Excluded from `repr` and equality. |

### `format_value(bound_field, value)`

Module-level. Render one cleaned value as display text; the mixin's
`format_value()` hook calls it.

| `value` | Renders as |
| --- | --- |
| `None` or `""` | `""` |
| anything, where the field carries `format_value()` | whatever the field says, via `str()` |
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

**A field can say how it reads.** The table is what Gandalf recognises, and
a project's own field is by definition not on it — the fall-through is
`str(value)`, which shows a person checking their answers a Python repr.
Give the field a `format_value()` and it is asked instead:

```python
from django import forms


class MoneyField(forms.DecimalField):
    def format_value(self, value):
        return f"£{value:,.2f}"
```

Said once on the field rather than again on every page that shows it. It is
handed the whole answer — a list included, since a field holding several
things knows how they read together — but not an empty one: that an
unanswered field shows blank is the page's rule, and a page wanting *Not
provided* says so by overriding `SummaryMixin.format_value()`.

Django's *widgets* carry a `format_value()` of their own, for rendering an
input's value. This is the answer's display text, and the two are
unrelated. The same field can also carry
[`json_schema()`](driver.md#form_json_schemaform), which is the same idea
for what an agent is told the field takes.

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

### Rendering an answer through its own template

A review template that branches on which step it is holding
(`{% if field.name == "line_1" %}`) accumulates knowledge of every step in
the wizard. A `Group` names the template that renders it instead, and the
review template includes whatever each answer names:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Group, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
    summary_fields = {
        "organisation_address": [
            Group(
                "line_1",
                "line_2",
                "town",
                "postcode",
                template_name="grants/summary/address.html",
            ),
        ],
    }
```

```django
{# grants/review.html — knows no step names #}
{% for field in row.fields %}{% include field.template_name %}{% endfor %}
```

```django
{# grants/summary/address.html #}
<ul>{% for part in field.parts %}<li>{{ part }}</li>{% endfor %}</ul>
<p>{{ field.form.cleaned_data.what3words }}</p>
```

**The context.** `{% include %}` inherits the including template's context,
so the partial sees whatever the review template has — including `row`, if
that is what the loop calls it. What it can rely on without that is `field`,
which carries everything the answer knows: `field.value`, `field.parts`,
`field.label`, `field.bound_field` for a plain field, and `field.form` for
the whole validated form. Reach for `field.form.cleaned_data` when the thing
to render is not a field at all — a value the form derived in `clean()`, or
one it stitched together from several answers. Pass the context explicitly
(`{% include field.template_name with field=field only %}`) if you would
rather the partial not inherit.

**The default.** `FIELD_TEMPLATE_NAME` is `"gandalf/summary/field.html"`,
which renders `{{ field.value }}` and nothing else — the markup around an
answer is the page's. It is the only template Gandalf ships, and reaching it
needs `"gandalf"` in `INSTALLED_APPS` with the app-directories template
loader. Change it for one page with `summary_field_template_name`, or for
every page by shadowing `gandalf/summary/field.html` in your own templates
directory.

A `Hide` takes no template: it renders nothing at all.

### Rendering a whole step through one template

`Group` names the fields that read as one answer. When *every* field of a
step reads as one answer — or when what should be rendered is not a field at
all — `Render` says so without the list:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Render, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
    summary_fields = {
        "opening_hours": [Render("grants/summary/hours.html")],
    }
```

```django
{# grants/summary/hours.html — a formset step, as its rows #}
<ul>
  {% for entry in field.form.cleaned_data %}
    <li>{{ entry.day }} from {{ entry.opens }}</li>
  {% endfor %}
</ul>
```

The row gets one `SummaryField` for the step, so nothing renders twice, and
`field.parts` still holds the formatted answers for a template that wants
them. This is the declarative form of the
[`build_summary_row()` override](#a-step-whose-answer-is-not-one-forms-worth):
reach for that one only when what a row needs cannot be said in a template —
several `SummaryField`s per step, or a label computed per row.

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
or give each wizard its own review view, so each carries only the specs its
own steps need. Two review views are two siblings mixing `SummaryMixin` into
`StepFormView`, not a base and an override: what one wizard shows is not a
partial version of what another shows.

### `ImproperlyConfigured: … names 'town' more than once for step 'address'`

A field belongs to one spec. Two `Group`s (or a `Group` and a `Hide`) for the
same step both name it; remove it from one.

### `ImproperlyConfigured: … more than one spec that names no fields`

A spec naming no fields speaks for what no other spec named, and two of
them cannot both have it — two `Render`s for one step, or a `Render` beside
a `Group()`. Name the fields on one of them, or drop it.

### The summary offers to change itself

`get_summary_steps()` drops the step whose declaration is
`request.run.rendering`, which the viewset sets for a routed GET. A
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
goes; see [Walk costs](walk-costs.md). Reading `request.run.path` again
inside the template — rather than the `summary` rows — rebuilds every form
a second time.

---

**Learn:** [Chapter 7 — The summary](../learn/07-the-summary.md) · **Related:** [Step views](step-views.md), [`Run`](run.md), [Walk costs](walk-costs.md)
