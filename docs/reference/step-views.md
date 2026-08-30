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
  `wizard` — so `self.request.wizard` type-checks with no cast (Gandalf ships
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
  request with no `wizard` attribute; override `get_success_url()` there to
  go somewhere real.
- Nothing else changes. Django's `FormView` composition API — `form_class`,
  `get_form_class()`, `get_form_kwargs()`, `get_initial()`, `get_prefix()`,
  `form_valid()`, `form_invalid()`, `get_context_data()` — works as it does
  anywhere.

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

- Called by `Wizard.configure()` for each step whose declaration is a
  `Form`. `template_name` is the one `configure(template_name=...)` received,
  which `WizardViewSet` supplies from its own `template_name` attribute —
  that is the whole route by which a viewset's template reaches a step, and
  why it never reaches a view you wrote yourself.
- Replaceable per wizard: `Wizard.configure(form_view_factory=...)` accepts
  any callable with the same signature returning a view class. See
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
| a `forms.Form` subclass | `form_view_factory(form, template_name=...)` generates the view at `configure()` time; the viewset's `template_name` is required, and its absence raises `ImproperlyConfigured` ("Wizard.configure() must receive template_name when generating FormView steps from Form classes."). |
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
`request.wizard` set to the run.

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

The dispatcher is replaceable per wizard
(`configure(step_dispatcher_class=...)`); see
[Configuration](configuration.md).

### What a step view may read

`self.request.wizard` is the run's [`Run`](run.md), from
anywhere in the view — `get_initial()`, `get_form_kwargs()`,
`get_context_data()`, `form_valid()`.

**A step view sees the validated prefix before it** — the answers the walk
has already proved on this request, never the step's own answer and nothing
after it. This is the same contract a branch predicate gets, and it holds
whether the step is being rendered or replayed behind the cursor: the
dispatch runs inside the walk's `walking()` handoff, so reading
`request.wizard.path` yields the prefix rather than starting a nested walk.

- `request.wizard.path` — the resolved route so far, as a `Path`.
- `path.find_step(**context)` — the single prior step matching `context`, or
  **`None`** for a step the run cannot see: not yet reached, on an arm not
  taken, or downstream of this one. Raises `MultipleStepsReturned` on
  ambiguity. Guard the lookup unless the step you want is unconditionally
  upstream.
- `path.filter_steps(**context)` — every matching prior step, in walk order.
- `step.form.cleaned_data` — a prior step's validated answer. `form` is
  built once per step per `path` access; hold the steps you iterate rather
  than re-reading `wizard.path` per field.
- `request.wizard.metadata` — the run's metadata bag. A write from a step
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
| `request.wizard.back_url` | the previous active-route step's URL; `None` at the first step, or when the predecessor is inside a preserved branch region |
| `request.wizard.run_url` | the bare run URL — redirects to the current step, so it is a "return to where I was" link |
| `request.wizard.path` | the answered steps on the route (a walk-time read; see above) |

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
        contact = self.request.wizard.path.find_step(name="contact")
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
        if form.cleaned_data["amount"] > self.request.wizard.metadata.get("cap", 0):
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

Outside the wizard `self.request` has no `wizard` attribute; a view that
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
