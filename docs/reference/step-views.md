# Step views

`gandalf.form_views` — the `FormView` behind a step: the base class a step
brings its own view from, and the factory that generates one for a bare
`Form`.

```python
from gandalf.form_views import StepFormView, form_view_factory
from gandalf.types import WizardRequest
```

---

## Reference

### `StepFormView`

A plain Django `FormView` with the one piece of wizard boilerplate already
written. Subclass it in place of `FormView` when a step needs view-level
behaviour — a per-step template, `get_initial()`, `get_form_kwargs()`, a
`form_valid()` that reads the request. The views Gandalf generates for bare
`Form`s are built on the same class, so a view you write and a view Gandalf
generates answer a submission the same way.

**What it adds over `FormView`**

- `get_success_url()` returns `self.request.path`. Gandalf reads only the
  *status code* of a step's response and then discards it, so the success
  URL is never followed; every step view would otherwise have to write the
  same no-op redirect back onto itself.
- `request` is typed as `WizardRequest` — an `HttpRequest` carrying
  `run` — so `self.request.run` type-checks with no cast (Gandalf ships
  `py.typed`).
- `form_class` is restated as `type[forms.BaseForm] | None`, so a
  `ModelForm` step type-checks.

**Attributes**

| Attribute | Required | Notes |
| --- | --- | --- |
| `form_class` | yes | Any `BaseForm` subclass. Default `None`. |
| `template_name` | yes | **Not inherited from the viewset.** `WizardViewSet.template_name` reaches only the views Gandalf generates; a step with its own view renders with `ImproperlyConfigured` ("TemplateResponseMixin requires either a definition of 'template_name' or an implementation of 'get_template_names()'") without one. |
| `request` | — | A `WizardRequest` inside a wizard dispatch; a plain `HttpRequest` when the class is mounted standalone. |

**Caveats**

- A `StepFormView` keeps its own configuration, so the same class can be
  mounted as an ordinary standalone view outside the wizard (`path("edit/",
  ContactStepView.as_view())`). Mounted that way it is handed a plain
  request with no `run` attribute; override `get_success_url()` there to
  go somewhere real.
- Nothing else changes. Django's `FormView` composition API — `form_class`,
  `get_form_class()`, `get_form_kwargs()`, `get_initial()`, `get_prefix()`,
  `form_valid()`, `form_invalid()`, `get_context_data()` — works as it does
  anywhere.

**`consumes_what_it_checks`** — whether validating this step *performs* the
check it describes: proving a one-time code, authorising a card, claiming a
reference. `False` by default, which is right for the overwhelming majority
of steps, whose `clean()` is a pure function of what was submitted. Declared
rather than derived, because a `clean()` that reaches out is
indistinguishable from one that does not until it has already reached.

It is the dry-run half of [`run.proof()`](proofs.md), which is the durable
half, and a step that needs one almost certainly wants both.
[`RunDriver.check()`](driver.md) reads it and reports such a step as
`unchecked` rather than spending what it was asked about. The HTTP path is
unaffected: a real submission performs the check, as it must.

**`get_answer_errors(form)`** — what this step refused, by field name, in
`ErrorDict.get_json_data()` shape, and empty when the step is satisfied.
Callers read the *emptiness* rather than testing a Django attribute, which
is the point of asking the view: `BaseForm.errors` answers both questions at
once because an empty `ErrorDict` is falsy, and a form object that is not a
`BaseForm` need not behave that way. Override it beside such an object; the
[`RuntimeStep.errors`](run.md) every reader goes through asks here.

**`get_answer(form)`** — what the step was answered with. A mapping of field
name to cleaned value for a form, and whatever shape suits an object that is
not one. Everything reading a run's answers goes through
[`RuntimeStep.answer`](run.md), so a step's answer has one shape rather than
a shape per reader.

**`get_answer_fields(form)`** — the bound fields this step's answer reads
as, in display order, which is what a summary page lists. A `BaseForm`
yields its own. Override beside a form object that is not one, so the page
shows the answers rather than iterating something that is not a bound field.

**`get_answer_schema(form)`** — the step as JSON Schema, which is what an
agent is told it asks. Override it beside a form object
`form_json_schema()` cannot read: that walks `form.fields`, which only a
`BaseForm` has.

**`get_submission(answer)`** — `answer` as the POST that would have produced
it, and the only one of the five that goes the other way: the four above
describe what a step holds, and this is how something gets *into* it. A
form's answer is already the shape a browser posts, so the default puts the
step's `get_prefix()` around it and stops. Override it beside a form object
whose answer is not a submission; [`RunDriver.submit()`](driver.md) asks here,
which is what lets a caller read a step, change one field and send it back.

A step declared with a bare Django `FormView` rather than a `StepFormView`
carries none of these and gets the `BaseForm` readings, so nothing has to
change to keep working.

**`summary_rows`** — how this step's answers read on a
[check-your-answers page](summary.md): a sequence of `Answer` / `Hide` /
`Question` specs about *this* step's fields, so there is no step name to key
them by. Default `()`.

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

An address is an address wherever it is asked, so the step is where that
belongs; a review page then names no steps at all. Not to be confused with
`SummaryMixin.summary_overrides`, which is a *page* saying something
different about a step it names — a review page is itself a step view, so
the two cannot share a name.

A step declared as a bare `forms.Form` has no view to put this on and says
it at the declaration instead —
`.step(AddressForm, name="address", summary_rows=[...])`. Saying it in both
places is refused by [`.step()`](wizard.md#wizardstepform_class_or_form_view_class--context).

A step view's `summary_rows` is checked when its class body executes: a
field claimed by two specs, two specs naming no fields, or a `Question`
wrapping something that is not one row's worth of answer, each raise
`ImproperlyConfigured` at import rather than when someone opens the summary
page. All are decidable from the list alone; the refusal that is not — a
spec naming a field the step has not got — needs the wizard, so it stays
with the [summary page](summary.md#spec-validation).

**`get_summary_row_specs()`** — those specs, for a summary page to start
from. The default returns `summary_rows`. Override to decide per request;
the summary page has the last word either way.

The view rather than the form, deliberately: a `forms.Form` is a Django
object shared with everything else that asks it, so a Gandalf attribute on
it is this library squatting in a namespace it does not own, and a form
knowing about a check-your-answers page is a form knowing about a page it
never renders. A step declared as a bare `forms.Form` gains a step view to
say it on.

### `FormSetStepView`

A step whose `get_form()` returns a formset rather than a form.

Serving one needs nothing special and never did — `.step()` takes a
`FormView`, and `FormView` builds a formset from `data`, `files`, `initial`
and `prefix` exactly as it builds a form, so the browser path works with a
plain `StepFormView`. `FormSetStepView` is what makes the step readable by
everything that is *not* a browser.

```python
from django import forms

from gandalf.form_views import FormSetStepView


OpeningHoursFormSet = forms.formset_factory(OpeningHoursForm, extra=1)


class OpeningHoursStepView(FormSetStepView):
    form_class = OpeningHoursFormSet
    template_name = "hours/step.html"
```

**`get_answer(form)`** — each row's own cleaned data, in order. Read off the
rows rather than off the formset, which is the same list when everything
validated (`BaseFormSet.cleaned_data` *is* each row's) and the only reading
that survives when something did not: a formset refuses `cleaned_data`
outright unless the whole thing is valid, and a run parked on a rejected
submission is exactly the state anything reading a run is most likely to
meet.

**`get_answer_errors(form)`** — a row's errors keyed by the row's index and
the field name, `"0-email"`, because `"email"` names nothing when several
people are being asked at once. Errors belonging to the formset itself
rather than to any row — `min_num`, `max_num`, a `clean()` on the formset —
keep Django's own `__all__`.

**`get_answer_fields(form)`** — every row's fields, row by row, in the order
they were entered. A formset declares no fields at step level — they belong
to each of the n rows it repeats — so iterating it yields *forms*, and a
page listing those would be listing the wrong objects.

Flattening the rows is plain rather than pretty, and deliberately so. What
three organisers should read like on a check-your-answers page is the
page's decision, made with
[`SummaryMixin.build_summary_rows()`](summary.md). What a default must not
do is show *nothing*: then the answers cannot be checked, which is what the
page is for, and nobody can see that they are missing.

**`get_answer_schema(form)`** — an array of rows rather than an object of
fields. The row schema comes from the formset's `empty_form`, so it
describes what a row *asks* rather than what any row was answered with.
`minItems` and `maxItems` are stated only where the formset enforces them:
`min_num` and `max_num` say what the page draws, and `validate_min` /
`validate_max` say what it will accept. Advertising an unenforced bound
would tell an agent a rule that is not one.

**`get_submission(answer)`** — rows as the management form and the n
prefixed rows a browser sends. This is the half that makes a formset step
*writable* by something that is not a browser: `[{"day": "Monday"}, ...]`
says nothing about `TOTAL_FORMS`, so until a step could render its own
submission, a caller reading a formset step back could not submit what it
had just been handed. The counts come from the unbound formset, so they are
the ones this step would have rendered.

A mapping is passed through unchanged — that is what a browser posted and
what the HTTP path stores, so it is a submission already. Rows are the
addition rather than the replacement.

**Why it is needed at all.** A valid formset's `errors` is `[{}]` — a list
holding one empty dict per row — which is **truthy**. Code written as `if
form.errors:` therefore reads a perfectly valid formset as invalid, and
type-checks while doing it. That is not something a caller can guard
against without knowing what kind of object it holds, which is exactly what
the step view knows and nothing downstream does.

**Choosing between a formset step and the other ways to say "many"** —
[Chapter 13](../learn/13-add-another.md#three-ways-to-say-many).

### `form_view_factory(form_class, *, template_name)`

Generate the `StepFormView` subclass behind a step declared with a bare
`Form`.

**Parameters**

- `form_class` — a `forms.Form` subclass.
- `template_name` — keyword-only; the template every generated view renders
  with.

**Returns** a new `StepFormView` subclass with `form_class` and
`template_name` set, named `<FormName>View` and given the form's
`__module__`, so it reads naturally in a traceback.

**Caveats**

- Called by `WizardViewSet.configure_wizard()` for each step whose
  declaration is a `Form`, with the viewset's own `template_name` — that is
  the whole route by which a viewset's template reaches a step, and why it
  never reaches a view you wrote yourself.
- Replaceable per viewset: `form_view_factory` accepts any callable with
  the same signature returning a view class. See
  [Configuration](configuration.md).

### `WizardRequest`

`gandalf.types.WizardRequest` — an `HttpRequest` subclass declaring one
attribute, `wizard: Run`. Never instantiated: it names what a
dispatch adds to the request, so a view can annotate what it is handed.
`StepFormView` already declares its `request` this way.

It is not what a branch predicate, a `.switch()` selector or an `.expand()`
builder receives — those are walk-time code and are handed a
`WizardContext`, whose `run` is the same `Run`.

### What `.step()` accepts

`Wizard.step(form_class_or_form_view_class, /, **context)` takes one
positional argument, of two kinds:

| Declaration | What Gandalf does |
| --- | --- |
| a `forms.Form` subclass | `form_view_factory(form, template_name=...)` generates the view when the viewset configures the wizard; the viewset's `template_name` is required, and its absence raises `ImproperlyConfigured` ("A step declared from … needs template_name to generate its view."). |
| anything else — a `FormView` subclass | used as the step's view directly, with whatever `template_name` it declares. |

The test is `issubclass(declaration, forms.Form)`, so a `ModelForm` — which
subclasses `BaseForm`, not `Form` — is *not* recognised as a form. Wrap it
in a `StepFormView` subclass rather than passing it bare.

Keyword arguments are the step's context: `name=` is the key the default
router reads, `label=` is what [`SummaryMixin`](summary.md) reads, and any
other key is matched by `find_step()` / `filter_steps()`.

### How Gandalf reads a step's response

A step view is dispatched as an ordinary Django view, on a request shaped
for it (`StepDispatcher.build_request`): a shallow copy of the browser's
request — or one fabricated for a run nobody is browsing — with `method`,
`POST` and `FILES` set to the submission being placed or replayed, and
`request.run` set to the run.

The wizard then reads **only the status code**
(`StepDispatcher.response_satisfies_step`):

| Status | Meaning |
| --- | --- |
| 300–399 | the answer stands; the step is satisfied and the walk carries on |
| anything else | the answer does not hold; on a live submission the response is what the user sees (the form re-rendered with its errors), on a replay the walk parks here |

Which is why `form_valid()` returning Django's default redirect is all a
step needs, and why a `form_valid()` that returns a 200 — rendering a
"thanks" page, say — never satisfies its step. An escape raised during the
dispatch also satisfies the step; see [Escapes](escapes.md).

The dispatcher is replaceable per viewset (`step_dispatcher_class`); see
[Configuration](configuration.md).

### What a step view may read

`self.request.run` is the run's [`Run`](run.md), from
anywhere in the view — `get_initial()`, `get_form_kwargs()`,
`get_context_data()`, `form_valid()`.

**A step view sees the validated prefix before it** — the answers the walk
has already proved on this request, never the step's own answer and nothing
after it. This is the same contract a branch predicate gets, and it holds
whether the step is being rendered or replayed behind the cursor: the
dispatch runs inside the walk's `walking()` handoff, so reading
`request.run.path` yields the prefix rather than starting a nested walk.

- `request.run.path` — the resolved route so far, as a `Path`.
- `path.find_step(**context)` — the single prior step matching `context`, or
  **`None`** for a step the run cannot see: not yet reached, on an arm not
  taken, or downstream of this one. Raises `MultipleStepsReturned` on
  ambiguity. Guard the lookup unless the step you want is unconditionally
  upstream.
- `path.filter_steps(**context)` — every matching prior step, in walk order.
- `step.form.cleaned_data` — a prior step's validated answer. `form` is
  built once per step per `path` access; hold the steps you iterate rather
  than re-reading `wizard.path` per field.
- `request.run.metadata` — the run's metadata bag. A write from a step
  view runs on every walk, so it must be idempotent; see
  [Run metadata](run-metadata.md).

### Replay

Stored answers are re-proved on every request: each answered step is
re-dispatched with its stored submission, on every GET and POST that
follows it, for as long as the run lives. A step view's code therefore runs
once per later request, not once per answer. Keep `get_initial()`,
`get_form_kwargs()`, `clean()` and `form_valid()` cheap, deterministic for
the same input, and free of side effects that must happen once — those
belong in `WizardViewSet.run_started()` or `done()`. Costs are set out in
[Walk costs](walk-costs.md).

`RuntimeStep.form` — what a summary page or `done()` reads — reconstructs
the form through the view's composition API only (`setup()`, `get_form()`,
`is_valid()`); it does not run `post()`, `dispatch()` or `form_valid()`. A
`form_valid()` override affects whether a submission is accepted, never what
`cleaned_data` later reads back.

### Template context

A step template receives Django's `FormView` context plus whatever
`get_context_data()` adds:

| Variable | What it is |
| --- | --- |
| `form` | the step's form — unbound on a first visit, bound to the failing submission on a validation error, pre-filled from the stored answer via `initial` when a completed step is revisited |
| `view` | the view instance |
| `request.run.back_url` | the previous active-route step's URL; `None` at the first step, or when the predecessor is inside a preserved branch region |
| `request.run.run_url` | the bare run URL — redirects to the current step, so it is a "return to where I was" link |
| `request.run.path` | the answered steps on the route (a walk-time read; see above) |

`request` is in the context only with
`django.template.context_processors.request` enabled, as in Django's
default `TEMPLATES` setting.

---

## Usage

### A step that pre-fills from an earlier answer

```python
from gandalf.form_views import StepFormView


class WebsiteStepView(StepFormView):
    form_class = WebsiteForm
    template_name = "grants/website.html"

    def get_initial(self):
        initial = super().get_initial()   # keeps the stored answer on revisit
        contact = self.request.run.path.find_step(name="contact")
        if contact is not None and "website" not in initial:
            domain = contact.form.cleaned_data["email"].partition("@")[2]
            initial["website"] = f"https://{domain}"
        return initial


application = (
    Wizard()
    .step(ContactForm, name="contact", label="Contact")
    .step(WebsiteStepView, name="website", label="Website")
)
```

`super().get_initial()` matters: when a completed step is rendered for
editing, Gandalf hands the stored submission to the view as `initial`, and
an override that builds a fresh dict throws it away.

### Passing the request into the form

```python
from gandalf.form_views import StepFormView


class TrusteeStepView(StepFormView):
    form_class = TrusteeForm
    template_name = "grants/trustee.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organisation"] = self.request.user.organisation
        return kwargs
```

`get_form_kwargs()` is honoured both on dispatch and when the answer is
read back through `RuntimeStep.form`, so the form is constructed the same
way in both places.

### Deciding in `form_valid()`

```python
from gandalf.escapes import Park
from gandalf.form_views import StepFormView


class BudgetStepView(StepFormView):
    form_class = BudgetLineForm
    template_name = "grants/budget.html"

    def form_valid(self, form):
        if form.cleaned_data["amount"] > self.request.run.metadata.get("cap", 0):
            raise Park("grant-cap-exceeded")
        return super().form_valid(form)
```

Return `super().form_valid(form)` — the 302 to `self.request.path` is what
tells Gandalf the answer stands. Raise an [escape](escapes.md) to leave the
wizard instead.

### Mounting the same view standalone

```python
from django.urls import path, reverse_lazy

from .views import TrusteeStepView


class TrusteeEditView(TrusteeStepView):
    success_url = reverse_lazy("organisation-detail")


urlpatterns = [path("trustee/edit/", TrusteeEditView.as_view())]
```

Outside the wizard `self.request` has no `run` attribute; a view that
reads it must be given a real success URL and must not reach for the run.

---

## Troubleshooting

### `ImproperlyConfigured: TemplateResponseMixin requires either a definition of 'template_name' …`

The step brings its own view, and a step view does not inherit
`WizardViewSet.template_name` — that default reaches only the views Gandalf
generates from bare `Form`s. Set `template_name` on the view class.

### My step accepts the answer but the wizard shows it again with no errors

`form_valid()` returned a non-3xx response. Gandalf reads only the status
code; a 200 says "this answer does not hold". Return
`super().form_valid(form)` (or any redirect) from `form_valid()`.

### `find_step()` returns `None` inside my step view

The step you asked for is not in the validated prefix: it is after this
step, on an arm the run did not take, or not reached yet. A step view only
ever sees the answers before it. Guard the lookup, or move the read to a
step that is unconditionally downstream.

### `get_initial()` runs on every request, not just when my step is shown

Stored answers replay on every walk, and the replay dispatches the step's
view, so the view's hooks run each time. Keep them cheap and idempotent;
anything that must happen once belongs in `run_started()` or `done()`. See
[Run metadata](run-metadata.md) and [Walk costs](walk-costs.md).

### Passing a `ModelForm` to `.step()` fails with an `as_view()` error

`.step()` recognises a form by `issubclass(declaration, forms.Form)`, and
`ModelForm` is not a `forms.Form`. Declare a `StepFormView` subclass with
`form_class = YourModelForm` and pass that.

### My edit of a completed step renders an empty form

`get_initial()` was overridden without calling `super()`. Gandalf passes the
stored submission as the view's `initial`; `super().get_initial()` is what
returns it.

---

**Learn:** [Chapter 6 — Step views](../learn/06-step-views.md) · **Related:** [Escapes](escapes.md), [`Run`](run.md), [Summary](summary.md), [Walk costs](walk-costs.md), [Configuration](configuration.md)
