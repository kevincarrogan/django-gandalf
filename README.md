# django-gandalf

`django-gandalf` lets you declare **multi-step, tree-shaped Django form flows**
as readable, composable code.

You build a flow with a small, immutable builder — `.step()` to add a form,
`.branch()` to fork on an answer, `.expand()` to grow steps from an answer — and
mount it as an ordinary Django view. Gandalf handles the per-step URLs, the
session state, back-navigation, editing, file uploads, and running your
completion logic exactly once.

It is built for the point where a journey stops being a straight line and starts
branching: business vs individual, domestic vs international, nested
compliance sub-flows, optional setup paths, and path fragments reused across
journeys. Instead of scattered step conditions and navigation overrides, you
describe the flow as one explicit tree.

```python
from gandalf.wizard import Wizard, condition

onboarding = (
    Wizard()
    .step(AccountTypeForm, name="account_type")
    .branch(
        condition(is_business_account, Wizard().step(BusinessDetailsForm, name="business")),
        default=Wizard().step(PersonalDetailsForm, name="personal"),
    )
    .step(ReviewForm, name="review")
)
```

The only dependency is Django. Coming from `django-formtools`? See
[Coming from django-formtools](#coming-from-django-formtools) at the end for a
declaration-by-declaration mapping.

---

## Installation & setup

```bash
pip install django-gandalf   # or: uv add django-gandalf
```

Gandalf ships no models or migrations, but it does rely on a few pieces of
standard Django plumbing:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django.contrib.sessions",   # wizard state lives in the session
    "gandalf",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",  # required
    "django.middleware.csrf.CsrfViewMiddleware",
    # ...
]

TEMPLATES = [
    {
        # ...
        "OPTIONS": {
            "context_processors": [
                # required so `request.wizard` is reachable in step templates
                "django.template.context_processors.request",
            ],
        },
    }
]
```

Requires Python 3.10+ and Django 4.2+.

### Try the examples locally

Every worked example in this README is a real, runnable wizard bundled with the
repository. Boot the demo app with:

```bash
just serve
```

That starts Django at **http://127.0.0.1:8000/**, whose index page links to the
bundled example wizards. Each section below ends with a **▶ Try it live** link
to that example's start URL, e.g. http://127.0.0.1:8000/readme/signup/. These
are local URLs — they only resolve while `just serve` is running.

The code for these examples lives in
[`tests/testapp/readme_examples.py`](tests/testapp/readme_examples.py), and
[`tests/functional/test_readme_examples.py`](tests/functional/test_readme_examples.py)
drives each one through the Django test client — so the snippets below are
checked in CI, not just prose.

---

## Quickstart: a linear wizard

The shortest end-to-end flow is a linear wizard that collects a couple of forms
and does something with the combined result when it finishes.

```python
from django import forms
from django.http import HttpResponse
from django.urls import include, path

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard


class NameForm(forms.Form):
    name = forms.CharField()


class EmailForm(forms.Form):
    email = forms.EmailField()


class SignupWizardViewSet(WizardViewSet):
    url_name = "signup"
    template_name = "signup/step.html"
    wizard = (
        Wizard()
        .step(NameForm, name="name")
        .step(EmailForm, name="email")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        create_account(**payload)          # runs exactly once
        return HttpResponse("Thanks!")
```

Mount it with a single `include`:

```python
urlpatterns = [
    path("signup/", include(SignupWizardViewSet.urls())),
]
```

The step template is a plain Django form — no management form, no wizard-specific
markup, because Gandalf keeps position in the session rather than in the POST
body:

```django
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Continue</button>
</form>
```

That is the whole thing: two forms, a viewset, one URL include.

### Linking to the wizard

`urls()` derives three URL names from `url_name`, so getting a user into the
wizard is ordinary Django reversing:

| URL name | Pattern | What it is |
| --- | --- | --- |
| `signup` | `signup/` | **the start URL** — begins a fresh run |
| `signup-run` | `signup/<run_id>/` | a run — redirects to wherever it has got to |
| `signup-step` | `signup/<run_id>/email/` | one step of a run |

The start URL is the one you publish, and its name is `url_name` verbatim:

```python
from django.urls import reverse

reverse("signup")            # "/signup/"
```

```django
<a href="{% url 'signup' %}">Sign up</a>
```

The other two are the wizard's own business — it redirects between them as the
user walks — though being reversible is what makes a run resumable from a link.
See [URLs and routing](#urls-and-routing) for mount prefixes that capture
kwargs, namespaces, and the hooks that build these URLs from inside the viewset.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/signup/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L37-L54)

---

## How it works

A few ideas carry the rest of the library.

**The builder is immutable.** Every `.step()` / `.branch()` / `.expand()`
returns a *new* `Wizard`, like Django `QuerySet` chaining — nothing mutates in
place. That makes reusable bases safe:

```python
base = Wizard().step(AccountForm, name="account")

staff_wizard = base.step(InternalReviewForm, name="internal_review")
customer_wizard = base.step(ProfileForm, name="profile")
# `base` still contains only AccountForm.
```

**Every step is named, and every step gets its own URL.** `name="email"` is
shorthand for `context={"name": "email"}`. From `url_name`, `urls()`
publishes three patterns — `signup` (the start URL), `signup-run`
(`signup/<run_id>/`), and `signup-step` (`signup/<run_id>/email/`); see
[URLs and routing](#urls-and-routing). A step URL is a *claim*: it either
renders that step or redirects to wherever the run actually is, so a stale link
can never land an answer on the wrong step.

**A run re-proves itself on every request.** Gandalf stores raw submissions, not
"how far you got". On each request it replays the stored answers through their
forms up to the first missing or no-longer-valid one — that is what makes
position, branch selection, editing, and completion all fall out of a single
walk, and what makes stale state impossible. (The cost of that replay is
covered in [What replaying costs](#what-replaying-costs).)

**`done(self, bound_wizard)` receives the run, not a list of forms**, so it can
read the answers however it needs:

- `bound_wizard.path` — the resolved route: the answered steps in order,
  iterable, each a `RuntimeStep` exposing `.form.cleaned_data`, `.data` (raw
  submission), `.files`, and — for linking back to a step — `.name` and
  `.url`.
- `MergeCleanedData().reduce(bound_wizard.path)` — folds every step's
  `cleaned_data` into one dict (last-write-wins). Subclass it for a different
  merge policy.
- `bound_wizard.path.find_step(name=...)` / `path.filter_steps(...)` — look a
  step up by name or any context key. These live on `path`, so they only ever
  see steps actually on the resolved route — prior answers, never the current
  (unanswered) step or a step not yet reached.
- `bound_wizard.runtime_tree` — the head of the walked tree (`.next` to the
  following step).
- `bound_wizard.get_state()` / `get_run_data()` — the raw stored JSON.

**Plain `Form` or full `FormView`.** Pass a plain `Form` and Gandalf generates
the step's view for you, rendered with the viewset's `template_name`. Pass your
own view — a `StepFormView` subclass — when a step needs `get_initial()`,
`get_form_kwargs()`, a per-step template, or other view-level behavior; it keeps
its own configuration and can be reused as a standalone view outside the wizard.
Inside the wizard the step still sees `self.request.wizard`, so it can inspect
run state when useful. See [Step views](#step-views-bringing-your-own-formview)
for what such a view must provide and what it sees when it reads run state.

---

## Branching

`.branch()` forks the flow on a prior answer. Each arm is a sub-`Wizard` (or
`None` for "nothing extra here"); a `condition(predicate, arm)` pairs a
`predicate(request)` with the arm it selects. Selection is **first-match-wins**,
falling back to `default`.

```python
from gandalf.wizard import Wizard, condition


def is_business_account(request):
    account_step = request.wizard.path.find_step(name="account_type")
    return account_step.form.cleaned_data["account_type"] == "business"


class BranchingWizardViewSet(WizardViewSet):
    url_name = "onboarding"
    template_name = "onboarding/step.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .step(ReviewForm, name="review")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        ...
```

A predicate always runs **behind a fully-validated prefix** — every step before
the branch has already validated on this same walk — so it can dereference
`path.find_step(...).form.cleaned_data` unconditionally without guarding for missing
answers.

Because arms are sub-`Wizard`s, they compose: define a subflow once and drop it
into several branches. And a de-selected arm's answers are not thrown away — see
[Dormant memory](#dormant-memory-flipping-a-branch-and-back) below.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/branching/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L60-L85)

---

## Dynamic wizards: `get_wizard()`

When the shape of the flow depends on **request context** — tenant, plan,
permissions, locale, feature flags — override `get_wizard(self, bound_wizard)`
instead of setting a class-level `wizard`. It is called per request, so the
same view can build a different flow for each caller. Here the plan is captured
in the URL, and the team plan gets an extra company step:

```python
class OnboardingWizardViewSet(WizardViewSet):
    url_name = "onboarding"
    template_name = "onboarding/step.html"

    def get_wizard(self, bound_wizard):
        wizard = Wizard().step(NameForm, name="name")
        if self.kwargs["plan"] == "team":
            wizard = wizard.step(CompanyForm, name="company")
        return wizard.step(EmailForm, name="email")
```

```python
urlpatterns = [
    path("onboarding/<slug:plan>/", include(OnboardingWizardViewSet.urls())),
]
```

The mount prefix can capture kwargs of its own; the default URL hooks forward
them into every redirect, so `self.kwargs["plan"]` is available on each request
of the run. Reach for `get_wizard()` when the shape depends on the *request*;
when it depends on a prior *answer* the user just gave, reach for
[`.expand()`](#expand-grow-the-wizard-from-a-prior-answer) instead — it grows
the tree in a single walk without re-reading stored state.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/onboarding/solo/ or
> [/team/](http://127.0.0.1:8000/readme/onboarding/team/) &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L91-L106)

---

## `.expand()`: grow the wizard from a prior answer

A branch chooses between subflows you declared up front. Sometimes the *shape*
of the flow is not known until a prior **answer** supplies it — N item steps for
a count the user just typed. `.expand()` grows the tree during the walk from a
builder you provide:

```python
def build_item_steps(request):
    count = int(request.wizard.path.find_step(name="count").form.cleaned_data["count"])
    steps = Wizard()
    for index in range(count):
        steps = steps.step(ItemForm, name=f"item-{index}")
    return steps


class ExpandWizardViewSet(WizardViewSet):
    url_name = "collect-items"
    template_name = "collect/step.html"
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(build_item_steps)
        .step(ReviewForm, name="review")
    )
```

The builder runs mid-walk, behind the validated count, and its steps are spliced
in where `.expand()` sits. That is the difference from a state-reading
`get_wizard()`: answering the count parks the user on the first grown step in a
*single* request, where `get_wizard()` has to walk twice (once to notice its own
submission changed the shape).

Good to know: the builder reaches back to prior answers **by name**, so renaming
an upstream step can break it; grown answers store positionally, so raising a
count keeps the answers already given and lowering it drops the trailing ones;
and every grown step must be routable (carry a `name`).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/expand/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L112-L137)

---

## Back-navigation: editing earlier steps

Because every step has its own URL, an "edit" affordance is just a link. GET a
completed step's URL to render it pre-filled; POST the changed answer back to it
to place it there. Editing is not a separate operation — putting an answer at a
step works the same whether or not it already had one.

A review template wires per-step edit links from the runtime path. Every step
on the route carries its own `name` and `url`, so the link is the step:

```django
<h1>Review your details</h1>
<ul>
  {% for step in request.wizard.path %}
    <li><a href="{{ step.url }}">Edit {{ step.name }}</a></li>
  {% endfor %}
</ul>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Confirm</button>
</form>
```

To show the answers themselves alongside those links, reach for
[`SummaryMixin`](#summary-pages-check-your-answers) rather than growing this
loop.

The promise is that changing an answer costs the user only as much of the wizard
as the change actually invalidates — usually nothing. A trivial edit lands
straight back on the summary; an edit that flips a branch parks only at the
steps that now need attention, then fast-forwards through every still-valid
answer. Nothing downstream is lost to a typo, because an invalid edit is kept
and re-rendered with its errors while the sealed tail is carried verbatim.

For an explicit in-page back link, any step template can reach
`request.wizard.back_url` (the previous step's URL, branch-aware; `None` on the
first step) and `request.wizard.run_url` (a "return to where I was" link):

```django
{% if request.wizard.back_url %}
  <a href="{{ request.wizard.back_url }}">Back</a>
{% endif %}
```

> ▶ **Try it live:** http://127.0.0.1:8000/readme/editing/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L216-L238)

---

## Summary pages: check your answers

A "check your answers" step asks the same three questions of every answer —
what is it called, what does it say, and where do I go to change it — so
`SummaryMixin` answers them once. Mix it into the step's `FormView` and the
template gets a `summary` list, one row per answered step:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "checkout/review.html"


class SummaryWizardViewSet(WizardViewSet):
    url_name = "checkout"
    template_name = "checkout/step.html"
    wizard = (
        Wizard()
        .step(NameForm, name="name", context={"label": "Your name"})
        .step(DeliveryForm, name="delivery", context={"label": "Delivery"})
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
        <span>{{ field.label }}: {{ field.value }}</span>
      {% endfor %}
      <a href="{{ row.url }}">Change {{ row.label }}</a>
    </dd>
  {% endfor %}
</dl>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Confirm</button>
</form>
```

The rows come from `request.wizard.path`, so they are the answers on the run's
resolved route, in walk order, with the selected branch arm inlined — never the
step doing the summarising, and never an answer left behind in a dormant arm.
Each row carries `label`, `fields`, `url`, `name`, the `step` it came from, and
its `form`; each field carries `label`, `value`, `name`, and the `bound_field`
the value came from.

**Values are display text, not stored data.** A choice shows its label, a
boolean shows Yes/No, dates and times take the active locale's format, an
upload shows its filename, a multi-valued answer is comma-joined, and an
unanswered optional field is blank rather than "None". Anything else is its
`str()`.

**Every decision is a hook.** Override on the view, deferring to `super()` for
the cases you do not special-case:

| Hook | Decides |
| --- | --- |
| `get_summary_steps()` | which steps get a row (default: every answered step) |
| `get_summary_label(step)` | a row's heading — the step's `label` context, else its name made readable |
| `include_summary_field(step, bound_field)` | whether a field earns a line |
| `format_value(bound_field, value)` | how one answer reads |
| `summary_context_name` | the context variable's name (default `summary`) |

```python
class ReviewStepView(SummaryMixin, StepFormView):
    def format_value(self, bound_field, value):
        if bound_field.name == "born_on":
            return value.strftime("%d %B %Y")
        return super().format_value(bound_field, value)
```

**One form per row.** Reading a step's answers means reconstructing its form
(see [What replaying costs](#what-replaying-costs)), so a page that reached for
`step.form` per field would pay a validation per field. The mixin builds each
row from a single form, and `RuntimeStep.form` is itself built once per step
per request — so a five-field row costs one reconstruction, not five.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/summary/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L309-L339)

---

## Dormant memory: flipping a branch and back

Editing an answer that flips a branch does not discard the arm you leave. A
de-selected arm's answers are kept as **dormant memory**, re-validated and
restored if you flip back — so the user never re-types an answer they already
gave.

Take the branching wizard: pick a business account, fill in the company name,
then edit the account type to personal. The business arm is now inactive, but
its answer is not gone. Flip the account type back to business and the company
name is already there — the run fast-forwards past it to the summary instead of
asking again.

```python
class FlipFlopWizardViewSet(WizardViewSet):
    url_name = "flip-flop"
    template_name = "onboarding/editing.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(is_business_account, Wizard().step(CompanyForm, name="company")),
            default=Wizard().step(PersonalForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )
```

Dormant arms live in the session until the run completes, and arm identity is
positional (declaration order) — so a dynamic `get_wizard()` that reorders
branch arms between requests would misattribute the memory, the same
positional-alignment rule that applies to steps.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/flip-flop/ (choose business,
> fill the company name, then edit the account type to personal and back)
> &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L244-L268)

---

## File uploads

Steps may declare `forms.FileField`. Uploaded bytes cannot live in the session,
so Gandalf persists them through a companion `WizardFileStorage`; the session
carries only a small ref (storage key plus original name/content-type/size). The
step template just needs the usual `enctype`:

```django
<form method="post" enctype="multipart/form-data">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Continue</button>
</form>
```

```python
class FileUploadWizardViewSet(WizardViewSet):
    url_name = "profile"
    template_name = "profile/step.html"
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, name="photo")
        .step(NameForm, name="name")
    )

    def done(self, bound_wizard):
        photo_step = bound_wizard.path.find_step(name="photo")
        filename = photo_step.files["photo"]["name"]
        ...
```

On replay, Gandalf reopens each stored file and re-injects it into
`request.FILES` before re-validating the step, so validators that inspect the
upload see the same value they saw originally. Editing respects keep-vs-replace
per field. After `done()` returns, the run's files are cleaned up automatically.

The default storage writes under a `gandalf/<run_id>/` prefix of Django's
default storage; point it elsewhere (S3, a per-tenant location) by subclassing
`WizardFileStorage` and passing it to `.configure(file_storage_class=...)`.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/file-upload/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L143-L152)

---

## Step views: bringing your own `FormView`

Pass a plain `Form` and Gandalf generates the step's view. Bring your own when
the step needs view-level behavior — a per-step template, `get_initial()`,
`get_form_kwargs()`, a custom `form_valid()`.

Start from **`StepFormView`**. It is a plain Django `FormView` with the one
piece of wizard boilerplate already written: the success URL. Gandalf reads only
the *status code* of a step's response — a 3xx means "this answer stands, carry
on" — and then discards the response, so the URL is never followed, and every
step view would otherwise redirect to `self.request.path` to say nothing.
The views Gandalf generates are built on the same class.

You still supply **`template_name`** (or `get_template_names()`): a step with
its own view does *not* inherit the viewset's `template_name` — that default
only reaches the views Gandalf generates — and without one, rendering raises
`ImproperlyConfigured`.

```python
from gandalf.form_views import StepFormView


class BillingStepView(StepFormView):
    form_class = BillingForm
    template_name = "billing/step.html"

    def get_initial(self):
        initial = super().get_initial()
        account = self.request.wizard.path.find_step(name="account")
        initial["company"] = account.form.cleaned_data["email"].partition("@")[2]
        return initial


class FormViewStepWizardViewSet(WizardViewSet):
    url_name = "billing"
    template_name = "billing/step.html"
    wizard = (
        Wizard()
        .step(EmailForm, name="account")
        .step(BillingStepView, name="billing")
        .step(ReviewForm, name="confirm")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(f"Billing {payload['company']} ({payload['country']})")
```

Mixing the two styles is the normal case: `billing` brings its own view, while
`account` and `confirm` stay plain `Form`s and get theirs generated with the
viewset's `template_name`. Nothing else changes — the step is still named, still
gets its own URL, and still contributes its `cleaned_data` to `bound_wizard.path`.

Because the view keeps its own configuration, the same class can also be
mounted as an ordinary standalone view outside the wizard — one place for the
form's behavior across "create in wizard" and "edit later" screens. Give the
standalone subclass a real `get_success_url()`; only the in-wizard one wants the
no-op `StepFormView` supplies.

A plain `FormView` still works as a step, and `StepFormView` changes nothing
about how it is declared — but then the no-op success URL is yours to write,
and a valid POST raises `ImproperlyConfigured` without one.

### Reading run state from a step view

The step runs on a wizard-shaped request, so `self.request.wizard` is the same
`BoundWizard` the rest of the flow sees — `path` for the resolved route,
`path.find_step(name=...)` to address a prior answer, as `get_initial()` does
above. That works from anywhere in the view: `get_initial()`,
`get_form_kwargs()`, `get_context_data()`, `form_valid()`.

**What a step view sees is the prefix before it** — the answers the walk has
already validated on this request, never the step's own answer and nothing
after it. That is the same contract a branch predicate gets, and it holds
whether the step is being rendered or replayed behind the cursor. A step is
replayed on every later request, so its reads run again each time; keep them
cheap for the same reason you keep `clean()` cheap (see
[What replaying costs](#what-replaying-costs)).

`find_step()` returns `None` for a step the run cannot see, so guard the lookup
when the step you want is not unconditionally upstream of this one. The example
above does not guard, because `account` always precedes `billing`.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/form-view/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L158-L197)

---

## URLs and routing

`WizardViewSet.urls()` publishes every URL a wizard needs, all derived from
`url_name` — which is therefore required, and `urls()` raises
`ImproperlyConfigured` without it.

| URL name | Pattern | What a request there does |
| --- | --- | --- |
| `signup` | `signup/` | starts a fresh run, then redirects to its run URL |
| `signup-run` | `signup/<run_id>/` | redirects to wherever that run's cursor actually is |
| `signup-step` | `signup/<run_id>/<step>/` | renders that step, or redirects if the run is elsewhere |

Only the first is a destination you publish. The wizard redirects between the
other two itself as the user walks, and a step URL is a *claim* rather than an
instruction — the run's own position always wins.

### Linking in from elsewhere

There is no gandalf-specific helper for this, and none is needed — the names
above are ordinary Django URL names:

```python
from django.urls import reverse

reverse("signup")            # from another view, an email, a management command
```

```django
<a href="{% url 'signup' %}">Sign up</a>
```

`get_start_url()` is *not* the tool for this. It is an instance method that
reads `self.kwargs` off a live request, so it only exists inside a viewset
handling a request. From anywhere else, reverse the name.

### Mount prefixes that capture kwargs

A wizard mounted under a prefix with captured kwargs — like the
[dynamic onboarding example](#dynamic-wizards-get_wizard), mounted at
`onboarding/<slug:plan>/` — needs those kwargs to reverse:

```python
reverse("onboarding", kwargs={"plan": "team"})     # "/onboarding/team/"
```

Inside the wizard you never pass them by hand. `get_url_kwargs()` takes whatever
the request captured, drops the wizard's own `run_id` and `gandalf_step`, and
forwards the rest into every reverse — so a run started at `/onboarding/team/`
stays under `/onboarding/team/` for the whole walk. Override it when reversing
needs context the URL does not capture.

### Reversing from inside the viewset

Three hooks build the wizard's own URLs. Each forwards `get_url_kwargs()`, so an
override that keeps that call keeps mount-prefix support:

| Hook | Reverses | Called for |
| --- | --- | --- |
| `get_start_url()` | `signup` | a run that cannot be continued — unknown, obliterated, or already completed (see `run_unavailable()`) |
| `get_wizard_url(run_id)` | `signup-run` | the redirect after a fresh run is created, and when a walk has no step left to land on |
| `get_step_url(run_id, segment)` | `signup-step` | every step-to-step redirect |

### Namespaces

The names `urls()` publishes are global, and the three hooks reverse them
unprefixed. Mounting under a namespace therefore breaks the wizard's own
redirects — the first one raises `NoReverseMatch` — unless you override all
three:

```python
from django.urls import include, path

urlpatterns = [
    path(
        "signup/",
        include((SignupWizardViewSet.urls(), "signup"), namespace="checkout"),
    ),
]
```

```python
from django.urls import reverse

from gandalf.viewsets import WizardViewSet


class SignupWizardViewSet(WizardViewSet):
    url_name = "signup"
    # ...

    def get_start_url(self):
        return reverse("checkout:signup", kwargs=self.get_url_kwargs())

    def get_wizard_url(self, run_id):
        return reverse(
            "checkout:signup-run",
            kwargs={**self.get_url_kwargs(), "run_id": run_id},
        )

    def get_step_url(self, run_id, step_segment):
        return reverse(
            "checkout:signup-step",
            kwargs={
                **self.get_url_kwargs(),
                "run_id": run_id,
                "gandalf_step": step_segment,
            },
        )
```

If all you wanted was to avoid a name clash, prefixing `url_name` itself
(`url_name = "checkout-signup"`) is less work and needs no overrides.

### Custom step segments

The step segment comes from `StepNameRouter`, which reads each step's
`name` context and reverses it back into a slug. Routing is an add-on: it
activates only because the published pattern captures `<slug:gandalf_step>`.
Subclass the router to key off different context and pass it as
`step_router_class`:

```python
from gandalf.wizard import StepNameRouter, Wizard


class StepSlugRouter(StepNameRouter):
    context_key = "slug"


wizard = (
    Wizard()
    .step(EmailForm, context={"slug": "email-address"})
    .configure(
        template_name="signup/step.html",   # a pre-configured wizard is taken
        step_router_class=StepSlugRouter,   # as-is, so set this here too
    )
)
```

(`name="email"` is only shorthand for `context={"name": "email"}`, so a
router keyed on `slug` wants the context spelled out.)

Every step must be reversible and every segment unique. Both are checked when
the wizard is resolved, across the whole declared tree rather than just the
steps this walk happens to reach — a walk stops at the cursor and so could not
see a duplicate beyond it. A step with no routable name, or a segment naming two
steps, raises `ImproperlyConfigured` rather than quietly serving an unreachable
step.

For a scheme the router cannot express at all, skip `urls()`, write the patterns
yourself, and override the three hooks above.

---

## Escaping the wizard

Sometimes an answer means the user should not be in the wizard any more — an
email lookup finds an existing account, so the right destination is the login
page, not the next step. A step says so by raising an escape, an ordinary
exception in the spirit of `Http404`:

```python
from django.contrib.auth.models import User
from django.urls import reverse

from gandalf.escapes import Park


class EmailLookupForm(forms.Form):
    email = forms.EmailField()

    def clean(self):
        cleaned_data = super().clean()
        if User.objects.filter(email=cleaned_data.get("email")).exists():
            raise Park(reverse("login"))
        return cleaned_data
```

All three escapes take the same arguments as `django.shortcuts.redirect` (a URL,
a named route, or a model with `get_absolute_url()`); which one you raise decides
what the user comes back to:

| Exception | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded, with any files it uploaded | the same step, unanswered |
| `Advance` | stored, and satisfies the step | the next step |
| `Obliterate` | destroyed with the rest of the run | a fresh run |

Escapes can also be raised from a `FormView`'s `form_valid()` when the decision
needs the view. `Escape` is the base class, so `except Escape` catches all
three.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/escape/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L203-L210)
> &nbsp; (enter `existing@example.com` to trigger the park)

---

## Completion and storage

**`done()` runs exactly once.** A run finishes the first time it is walked and
every step is satisfied; `done()` is called, its files are cleaned up, and the
run is retired — its answers are dropped and a small completion marker takes
their place. After that, every request for it (bare run URL or any step URL, GET
or POST) is answered by `run_unavailable()` without reaching the wizard. So a
stale tab cannot finalize twice, and a refreshed completion page cannot re-charge
a card. Put side effects in `done()` and they happen once, full stop.

The marker is written *after* `done()` returns, so a `done()` that raises leaves
the run intact and resumable.

`run_unavailable(self, bound_wizard, reason)` answers everything that cannot be
run — `reason` is `"completed"` (finished) or `"unknown"` (never started,
obliterated, or a lost session). The default redirects to the start URL; override
it to say something more specific:

```python
class CheckoutWizardViewSet(WizardViewSet):
    def run_unavailable(self, bound_wizard, reason):
        if reason == "completed":
            return redirect("order-thanks")
        raise Http404("That checkout has expired.")
```

**Storage** is session-backed. Gandalf ships `SessionStorage`, which keeps plain
JSON in `request.session` (Django's session backend handles persistence). It is
the one touch point set on the viewset rather than via `.configure(...)`, because
it must exist *before* the wizard does — a dynamic `get_wizard()` reads stored
state to shape itself:

```python
class SignupWizardViewSet(WizardViewSet):
    storage_class = CustomSessionStorage
```

Retired runs are pruned to the most recent `SessionStorage.max_completed_runs`
(25 by default), so completed runs cannot grow a session without bound.

### Storage that outlives a session

A journey the user comes back to over days needs somewhere better than a
session. Gandalf ships no durable backend — that would mean models, migrations
and a retention policy, and the only dependency here is Django — so
`storage_class` is the seam, and it is small enough to swap. `BoundWizard`
calls exactly these nine things and nothing in the runtime, the walker or the
viewset reaches past them:

| Method | Contract |
| --- | --- |
| `__init__(request)` | The request is passed in, so a backend can scope by `request.user` or a tenant |
| `initialise_run()` | Create a run, return its id |
| `retrieve_run(run_id)` | Return the id, or raise `RunNotFound`. **This is the whole authorisation model** — scoping the queryset by owner is what stops one user resuming another's run |
| `get_run_data(run_id)` | `{"state": [...]}`, or `{"completed": True}` for a finished run |
| `get_state(run_id)` | The state list; `[]` for a completed run |
| `set_state(run_id, state)` | Store the list verbatim |
| `delete_run(run_id)` | Forget it entirely. Idempotent |
| `complete_run(run_id)` | Discard the state and mark it finished, leaving the run *addressable* so a revisit answers "done" rather than "no such run". Idempotent |
| `is_run_complete(run_id)` | Whether it has been tombstoned |

A [worked `ModelStorage`](tests/testapp/durable.py) lives in the test app,
driven end to end by
[`test_durable_storage.py`](tests/functional/test_durable_storage.py) — a whole
hub journey over the database, with the session holding nothing but the login.

**A durable hub needs both stores swapped**: `storage_class` on every section
viewset, *and* `section_store_class` on the hub and on each `SectionMixin`.
Swapping only one gives you durable answers nobody can find, or a durable index
into runs that have expired. A durable section store also closes a race the
session cannot: Django read-modify-writes the whole session, so two tabs
entering the same section can lose a registration outright, where a unique
constraint on `(owner, section_key)` settles it.

Note that `gandalf.testing`'s peek-and-seed helpers read the session stores
directly, so they do not apply to a custom backend — assert against your own
models instead.

---

## Stashing and resurrecting runs

Completion is terminal — `done()` fires once and the run's answers are gone.
Sometimes you want both: the wizard finishes (its side effects run), but the
answers stay editable — say, a profile built from several wizards where each
section completes on its own and any of them can be re-opened later.

That is a **stash**: inside `done()`, `bound_wizard.stash()` returns a small
JSON-safe payload of the run's answers. The payload is yours — put it in a
model field, the session, wherever your bigger flow keeps its pieces. To
re-open it, `MyWizardViewSet.resurrect(request, payload)` seeds a brand-new
run from the payload and returns the URL to send the user to; they land in
the ordinary wizard UI with every answer pre-filled, edit whatever they need,
and `done()` fires again for the new run when they finish.

```python
from django.http import HttpResponse
from django.shortcuts import redirect

from gandalf.storage import SessionStashStore, StashNotFound
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import InvalidStash, Wizard


class ContactSectionWizardViewSet(WizardViewSet):
    url_name = "contact-section"
    template_name = "profile/step.html"
    wizard = (
        Wizard()
        .step(NameForm, name="name")
        .step(EmailForm, name="email")
    )

    def done(self, bound_wizard):
        # Keep the finished answers so this section can be re-opened later.
        SessionStashStore(self.request).put(
            "contact", bound_wizard.stash(label="contact")
        )
        return HttpResponse("Contact details saved.")


def reopen_contact(request):
    stashes = SessionStashStore(request)
    try:
        payload = stashes.get("contact")
        url = ContactSectionWizardViewSet.resurrect(
            request, payload, expected_label="contact"
        )
    except (StashNotFound, InvalidStash):
        # Nothing stashed — start fresh at the wizard's start URL, which
        # `urls()` published under `url_name`.
        return redirect("contact-section")
    return redirect(url)
```

`SessionStashStore` is the helper for the common case — keyed payloads in the
session (`put` / `get` / `pop` / `delete` / `keys`), server-side so they cannot
be tampered with in transit. Any other home works just as well; if a payload
ever travels through the client, sign it (`django.core.signing`).

What resurrection promises:

- **A fresh, ordinary run.** Nothing about it is special — standard URLs,
  editing, escapes. Resurrecting the same payload twice yields two independent
  runs. The original run's tombstone is untouched, so the once-per-run `done()`
  guarantee holds: re-completion fires `done()` for the *new* run.
- **Every answer is re-proved.** Resurrection replays the walk, so a payload is
  trusted no further than a live session's own state — a mangled answer parks
  the run on that step with its errors rather than completing silently.
- **A step URL, never the bare run URL.** A stashed run's answers all validate,
  so `resurrect()` lands the user on a step (pass `step="..."` to choose which;
  default is the cursor, or the first step when complete). See
  [`BoundWizard.entry_url()`](#hub-and-spoke-parallel-sections), which is what
  `resurrect()` uses and what any other link into a run should use too.
- **Re-opening is edit-and-re-save.** Every answer already validates, so the
  *next* successful submission — including an edit to step one — walks straight
  to the end and fires `done()` again. A review step does **not** gate that; its
  own answer is stashed too, so it re-validates like any other. What a review
  step gives you is somewhere to *land*: pass `step="review"` (or, for a hub
  section, `reopen_step="review"`) and the user arrives at their answers with a
  change link each, instead of at step one. `SummaryMixin` drops the step doing
  the summarising from its own rows, so a review page revisited this way does
  not offer to change itself.
- **Files are not preserved.** Uploaded bytes are deleted at completion, so
  `stash()` keeps a file step's other answers but drops its uploads. On
  resurrection an *optional* file field sails through; a *required* one parks
  the run at that step for the user to re-upload.
- **Same-shaped wizard only.** Stored answers align with the wizard tree
  positionally, so a payload only resurrects correctly against a tree shaped
  like the one that stashed it. The `label` is the guard rail: stamp it at
  stash time, pass `expected_label` at resurrect time, and bump the label when
  a deploy reshapes the wizard — a mismatch raises `InvalidStash` before any
  run is created.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/stash/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L276-L302)

---

## Hub and spoke: parallel sections

Some journeys are not one wizard but several, and the user picks the order: a
profile with contact details, an address and employment history; an application
with a task list. Each section completes on its own, any of them can be
re-opened, and a page up front says how far each has got.

`gandalf.sections` is that page. Declare the sections, mix `SectionMixin` into
each section's viewset, and the hub renders a row per section carrying its
title, its status — **Not started**, **Incomplete** or **Complete** — and one
URL that does the right thing whichever state it is in.

```python
from gandalf.form_views import StepFormView
from gandalf.sections import HubView, Section, SectionMixin
from gandalf.summary import SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "profile/review.html"


class ContactSectionViewSet(SectionMixin, WizardViewSet):
    url_name = "profile-contact"
    template_name = "profile/step.html"
    section_key = "contact"
    hub_url_name = "profile-hub"
    wizard = (
        Wizard()
        .step(NameForm, name="name", context={"label": "Your name"})
        .step(EmailForm, name="email", context={"label": "Email"})
        .step(ReviewStepView, name="review")
    )

    def section_done(self, bound_wizard):
        save_contact(self.request.user, bound_wizard)
        return super().section_done(bound_wizard)  # back to the hub


class ProfileHubView(HubView):
    template_name = "profile/hub.html"
    url_name = "profile-hub"
    section_url_name = "profile-hub-section"
    sections = [
        Section(
            "contact",
            ContactSectionViewSet,
            title="Contact details",
            reopen_step="review",
        ),
        Section("address", AddressSectionViewSet, title="Address"),
    ]
```

A hub is mounted exactly like a wizard, and publishes two patterns from
`url_name` — the page, and the door into one section:

```python
from django.urls import include, path

urlpatterns = [
    path("profile/", include(ProfileHubView.urls())),
    path("profile/contact/", include(ContactSectionViewSet.urls())),
    path("profile/address/", include(AddressSectionViewSet.urls())),
]
```

```django
{% for row in sections %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
```

**Sections override `section_done()`, never `done()`.** `done()` belongs to the
mixin: it stashes the finished answers under `section_key`, which is the only
thing that can tell the hub the section is finished. A subclass that replaced
it would leave the section reading as not started forever.

### What each status means

| Status | Comes from |
| --- | --- |
| **Complete** | A stash under the section's key — the section ran to its own end and `done()` fired |
| **Incomplete** | A recorded run holding at least one submission |
| **Not started** | Everything else, including a section opened and left unanswered, and one whose run has expired |

A row is deliberately cheap: two storage reads and a `reverse()`, no walk, so
a hub of six sections costs six dict lookups rather than a form `clean()` per
answered step per row. Whether the stored answers still *validate* is not
asked — it would not change the row, since an answer that no longer validates
leaves the section in progress just as surely as one that does.

### Every link is a step URL, never a bare run URL

This is the one thing worth understanding. A run whose every stored answer
validates **completes on a GET** — the bare run URL redirects to the cursor,
and when there is no cursor left that is `done()`. So a hub row can never
point at `get_wizard_url()`: it would fire the section's side effects on a
click.

Rows therefore link to the hub's own door, which is the only place that can
afford to ask what exists. It resumes a live run, re-opens a stash, or starts
a fresh run, and every arm ends at `BoundWizard.entry_url()` — a step URL by
construction. Resuming is tried *before* re-opening, so a section already
being edited continues that edit rather than resurrecting a second run beside
it.

### Re-opening is edit-and-re-save

A re-opened section arrives with every answer already valid, so **the next
successful submission walks to the end and fires `done()` again**. That is the
intended semantics — the user changed something and it saved — and it is why
the mixin splits idempotent bookkeeping (`done()`) from work that runs once
per edit (`section_done()`).

A review step does not gate this — its own answer is stashed too, so it
re-validates like any other. What it gives you is somewhere to *land*: set
`reopen_step` to it and re-entering shows the answers with a change link each,
rather than dropping the user back at step one. A re-opened run has every step
answered, the review step included, and `SummaryMixin` drops the step doing the
summarising from its own rows so the page does not offer to change itself.

### Reaching a run from outside its own request

The hub is built on three classmethods that bind a wizard outside its own
dispatch, and they are public API in their own right:

| Method | Returns |
| --- | --- |
| `MyViewSet.begin(request, **url_kwargs)` | A fresh run — the start URL minus the redirect, for a caller that must remember the run id |
| `MyViewSet.inspect(request, run_id, **url_kwargs)` | An existing run, bound and ready to read. Walks nothing; raises `RunNotFound` |
| `MyViewSet.reopen(request, payload, ...)` | A run seeded from a stash — the run behind `resurrect()` |

Each hands back a `BoundWizard`, so `cursor()`, `path`, `step_url()` and
`entry_url()` all work as they do inside a dispatch. A tombstoned run is
*found*, not missing, so check `is_complete` before running one.

### Customising

Every decision is a hook. `get_sections()` chooses the sections per request,
`get_section_status()` decides how far one has got, `get_section_title()` names
it, `get_status_label()` reworks the wording, and `resume_section()` /
`reopen_section()` / `start_section()` each own one way into a run.
`stash_unusable()` handles a payload whose `label` no longer matches — it
re-raises by default, because silently starting over looks to the user exactly
like their answers vanishing.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/hub/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L337-L410)

---

## Testing your wizards

Driving a multi-step wizard with the raw Django test client means chasing the
run id through the session and hand-building step URLs. `gandalf.testing` does
that plumbing for you, and a pytest plugin ships with the package — installing
django-gandalf makes the `wizard_driver` fixture available with no conftest
wiring (it builds on [pytest-django](https://pytest-django.readthedocs.io/)'s
`client` fixture, so pytest-django must be installed).

`wizard_driver` is a factory: give it your viewset's `url_name` — the driver
reverses the same three names `urls()` published (see
[URLs and routing](#urls-and-routing)), so no test ever hand-builds a path — and
drive the whole wizard in one call. For the quickstart's signup wizard:

```python
def test_signup_collects_both_steps(wizard_driver):
    response, run = wizard_driver("signup").drive(
        [
            ("name", {"name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == 200
    assert run.is_completed
```

`drive()` starts a run (discovering its id from the session), POSTs each
`(step, data)` pair following redirects, and returns the final response along
with a `WizardRun` — URLs, requests, and stored state, all keyed by the run id.
Step by step, the same run object makes redirect and state assertions direct:

```python
def test_first_answer_advances_and_stores(wizard_driver):
    run = wizard_driver("signup").start()

    response = run.post_step("name", {"name": "Ada"})

    assert response["Location"] == run.step_url("email")
    assert run.state == [{"step": {"name": "Ada"}}]
```

Request helpers default to `follow=False` like the test client — pass
`follow=True` to land on the rendered next step (`response.context["form"]`
and friends work as usual). The run also exposes `run.url`, `run.get()`,
`run.get_step("name")` (the edit render of an answered step), `run.data` (the
raw session entry — `{"completed": True}` after `done()` fires), and
`run.seed_state([...])` for arranging stored state a request cycle can't
produce.

A few notes:

- **Mount-prefix kwargs.** A wizard mounted under
  `path("onboarding/<slug:plan>/", include(...))` is driven with
  `wizard_driver("onboarding", plan="team")` — the extra kwargs thread through
  every URL the driver builds.
- **Multiple runs.** `driver.start()` works with any number of existing runs;
  `driver.only_run()` and `driver.new_run(*known)` recover a run you didn't
  start yourself (a resurrected stash, say), raising `RunDiscoveryError` when
  the session is ambiguous.
- **Uploads** ride along as ordinary POST data:
  `run.post_step("photo", {"photo": SimpleUploadedFile("a.png", b"...")})`
  (with `from django.core.files.uploadedfile import SimpleUploadedFile`).
- **Session peeking and seeding.** `stored_runs(client)` /
  `stored_run(client, run_id)` / `seed_run(client, run_id, data)` read and
  write raw run entries; `stored_stash(client, key)` / `seed_stash(...)` do
  the same for stash payloads; and `stored_section_run(client, key)` /
  `seed_section_run(...)` do it for a hub's section-to-run bookkeeping — no
  session keys in your tests.
- **Outside pytest** the helpers work from any test:
  `WizardDriver(Client(), "signup")` (with
  `from django.test import Client` and
  `from gandalf.testing import WizardDriver`).
- Wizards with a **custom URL scheme** (overriding `get_wizard_url` /
  `get_step_url`) fall outside the driver's contract — drive those with the
  plain test client. To keep the plugin out of a run entirely:
  `pytest -p no:gandalf`.

Gandalf's own functional suite is written with these helpers, and the snippets
above are the checked-in tests for the signup example — **Source:**
[`test_readme_examples.py`](tests/functional/test_readme_examples.py).

---

## Configuration

Declaring steps is usually all you need; `.configure(...)` overrides a runtime
default when you want one. It is optional — a `WizardViewSet` configures a plain
`Wizard` with defaults automatically.

```python
signup_wizard = (
    Wizard()
    .step(AccountForm, name="account")
    .configure(file_storage_class=TenantFileStorage)
)
```

The same keyword pattern applies to every touch point on the configured wizard —
`form_view_factory`, `cursor_walker_class`, `step_dispatcher_class`,
`state_serializer_class`, and `step_router_class`. Each has a sensible default,
so you only configure what you need. For a custom URL scheme, subclass
`StepNameRouter` (routing on a different context key) and pass it as
`step_router_class`, or write the URL patterns yourself and override
`get_start_url()` / `get_wizard_url()` / `get_step_url()` on the viewset — see
[URLs and routing](#urls-and-routing).

For a runtime-level view of how the pieces fit together, see
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## What replaying costs

Gandalf re-proves stored submissions rather than trusting a recorded position.
The rule is small enough to keep in your head:

> A form's `clean()` runs **once per completed step per HTTP request.**

That holds however many times the request *reads* an answer: `RuntimeStep.form`
is built once per step per request, so a summary page listing every field of
every step costs one reconstruction per step, not one per field. (`path` builds
fresh step nodes on each access, so iterate the steps you hold rather than
re-reading `wizard.path` per field.)

So with `k` answers stored, a request costs `k` replays, and a POST costs one
more for the answer being submitted; completing an `N`-step run costs `N²`
validations end to end, spread over `2N` requests. **The number that matters is
not `N`, it is how many of your steps are expensive** — each completed step is
validated once per request whether the user is on step 5 or step 29, so `N²`
only bites when *most* steps do real work in `clean()`.

Measured on a 2023 laptop with `just bench`, for a linear wizard:

| steps | `clean()` | whole run | final POST |
|---|---|---|---|
| 30 | free | 72ms | 1.1ms |
| 30 | 5ms on *every* step | 6.7s | 222ms |

Gandalf's own share is about a millisecond per request at 30 steps; everything
else is your forms. If expensive `clean()` becomes a problem, move the work into
`done()` (where it runs once), store a cheaply-recheckable token, or accept that
some checks belong only at submission time. `just bench` measures your own
shapes, and `tests/functional/test_walk_cost.py` pins the counts so they cannot
regress unnoticed.

---

## Coming from `django-formtools`

Gandalf neither forks nor depends on `django-formtools` — the storage shape, the
URL model, and the re-proving walk all differ, so there is no drop-in
replacement. What maps cleanly is the *declaration*: a `form_list` becomes
chained `.step(...)` calls, and a `condition_dict` becomes
`.branch(condition(predicate, subflow))`. The predicates are the same idea — a
callable given the request — but a Gandalf predicate runs behind a
fully-validated prefix, so it reads prior answers with
`path.find_step(...).form.cleaned_data` unconditionally.

### Linear wizard

```python
# formtools
class CheckoutWizard(SessionWizardView):
    form_list = [CustomerForm, AddressForm, ConfirmForm]

# gandalf
checkout_wizard = (
    Wizard()
    .step(CustomerForm, name="customer")
    .step(AddressForm, name="address")
    .step(ConfirmForm, name="confirm")
)
```

### Conditional step inclusion

```python
# formtools — a condition_dict keyed by step name
def needs_vat(wizard):
    cleaned = wizard.get_cleaned_data_for_step("company") or {}
    return cleaned.get("is_business")

class CompanyWizard(SessionWizardView):
    form_list = [("company", CompanyForm), ("vat", VATForm), ("summary", SummaryForm)]
    condition_dict = {"vat": needs_vat}

# gandalf — the condition lives next to the step it guards
def needs_vat(request):
    company_step = request.wizard.path.find_step(name="company")
    return company_step.form.cleaned_data.get("is_business")

company_wizard = (
    Wizard()
    .step(CompanyForm, name="company")
    .branch(
        condition(needs_vat, Wizard().step(VATForm, name="vat")),
        default=None,  # skip VAT when the condition is false
    )
    .step(SummaryForm, name="summary")
)
```

### Tree-like branching with reusable subflows

```python
# formtools — branching lives in imperative get_next_step() logic
class OnboardingWizard(SessionWizardView):
    form_list = [AccountTypeForm, BizAForm, BizBForm, PersonAForm, FinalForm]

    def get_next_step(self, step=None):
        ...  # custom, dynamic next-step logic

# gandalf — the shape is the declaration
business_flow = Wizard().step(BizAForm, name="biz_a").step(BizBForm, name="biz_b")
personal_flow = Wizard().step(PersonAForm, name="person_a")

onboarding_wizard = (
    Wizard()
    .step(AccountTypeForm, name="account_type")
    .branch(
        condition(is_business_account, business_flow),
        default=personal_flow,
    )
    .step(FinalForm, name="final")
)
```

The payoff for tree-shaped journeys: branch condition and target stay together,
arms are reusable sub-wizards, and the whole flow is visible in one declaration
instead of growing bespoke navigation plumbing as branches multiply.

---

## Contributing

See `CONTRIBUTING.md` for local setup, workflow expectations, separated unit and
functional test commands, and commit message conventions.
