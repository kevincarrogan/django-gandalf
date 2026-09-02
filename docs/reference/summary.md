# Summary

`gandalf.summary` — a check-your-answers page: the answers of a run as a
flat list of rows, each a question, its answer as display text, and the URL
that changes it.
An optional module; nothing in the core depends on it.

```python
from gandalf.summary import (
    Answer,
    Hide,
    Question,
    RowSpec,
    SummaryMixin,
    SummaryRow,
    check_row_specs,
    format_value,
)
```

---

## Levels of customisation

A summary page is meant to work before you configure anything, and to keep
working as you take it apart. Each level below leaves the ones above it
intact — you reach for a lower one only for what the ones above cannot say.

| | You write | You get |
| --- | --- | --- |
| **Nothing** | mix in [`SummaryMixin`](#summarymixin) and loop `summary` in a template | every answer of every answered step, one row each, named by the field that asked it, values as display text |
| **Declare** | [`summary_rows`](#where-shaping-is-declared) on the step's view, or at its declaration: `Answer`, `Hide` | answers joined onto one row or dropped, said once, next to the step |
| | [`Question(text, spec)`](#questiontext-spec) | a question for a row no single field asked |
| | `.step(Form, name="address", label="Address")` | the name such a row takes when no `Question` gives it one |
| **Render** | [`Answer(template_name=…)`](#rendering-a-row-through-its-own-template) | that row's markup, rendered by Gandalf into `row.answer` |
| **Override** | `summary_overrides` on the review page | this page saying something different from the step |
| | `format_value(bound_field, value)` | how a value reads, everywhere on the page |
| | `include_summary_field(step, bound_field)` | which answers appear at all |
| **Extend** | [a spec of your own](#writing-a-spec) | several rows from one step, or anything else a spec can build |
| | [`get_row_specs(step)`](#choosing-specs-per-run) | which specs a step gets, decided per run |
| **Build** | `build_field_row` / `build_answer_row` / `render_row` | how one row is built |
| | [`build_summary_rows(step)`](#a-step-whose-answer-is-not-one-forms-worth) | every row one step makes |
| **Replace** | `get_summary_rows()` | the rows themselves: a different order, or rows from somewhere other than the steps |
| | `get_summary_steps()` | which steps are summarised at all |

Two boundaries in that table are worth knowing.

**Between *Declare* and *Render*** is where the library stops deciding how a
row reads and starts rendering markup you wrote. Above it you are describing
the answer; below it you are writing a template, and everything the library
knows about the row is handed to it — `row.parts` for the formatted pieces,
`row.form` for the whole validated form.

**Between *Extend* and *Build*** is where a declaration stops being enough.
A spec is a thing a page can hold in a list, check, and reuse; a `build_*`
override is a method with a step in it. Prefer the spec: three of the four
worked examples further down were `build_*` overrides once, and each read
worse than the spec that replaced it.

### Where shaping is declared

The same specs can be declared in three places. The page wins over the
step, and the step says it once — on its view, or at its declaration, but
not both:

| Where | What it says | Reach for it when |
| --- | --- | --- |
| `SummaryMixin.summary_overrides` on the review page | this step, on this page, reads like this | one page disagrees, or the step is not yours to change |
| `summary_rows` on the step's view | this step's answers read like this, wherever it is asked | the step has a view of its own — the ordinary place |
| `summary_rows` at the declaration | the same, for a step with no view to say it on | `.step(AddressForm, name="address", ...)` |

**Not on the form.** A `forms.Form` is a Django object shared with everything
else that asks it, and a Gandalf attribute on it is this library squatting in
a namespace it does not own — as well as a form knowing about a page it never
renders. A form carrying `summary_rows` is refused by `.step()` rather than
ignored, because a declaration nothing reads is worse than one that fails.

**Said once.** A step whose view declares specs *and* whose declaration
names them is a step answering one question twice, and `.step()` refuses
that too. Which of the two to use is a question about the step, not about
the summary: a step with view-level behaviour already has a class to put
them on, and a step that is a bare form does not.

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Answer, Hide


class AddressStepView(StepFormView):
    form_class = AddressForm
    template_name = "grants/address.html"
    summary_rows = [
        Answer("line_1", "line_2", "town", "postcode"),
        Hide("lookup_token"),
    ]
```

Or, for a step that is a bare form, beside the `name` and `label` it already
declares there:

```python
Wizard().step(
    AddressForm,
    name="address",
    label="Address",
    summary_rows=[
        Answer("line_1", "line_2", "town", "postcode"),
        Hide("lookup_token"),
    ],
)
```

The review page then names no steps at all:

```python
class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
```

An address is an address wherever it is asked, so the step is where that
belongs — and a page listing every awkward step by name is a page carrying
knowledge it did not generate. A page that *does* disagree says so in
`summary_overrides`, and wins for that step. A key there with an empty
sequence is an opinion rather than a silence: it overrides the step back to
one row per field.

A step's own specs are checked exactly as a page's are, against the fields
the step declares — see [Spec validation](#spec-validation).

---

## Reference

### `SummaryMixin`

Adds a flat list of `SummaryRow`s to a step view's template context. Mix it
into the `FormView` of a check-your-answers step, ahead of
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
| `summary_label_context_key` | `"label"` | the step-context key a step-named row reads its name from |
| `summary_overrides` | `{}` | `Mapping[str, Sequence[RowSpec]]` — what this page wants said differently, keyed by step name. A step it does not mention reads as the step itself says, and failing that as one row per field. A key with an empty sequence overrides the step back to plain |

**Hooks** — override on the view, deferring to `super()` for the cases you
do not special-case:

| Hook | Returns | Default |
| --- | --- | --- |
| `get_summary_steps()` | `list[RuntimeStep]` | every step in `request.run.path` whose declaration is not `request.run.rendering` — the step being rendered |
| `get_summary_rows()` | `list[SummaryRow]` | runs the checks, then `build_summary_rows()` per summarised step |
| `build_summary_rows(step)` | `Iterator[SummaryRow]` | one step's rows: its fields — `step.answer_fields`, so the *step view* decides what they are — in form order with its specs folded in. What a spec contributes is the spec's own answer (`RowSpec.build_rows()`), not a branch here: it speaks once, at the first of its fields the page shows |
| `build_field_row(step, form, bound_field)` | `SummaryRow` | one answer on a row of its own, asked by the field that asked it |
| `build_answer_row(step, form, spec, question=None)` | `SummaryRow` | several answers on one row (see `Answer`); `question` is the `Question`'s if one asked it |
| `render_row(row, template_name)` | `SummaryRow` | the row with its `answer` rendered through `template_name`, when its spec named one. The only template Gandalf renders, and never one of its own |
| `answered_bound_fields(step, form, spec)` | `Sequence[BoundField]` | the bound fields one row joins: the ones it names, or — naming none — what no other spec named, in form order |
| `claimed_field_names(step)` | `set[str]` | every field name some spec of this step names. What is left is what a spec naming none speaks for |
| `get_row_specs(step)` | `Sequence[RowSpec]` | this page's `summary_overrides` by step name, and failing that the step's own `summary_rows`; override to decide per run |
| `get_whole_step_spec(specs)` | `RowSpec \| None` | the spec naming no fields, which speaks for what no other spec named |
| `row_specs_source(step)` | `str` | what declared the specs a step is shown with — this page's `summary_overrides`, or the step's own `summary_rows`. Names the place a refusal should be fixed |
| `check_summary_overrides()` | `None` | raises `ImproperlyConfigured` for a `summary_overrides` key naming no declared step |
| `check_summary_row_names()` | `None` | raises for a spec of this page's naming a field its step has not got |
| `check_step_field_names(step, fields)` | `None` | the same, for a step's *own* specs. Called per step during the build rather than in a pass of its own: asking a step sets its view up, and a second pass would build every step's view twice |
| `check_field_names(step_name, specs, fields, source)` | `None` | the check both of those defer to; `source` is what named the fields, so the message says where the fix is |
| `get_declared_step_names()` | `set[str] \| None` | every `name` the wizard's tree declares; `None` when the tree contains an `.expand()`, whose steps are not known until walked |
| `include_summary_field(step, bound_field)` | `bool` | `True`; return `False` to drop a field. Consulted for a field's own row and for each piece of a joined one |
| `get_summary_question(step)` | `StrOrPromise` | what a row asks when no field and no `Question` asked it: the step's `label` context if it declares one, otherwise its name with `_` and `-` replaced by spaces and the first letter capitalised (`"business_name"` → `"Business name"`) |
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
- **One form per step, not per row.** Reading a step's answers means
  reconstructing and re-validating its form. Every row of a step is built
  from one `step.form`, and `RuntimeStep.form` is itself built once per step
  per request, so a step that reads as seven rows costs what a step that
  reads as one costs. A summary render still costs two validations per
  answered step — the walk proves each answer, then the rows read it back —
  where an ordinary step page costs one. See [Walk costs](walk-costs.md).
- The mixin reads `self.request.run`, so it works only on a view
  dispatched inside a wizard.

### A step whose answer is not one form's worth

A summary lists `step.answer_fields`, which the step's own view decides —
so a step holding a formset lists every row's fields, row by row, rather
than iterating the formset and finding sub-*forms* where bound fields were
expected (see [Step views](step-views.md)).

That default is plain rather than pretty on purpose. How three organisers
should read on a check-your-answers page is this page's decision, and an
`Answer` naming no fields is the short way to make it — one template for the
whole step, reaching its rows through `row.form.cleaned_data`:

```python
from gandalf.summary import Answer, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    summary_overrides = {
        "opening-hours": [Answer(template_name="grants/summary/hours.html")],
    }
```

For several *rows* for one step — one per formset row, each with its own
label and value — write a spec of your own: see
[Writing a spec](#writing-a-spec). `build_summary_rows(step)` is the longest
way, and the only one that can also ignore the step's fields entirely.

```python
from gandalf.summary import SummaryMixin, SummaryRow


class ReviewStepView(SummaryMixin, StepFormView):
    def build_summary_rows(self, step):
        if step.name != "opening-hours":
            yield from super().build_summary_rows(step)
            return
        for row in step.answer:
            yield SummaryRow(step=step, label=row["day"], value=row["opens"])
```

`Answer` naming fields and `Hide` address a step's *own* declared fields,
and a formset step declares none at step level, so neither reaches into its
rows. An `Answer` naming no fields does not need to.

The summary page is not the only reader that shows a person their answers.
What a step's own `summary_rows` hides, the [driver](driver.md) leaves out of
`describe()` and `outline()` too — the schema an agent is given does not ask
for the token, and the answers it reads back do not carry it — while the
run's record keeps it. A page's `summary_overrides` hides on that page only.

### Spec validation

The checks run before and during the build and raise
`django.core.exceptions.ImproperlyConfigured` when:

| Condition | Message |
| --- | --- |
| a `summary_overrides` key names a step the wizard does not declare | `<View>.summary_overrides shapes steps this wizard does not declare: <keys>. Declared steps: <names>.` |
| a spec of this page's names a field its step does not declare | `<View>.summary_overrides shapes fields step '<step>' does not declare: <fields>. Its fields: <names>.` |
| a spec of the *step's own* names a field it has not got | `step '<step>'s own summary_rows shapes fields step '<step>' does not declare: <fields>. Its fields: <names>.` |
| a `Question` wraps a `Question` | `<source> has a Question ('<label>') inside a Question. …` |
| a `Question` wraps a `Hide` | `<source> has a Hide inside a Question ('<label>'), which is a row named and then not shown. …` |
| a field name appears in two specs for one step | `<source> names '<field>' more than once; a field belongs to one spec.` |
| two specs for one step name no fields | `<source> has more than one spec that names no fields, and what no other spec named cannot go to both.` |

A step's own specs are checked as strictly as a page's, and the message
names the source — `AddressStepView.summary_rows`,
`ReviewStepView.summary_overrides['address']` — because that is where the
fix is.

**There is no check that every field is accounted for**, and there does not
need to be: a field no spec names keeps a row of its own, so a field added
to a form appears on the summary the moment it is added, whatever else the
step says about itself.

**The last four are checked at import.** They need nothing but the spec list
to decide, so `StepFormView.__init_subclass__` runs
[`check_row_specs()`](#check_row_specsspecs-source) when a step view's class
body executes: a step view saying something impossible fails at startup
rather than when someone opens the summary page. The build checks again,
because a list `get_row_specs()` invents per run, or a page's
`summary_overrides`, is one nothing saw at import.

The name checks read the *declaration*, not what this run walked, so a
`summary_overrides` key naming a step on the arm not taken is fine. They are
skipped entirely for a wizard containing an `.expand()`, because a name that
looks unknown may simply not have been grown yet, and the field check is
skipped for a step whose view chooses its form class per request — what such
a step asks cannot be read off the declaration.

That last exemption is the point of the check. At render, a field a spec
names but the step does not offer is skipped rather than refused, so a row
survives a dynamic form asking for less. Where the fields *are* declared,
the same silence would swallow a typo: a misspelt `Hide` hides nothing and
renders the answer it was meant to keep off the page.

**Not checked: whether a `template_name` exists.** A name that resolves to
no template raises `TemplateDoesNotExist` while the page's rows are being
built — in the view, with a traceback naming the step — rather than halfway
through the markup. That is late, but it is loud, and it is why rows are
rendered when they are built rather than lazily in the template.

### `Answer(*fields, separator=", ", template_name=None)`

Some of a step's fields, read as one row.

**Parameters**

- `*fields` — field names, in the order the pieces should read. The join
  order is the spec's, not the form's: an address reads street, town,
  postcode whatever the form asks first. Naming none means *the rest*: every
  field of the step no other spec named.
- `separator` — what the non-empty pieces are joined with. Default `", "`.
- `template_name` — the template this row's value renders through. Gandalf
  renders it and the result lands on `SummaryRow.value`, marked safe. See
  [Rendering a row through its own template](#rendering-a-row-through-its-own-template).

**Attributes** — `fields` (a tuple), `separator`, `template_name`. Frozen.

**Caveats**

- It carries no question of its own. The row is asked by the step —
  `get_summary_question()` — or by the [`Question`](#questiontext-spec)
  around it. Two ways to name one thing is what a summary page does not
  need.
- Each piece is rendered through the view's `format_value()`, and the empty
  ones are dropped, so a blank second address line does not leave `", ,"`.
- The spec takes the place of the first of its fields in form order and
  swallows the rest; the resulting `SummaryRow.name` is the first field
  actually shown, or the step's name when it showed none.
- A field the form does not offer is skipped. One none of whose fields the
  form offers still builds a row — its template is the point rather than its
  values, which is how an empty formset says "none given".
- Pieces the view's `include_summary_field()` rejects are left out of the
  join.
- `SummaryRow.bound_field` is `None`: no single `BoundField` can stand for
  several answers. `SummaryRow.form` is the step's form, so
  `row.form.cleaned_data` reaches a value derived in `clean()` — the reach a
  field list cannot name, offered anyway.
- Rendering from `cleaned_data` gives up `format_value` — a choice is its
  key rather than its label, a boolean is `True` rather than `Yes`, a date
  is not in the active locale — so the row still carries the formatted
  answers in `parts`. A template takes whichever it wants.

### `Question(text, spec)`

The question a row asks, when the step could not ask it.

A step is a page, and a page that asked one thing is named by the step: the
address step's row is called Address without anyone saying so. A page that
asked three reads as three rows sharing one change link, and the step's name
will do for at most one of them.

```python
class ApplicantStepView(StepFormView):
    form_class = ApplicantForm
    summary_rows = [
        Question("Address", Answer("line_1", "line_2", "town")),
        Question("Postcode", Answer("postcode")),
        Hide("lookup_token"),
    ]
```

```
Address    12 High Street, Ely    Change
Postcode   CB7 4AA                Change
```

**Parameters**

- `text` — the question itself.
- `spec` — the one spec whose row it asks.

**Attributes** — `text`, `spec`, and `fields`, which is its spec's. Frozen.

**Caveats**

- It wraps exactly one spec and does one thing to it. Everything about
  *what* the row says is the spec's, which is why a `Question` takes no
  separator, no template and no fields of its own.
- The question goes *down* into the spec rather than being applied after, so
  a template rendering the answer already sees the question the page will
  show it under.
- Every row a step makes carries the same `step`, so `row.url` is the same
  page for all of them. That is the point: three things to check, one place
  to go and fix any of them.
- A `Question` wrapping an `Answer` that names no fields is the shape to
  reach for when a row's value comes from a template and its name comes
  from the page that asked it — a date of birth spread over three inputs,
  say, whose answer is in `cleaned_data` and in no field.
- A `Question` inside a `Question`, or a `Hide` inside one, is refused.

### `Hide(*fields)`

Fields the summary does not show — an address lookup token, a hidden
nonce. It claims its fields and builds no row, which is what hiding is.
**Attributes** — `fields` (a tuple). Frozen.

### `check_row_specs(specs, source)`

Module-level. Refuses a list of specs that contradicts itself — a field
claimed by two specs, two specs naming no fields, or a `Question` wrapping
something that is not one row's worth of answer. `source` is what declared
them, and appears in the message.

Every rule is decidable from the list alone, which is why
`StepFormView.__init_subclass__` calls this at import. It is called again
when a page builds its rows, for the lists import time could not see.

Whether a spec names a field its step has not got is *not* here: that needs
the step, so it stays with the page — `check_field_names()`.

### `RowSpec`

A `Protocol`. `Answer`, `Hide` and `Question` are the specs Gandalf ships;
anything answering these two questions is one.

| Member | Type | What it says |
| --- | --- | --- |
| `fields` | `tuple[str, ...]` | the field names this spec speaks for. Empty means the rest |
| `build_rows(view, step, form, question=None)` | `Iterator[SummaryRow]` | the rows it stands for — none, one, or several |

One rule holds them together, and it is the whole of the arrangement:

> A spec speaks for the fields it names. A spec naming none speaks for
> every field no other spec named.

Everything else follows from it. `Hide("token")` claims the token and
builds nothing, which is what hiding is. `Answer(template_name="hours.html")`
names none, so it claims what is left — usually the lot. An `Answer` beside
one is not a conflict but a sentence that parses: these fields on one row,
the rest on another.

A spec speaks once, at the first of its fields the page shows. One naming
no fields speaks at the first field nothing else claimed — or last, and for
nothing, when the step had nothing left to give it: an empty formset still
renders its template, because the template is the point rather than the
values. Two specs naming no fields is the one shape refused, because what
is left over cannot go to both.

`build_summary_rows()` asks; it does not decide. It knows none of the three
by type, which is what makes a spec of your own an ordinary one.

#### Writing a spec

`build_rows()` may yield several rows, which no spec Gandalf ships does —
one row of a repeated step per summary row, say:

```python
from gandalf.summary import SummaryRow


class Repeat:
    """Each row of a repeated step as its own summary row."""

    def __init__(self, label_field, value_field):
        self.label_field = label_field
        self.value_field = value_field

    @property
    def fields(self):
        return ()

    def build_rows(self, view, step, form, question=None):
        for row in step.answer:
            yield SummaryRow(
                step=step,
                question=row[self.label_field],
                answer=row[self.value_field],
                form=form,
            )
```

```python
summary_overrides = {"opening-hours": [Repeat("day", "opens")]}
```

`view` is the summary page, so defer to it rather than deciding for it:
`view.format_value()` renders a value, `view.include_summary_field()` says
whether an answer is shown at all, `view.get_summary_question()` is what a
step asks on behalf of a row that asks nothing itself, and
`view.claimed_field_names()` is what a spec naming no fields subtracts to
find its own. `question` is what a `Question` around it asked, and `None`
when nothing did.

### `SummaryRow`

One row of a check-your-answers page. Frozen dataclass. The page reads back
the words the declaration wrote — `Question` and `Answer` there,
`row.question` and `row.answer` here.

| Attribute | Type | What it is |
| --- | --- | --- |
| `step` | `RuntimeStep` | the step this answer came from; `row.step.data` is the raw submission, `row.step.name` is what to group rows by |
| `question` | `StrOrPromise` | what the row asks — the field's label, the `Question`'s text, or `get_summary_question(step)`. Never `None` |
| `answer` | `str` | the display text: one answer formatted, several joined, or a template already rendered — in which case it is marked safe, as `form.as_p()` is. `""` for an unanswered field |
| `name` | `str` | the answer's name: the field's, the first field a joined row showed, or the step's when it showed none. Default `""` |
| `parts` | `tuple[str, ...]` | what a joined `answer` was made from: one per non-empty answer, `(value,)` for an answered plain field, `()` for an empty one. Still populated when a template rendered the answer. Default `()` |
| `url` | `str \| None` | property — `step.url`, the step's own URL: the change link. `None` without a URL reverser (programmatic use) |
| `form` | `BaseForm \| None` | the bound, validated form the answer came from — `form.cleaned_data` included, which is where a value derived in `clean()` lives. For a plain field it is the bound field's own form, which differs from the step's for a repeated step. Excluded from `repr` and equality |
| `bound_field` | `BoundField \| None` | the Django `BoundField` the value came from — the widget, help text, field attributes. `None` for a row several fields made. Excluded from `repr` and equality |

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
    <dt>{{ row.question }}</dt>
    <dd>
      <span>{{ row.answer }}</span>
      <a href="{{ row.url }}">Change {{ row.question }}</a>
    </dd>
  {% endfor %}
</dl>
<form method="post">
  {% csrf_token %}
  <button type="submit">Confirm and continue</button>
</form>
```

One loop and nothing to decide: a question, an answer and somewhere to
change it.
An empty submission is still a submission, so a fieldless `ConfirmForm`
satisfies the step on POST.

### Shaping an address into one row

Declared on the step, which is what knows an address is an address:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Answer, Hide


class OrganisationAddressStepView(StepFormView):
    form_class = OrganisationAddressForm
    template_name = "grants/address.html"
    summary_rows = [
        Answer("line_1", "line_2", "town", "postcode"),
        Hide("lookup_token"),
    ]
```

Or on the review page, for a step it wants to read differently — or one
that is not yours to change:

```python
from gandalf.summary import SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
    summary_overrides = {
        "organisation_address": [
            Answer("line_1", "line_2", "town", "postcode"),
            Hide("lookup_token"),
        ],
    }
```

That row is asked by the step — `.step(…, label="Organisation address")`,
else the name made readable. When the step's name is not what the row asks,
`Question("Where the work happens", Answer(…))` says what it asks.

### Rendering a row through its own template

A review template that branches on which step it is holding
(`{% if row.name == "line_1" %}`) accumulates knowledge of every step in the
wizard. An `Answer` names the template that renders it instead, Gandalf
renders it, and the review template goes on printing `{{ row.answer }}`:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Answer, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
    summary_overrides = {
        "organisation_address": [
            Answer(
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
{# grants/summary/address.html #}
<ul>{% for part in row.parts %}<li>{{ part }}</li>{% endfor %}</ul>
<p>{{ row.form.cleaned_data.what3words }}</p>
```

**The context.** The template is rendered with `row` and `view`, plus
whatever the context processors add — not the review template's context,
because it is rendered before the review template runs. `row` carries
everything the answer knows: `row.answer`, `row.parts`, `row.question`,
`row.bound_field` for a plain field, and `row.form` for the whole validated
form. Reach for `row.form.cleaned_data` when the thing to render is not a
field at all — a value the form derived in `clean()`, or one it stitched
together from several answers.

**What comes back is marked safe**, exactly as a rendered template is
anywhere in Django, so `{{ row.answer }}` prints markup for a row that named
a template and escaped text for one that did not. There is nothing in the
page's loop to change either way.

**Gandalf ships no templates.** Every template rendered here is one the
caller named. A row that names none reads as its joined value.

### Rendering a whole step through one template

`Answer` naming fields says which of them read as one row. When *every*
field of a step reads as one row — or when what should be rendered is not a
field at all — it says so by naming none:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Answer, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"
    summary_overrides = {
        "opening_hours": [Answer(template_name="grants/summary/hours.html")],
    }
```

```django
{# grants/summary/hours.html — a formset step, as its rows #}
<ul>
  {% for entry in row.form.cleaned_data %}
    <li>{{ entry.day }} from {{ entry.opens }}</li>
  {% endfor %}
</ul>
```

The step gets one row, so nothing renders twice, and `row.parts` still holds
the formatted answers for a template that wants them. This is the
declarative form of the
[`build_summary_rows()` override](#a-step-whose-answer-is-not-one-forms-worth):
reach for that one only when what a step needs cannot be said in a template
— several rows per step, each with a label computed per row.

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

The pieces of a joined row are formatted through the same hook, so the
override shapes what an `Answer` joins too.

### Choosing specs per run

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Answer, SummaryMixin


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "grants/review.html"

    def get_row_specs(self, step):
        if step.name == "referee" and step.form.cleaned_data.get("same_address"):
            return [Answer("name", "role")]
        return super().get_row_specs(step)
```

`step.form` here is the same memoised form the rows are built from, so the
read costs nothing extra.

---

## Troubleshooting

### `ImproperlyConfigured: ReviewStepView.summary_overrides shapes steps this wizard does not declare: …`

A key in `summary_overrides` names no step of the wizard the view is mounted
in — usually a step renamed since the override was written, or one review
view shared between wizards of which only some have that step. Rename the
key, or move the shaping onto the step itself, where a page that never
mentions the step can still show it correctly and one review view serves
both wizards.

### `ImproperlyConfigured: … names 'town' more than once`

A field belongs to one spec. Two `Answer`s (or an `Answer` and a `Hide`) for
the same step both name it; remove it from one.

### `ImproperlyConfigured: … more than one spec that names no fields`

A spec naming no fields speaks for what no other spec named, and two of
them cannot both have it — two whole-step `Answer`s for one step. Name the
fields on one of them, or drop it.

### `ImproperlyConfigured: … has a Hide inside a Question`

A `Question` names a row; a `Hide` builds none. Move the `Hide` out beside
the questions.

### `TemplateDoesNotExist` when the review page loads

An `Answer` names a `template_name` that resolves to nothing. Rows are
rendered while they are built, so the traceback comes from the view rather
than from the markup — the step in it is the one whose spec named the
template.

### A row asks the step's name rather than a question

A row one field made asks what the field asked; a row several fields made has
no one field to ask for it, so it takes the step's `label`. Wrap the spec in
a `Question` to say what it asks.

### The summary offers to change itself

`get_summary_steps()` drops the step whose declaration is
`request.run.rendering`, which the viewset sets for a routed GET. A
summary built outside a step render — where `rendering` is `None` — excludes
nothing; filter `get_summary_steps()` yourself there.

### A choice field shows its stored value, not its label

The value is no longer in the field's `choices`, or the value is not a `str`
or `int`. A withdrawn choice renders as itself by design; override
`format_value()` to map old values.

### `row.bound_field` is `None`

The row was made by an `Answer` over several fields; no single `BoundField`
can stand for them. Reach the members through `row.form[name]` instead.

### The summary page is slow

Each answered *step* costs one form reconstruction — not each row — and the
walk that reached the page already validated each answer once, so a summary
is two validations per answered step. If a step's `clean()` is expensive,
that is where the time goes; see [Walk costs](walk-costs.md). Reading
`request.run.path` again inside the template — rather than the `summary`
rows — rebuilds every form a second time.

---

**Learn:** [Chapter 7 — The summary](../learn/07-the-summary.md) · **Related:** [Step views](step-views.md), [`Run`](run.md), [Walk costs](walk-costs.md)
