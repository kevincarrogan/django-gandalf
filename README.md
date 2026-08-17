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

**Every step is named, and every step gets its own URL.** Keyword arguments to
`.step()` become the step's context, so `name="email"` is an ordinary context
entry — the one the default router reads. From `url_name`, `urls()`
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

### `.switch()`: one case per outcome

When a fork is "which of these", not "is this true", `.switch()` says so
directly. The selector returns the name of the case that applies:

```python
from gandalf.wizard import Wizard, on_field


wizard = (
    Wizard()
    .step(CompanyForm, name="company")
    .switch(
        on_field("company", "company_type"),
        {
            "limited": Wizard().step(RegistrationForm, name="registration"),
            "partnership": Wizard().step(PartnersForm, name="partners"),
        },
        default=Wizard().step(OwnerForm, name="owner"),
    )
)
```

A selector is the same arbitrary code a predicate is — read several answers,
call out to a service, compute whatever you like — but asking *which* rather
than *whether* buys three things. Exactly one case can apply, so overlapping
conditions cannot resolve by declaration order. The selector runs **once per
switch** however many cases there are, so it is free to be expensive. And each
case's answers are stored under its own name rather than its position, so
reordering the cases cannot strand them.

`on_field(step, field)` is the common case said declaratively — route on the
value of an earlier answer. Prefer a plain function whenever the decision is
anything more than "what did they say"; a multi-valued field has no single
value to switch on, so route those with a predicate `.branch()` or a selector
of your own.

A value no case names falls to `default`, or past the switch entirely when
there is none.

> ▶ **Try it live:** http://127.0.0.1:8000/switch-wizard/

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

That positional storage is exactly why `.expand()` is the wrong tool for a list
the user grows and prunes over time — deleting from the middle would shift every
answer after it. For that, see
[Add another: a collection of items](#add-another-a-collection-of-items), where
each item is its own run and identity is opaque.

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

> **Optional module.** `gandalf.summary` reads a run's answers back for
> display; nothing in the core depends on it. Skip this unless a step of
> yours shows people what they have entered.

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
        .step(NameForm, name="name", label="Your name")
        .step(DeliveryForm, name="delivery", label="Delivery")
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
  <button type="submit">Confirm and continue</button>
</form>
```

`ConfirmForm` has no fields at all — the button *is* the confirmation, and a
required checkbox beside it asks the same question twice while giving the user
a way to get it wrong. Gandalf reads a submission, not a field: an empty
submission is still a submission, and only a missing entry (`{"step": null}`)
is a hole.

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

Gandalf ships type annotations (`py.typed`), and `StepFormView` declares its
`request` as a `WizardRequest` — an `HttpRequest` carrying `wizard` — so
`self.request.wizard` type-checks with no cast, and a type checker makes that
guard concrete by typing `find_step()` as returning an optional step:

```python
from typing import Any


    def get_initial(self) -> dict[str, Any]:
        initial: dict[str, Any] = super().get_initial()
        account = self.request.wizard.path.find_step(name="account")
        if account is not None:
            initial["company"] = account.form.cleaned_data["email"].partition("@")[2]
        return initial
```

Branch predicates and `.expand()` builders are handed the same request, so
annotate those with `WizardRequest` (importable from `gandalf.types`) to reach
`request.wizard` inside them; one declaring a plain `HttpRequest` still fits.

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
    .step(EmailForm, slug="email-address")
    .configure(
        template_name="signup/step.html",   # a pre-configured wizard is taken
        step_router_class=StepSlugRouter,   # as-is, so set this here too
    )
)
```

(`name=` carries no special weight at declaration time — it is just the key the
default router reads, so a router keyed on `slug` reads `slug=` instead.)

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
into runs that have expired. A durable *collection* needs the same two, with a
`SessionCollectionStore` replacement in place of the section store — it is the
section store plus an ordered registry, so one swap covers both halves.

A durable store also closes a race the session cannot: Django read-modify-writes
the whole session, so two tabs entering the same section can lose a registration
outright, where a unique constraint on `(owner, section_key)` settles it. For a
collection the race is strictly worse — `add_item` appends to a *list*, so two
tabs adding at once both read the old list, both append one, and an item is lost
outright rather than overwritten with an equivalent value. A table with
`UniqueConstraint(owner, collection_key, item_id)` and an explicit `position`
settles that too; `ModelCollectionStore` in
[`durable.py`](tests/testapp/durable.py) is the worked example.

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
  run is created. A collection's items all share one label, per collection
  rather than per item: they are one shape wearing many ids, and a per-item
  label would match nothing.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/stash/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L276-L302)

---

## Hub and spoke: parallel sections

> **Optional module.** `gandalf.sections` is a pattern built on everything
> above, with its own vocabulary and a second storage seam. Nothing in the
> core depends on it, and it costs nothing if you never import it. Skip
> this unless one journey is really several.

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
        .step(NameForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
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

## Add another: a collection of items

Some things a journey collects are not one answer but a list of them, and the
user decides how long the list is: guests, dependants, previous addresses,
employments. `gandalf.collections` is the "add another" pattern — a page
listing what has been added so far, with **Change** and **Remove** on each row,
an **Add another** question, and one item wizard behind all of them.

A collection is a hub whose sections are *built* rather than declared: one per
id in an ordered registry the user grows. Everything the hub does — the status
derivation, the resume-before-reopen door, the no-bare-run-URL guarantee —
applies unchanged.

```python
from django.urls import include, path
from gandalf.collections import CollectionView, ItemSectionMixin
from gandalf.sections import HubView, Section, SectionMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class GuestItemViewSet(ItemSectionMixin, WizardViewSet):
    url_name = "party-guest"
    template_name = "party/step.html"
    collection_key = "guests"
    collection_url_name = "party-guests"
    # The answer that names a row, cached when the item finishes.
    item_title_step = "guest"
    item_title_field = "name"
    wizard = (
        Wizard()
        .step(GuestForm, name="guest", label="Guest")
        .step(ReviewStepView, name="review")
    )

    def section_done(self, bound_wizard):
        save_guest(self.request.user, self.get_item_id(), bound_wizard)
        return super().section_done(bound_wizard)  # back to the collection


class GuestCollectionView(CollectionView):
    template_name = "party/guests.html"
    remove_template_name = "party/remove_guest.html"
    url_name = "party-guests"
    collection_key = "guests"
    item_viewset = GuestItemViewSet
    item_name = "Guest"
    item_reopen_step = "review"
    continue_url_name = "party-hub"


class PartyHubView(HubView):
    template_name = "party/hub.html"
    url_name = "party-hub"
    section_url_name = "party-hub-section"
    sections = [
        Section("venue", VenueSectionViewSet, title="Venue"),
        GuestCollectionView.as_section("guests", title="Guests"),
    ]
```

### Mount the three as siblings, never nested

This is the one thing that will bite you, and it fails silently:

```python
urlpatterns = [
    path("party/", include(PartyHubView.urls())),
    path("party-venue/", include(VenueSectionViewSet.urls())),
    path("party-guests/", include(GuestCollectionView.urls())),
    path("party-guest/<uuid:item>/", include(GuestItemViewSet.urls())),
]
```

`HubView` publishes `<slug:section>/`, which matches **any** single segment —
so a collection mounted at `party/guests/` is swallowed by the hub's own door
for a section named `guests`. And `WizardViewSet` publishes `""` as its start
URL — so an item wizard mounted at `party-guests/<uuid:item>/` occupies the
exact path of the collection's door for that item. Either way, whichever
`include()` is listed first wins, and the symptom is "Change stopped working"
rather than anything that looks like a URL conflict.

The collection publishes three patterns from `url_name`: the page (GET lists,
POST answers *add another*), `<url_name>-item` (the door into one item) and
`<url_name>-remove` (confirm on GET, remove on POST). The item kwarg is a
`uuid` rather than a slug, which is what lets `remove/` be a safe sibling.

```django
{% if collection.is_empty %}
  <h1>You have not added any guests</h1>
{% else %}
  <h1>You have added {{ collection.count }} guest{{ collection.count|pluralize }}</h1>
  <ul>
    {% for row in collection.rows %}
      <li>
        {{ row.title }}
        <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
        <a href="{{ row.url }}">Change</a>
        <a href="{{ row.remove_url }}">Remove</a>
      </li>
    {% endfor %}
  </ul>
{% endif %}
<form method="post">
  {% csrf_token %}
  {{ form.errors.add_another }}
  <button type="submit" name="add_another" value="yes">Add another guest</button>
  {% if not collection.is_empty %}
    <button type="submit" name="add_another" value="no">Continue</button>
  {% endif %}
</form>
```

The view reads one POST field, so two submit buttons carry the answer and the
question needs no widget of its own. `AddAnotherForm` still validates it —
render it as a radio instead if your service asks the question that way, and
`form_class` swaps it for something else entirely.

### Identity is opaque, so removing renumbers nothing

An item is a uuid, never a position. Delete from the middle and the survivors
keep their ids, their URLs and their answers — a link the user already has
still names the item they meant. This is the single biggest reason a collection
is not `.expand()`.

### The item id travels in the item wizard's own URL

`ItemSectionMixin` takes its section key from `self.kwargs["item"]`, which is
how `done()` knows which item it is recording. It is *this wizard's* mount
prefix, forwarded into every URL the wizard builds for itself by
`get_url_kwargs()` — and dropped from the collection's own URLs, which is why
a finished item lands back on the page rather than on a URL with its own id in
it.

### A row costs no walk

An item is titled by the answer named in `item_title_step` / `item_title_field`,
worked out **once, when the item finishes**, and cached. The page reads a
string. That is one walk per completion — on a request that already walked
twice — in exchange for none on every later render of the page and of the task
list above it. An item that has never finished falls back to a positional name
(`Guest 2`), which is honest: nothing it has answered is known to name it.
Override `get_item_title(bound_wizard)` when the name is not one field.

### Completeness is declared, not derived

| Status | Comes from |
| --- | --- |
| **Not started** | No items |
| **Incomplete** | Items, but the user has not said there are no more — or has, while one is unfinished or `min_items` is unmet |
| **Complete** | The user answered *no more to add*, every item has finished, and there are at least `min_items` |

No reading of storage can say whether the user has more guests to add. Only the
user can, so the page asks and the answer is stored. Answering *yes* again
withdraws it — pressing **Add another** *is* the user changing their mind, so
they are put past the question once more. Removing an item does not re-ask it:
three guests minus one is still "and no more".

### Full CRUD, and the order each action takes

| Action | What happens |
| --- | --- |
| **Add** | The item is registered *first*, then its wizard starts — which is what lets a half-finished item have a row, and leaves a listed, removable row rather than an orphan run if entering fails |
| **Read** | One `Section` per registered id; the hub's own status derivation and row building, unchanged |
| **Change** | The door resumes a live run or re-opens a stash. A re-opened item has every answer valid, so the next submission walks to the end and re-saves — and re-caches the title, so a rename shows on the page |
| **Remove** | Run obliterated → run cleared → stash deleted → title cleared → `item_removed()` → registry entry last, so a hook that raises leaves the item still listed and still removable |

Every link the page hands out is a step URL by construction, exactly as a hub's
is, and for the same reason: a run whose every stored answer validates
completes on a GET.

### Why not `.expand()`?

[`.expand()`](#expand-grow-the-wizard-from-a-prior-answer) grows *steps inside one run* from a
count the user has just given. It is the right tool for "how many children? now
tell me about each", and the wrong one here:

* Its answers are one positional list under a single `{"expand": [...]}` entry,
  so deleting from the middle shifts every answer after it down a slot and
  item 3's answers become item 2's.
* Identity is positional (`name=f"item-{index}"`), so a live URL repoints when
  something slides into its slot.
* Every item lives in **one run**, so there is no such thing as a half-finished
  *item*, and nothing can be saved per item.

Use a collection when the items are separately resumable, separately
completable and separately destroyable — which is what "add as many as you
like, and change your mind later" means.

### Customising

`get_item_ids()` chooses the items — override it to build the list from your
own records instead of the registry, and the page's routes follow it.
`new_item_id()` mints identity, `get_item_title()` names a row,
`get_collection_status()` decides how far the whole thing has got,
`item_removed()` is where the application deletes whatever `section_done()`
saved, and `collection_done()` is what happens when the user says that is all.
`min_items` makes "at least one" declarative.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/guests/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L399-L456)

---

## Asking what a wizard is

> **Optional to know about.** `wizard.outline()` is a read of the declaration.
> Skip this unless something needs to know a journey's shape.

A configured wizard can describe itself, as data:

```python
wizard = Wizard().step(CompanyForm, name="company").switch(...).configure(...)

wizard.outline()
# [{"kind": "step", "name": "company", "context": {...}, "declaration": ...},
#  {"kind": "switch", "decided_by": "company.company_type",
#   "source": {"step": "company", "field": "company_type"},
#   "cases": [{"case": "limited", "steps": [...]}, ...], "default": [...]}]
```

It is the data counterpart of the tree `repr()` you get while debugging: every
step in order, every fork with **all** of its possible routes, and a marker
wherever `.expand()` grows the tree from an answer. Since it describes the
declaration, it needs no run, no request and no storage — the same answer
before anybody starts and after they finish. A dynamic `get_wizard()` is
described as it currently resolves, which is the honest answer when the shape
is a function of the run.

`WizardViewSet.resolve(request)` is the third door alongside `begin()` and
`inspect()`: it binds the wizard without creating a run, for when the question
is *what is this wizard* rather than *run it* or *reach that run*.

Useful for a progress indicator that has to cope with branches, for generating
documentation or a diagram of a journey, for a test that pins a wizard's shape
— and for anything else that needs to know a journey's shape without
walking it.

---

## Watching a run

> **Optional module.** `gandalf.observers` is a hook and a no-op base class.
> Skip this unless you want to know how your wizards are actually going.

Which step do people get wrong most often? How many abandon at the address?
Does the branch that asks for company details lose people? None of that is
visible from outside a run, and all of it is one line from inside. Declare an
observer and it is told what happens, for every run of that wizard — over
HTTP, from a script, or from a test:

```python
from gandalf.observers import WizardObserver
from gandalf.wizard import Wizard


class CountRejections(WizardObserver):
    def submission(self, step, accepted, metadata):
        if not accepted:
            statsd.increment(
                "wizard.rejected",
                tags=[f"step:{step.context['name']}", f"run:{self.run_id}"],
            )


wizard = (
    Wizard()
    .step(EmailForm, name="email")
    .configure(template_name="signup/step.html", observer_class=CountRejections)
)
```

Two things about it are deliberate.

**One event per placement, not per validation.** A run re-proves every stored
answer on every request — see [What replaying costs](#what-replaying-costs) —
so an observer told about validations would count one mistyped email again on
every page that followed it. `submission()` fires only when an answer is
actually placed, so counting `accepted=False` counts mistakes people made.

**Observers see what happened, never what was said.** A step's answers are
somebody's name, date of birth and address, so an observer is handed the step
*declaration* and the outcome — enough to count, group and compare, and not
enough to leak personal data into a metrics backend. When you do want the
answers, take them where you already have them and where the decision is
visible in your own code: `done()`, or whatever is driving the run.

An observer is built once per run and knows which run it is watching, so no
event repeats it. What it is *not* told is **who** is on the other end. The
library cannot know: a submission arrives through a request, and whether that
is a person in a browser, a script, or a management command is your
application's knowledge.

What it *is* told is whatever the placement claimed about itself, carried
unread. `metadata` is `None` for a browser submission, because a request makes
no such claim, and `{"unattended": True}` for one
[a driver made](#driving-a-wizard-from-python) unless the caller said
otherwise. In a journey people and agents share, that is usually the
distinction you wanted:

```python
def submission(self, step, accepted, metadata):
    if (metadata or {}).get("unattended"):
        statsd.increment("wizard.unattended")
```

There is no "run started" event, because a run exists before its wizard is
resolved — that ordering is what lets a dynamic `get_wizard()` read stored
state to decide its own shape. Count first submissions, or record creation
where you mint it.

---

## Driving a wizard from Python

> **Optional module.** `gandalf.driver` needs nothing but Django and is
> never imported unless you ask for it. Skip this unless something other
> than a browser needs to answer your steps.

Everything so far assumes a person and a browser. `gandalf.driver` is the
same wizard without either: `RunDriver` walks a run by calling the runtime
directly, so a data import, a management command, an admin action — or an
AI agent holding somebody's details — can answer steps as data.

```python
from gandalf.driver import RunDriver

driver = RunDriver.begin(SignupWizardViewSet)

driver.describe().schema        # JSON Schema for the current step's form
driver.submit({"name": "Ada"})
result = driver.submit({"email": "ada@example.com"})
if result.status == "complete":
    driver.finish()             # fires done() exactly once
```

`submit()` reports `"advanced"`, `"invalid"` (with `errors` in
`form.errors.get_json_data()` shape), `"complete"`, or `"escaped"`;
`submit(data, step="account_type")` edits an earlier answer and lets the walk
re-route from it. Three more methods exist for callers filling a run from
data they already hold:

| | |
|---|---|
| `outline()` | the declared journey before any answers exist — every step with its schema, every fork with all of its possible routes |
| `check(answers)` | what a bag of answers *would* do, without placing any of it: what is invalid, what is still missing, what could not be judged |
| `prefill(answers)` | place as many as the tree will take, following branches and expansions, and report the residue |

`answers()` hands back cleaned values — a `DateField` gives a `datetime.date`,
which is what a management command wants and what `submit()` takes straight
back. A caller that has to serialise them asks:
`driver.answers(json_safe=True)`, or `driver.describe(json_safe=True)` to
convert the whole description without reading the answers twice. It is the
cleaned answer that is rendered, so a ticked checkbox is `True` rather than
the `"on"` a browser posted.

Nothing here is a second implementation. Every operation is the one a request
performs, so a run filled programmatically is an ordinary run: same `run_id`,
same stored state, same re-validation. With a durable
[storage backend](#completion-and-storage) you can fill a run from a script
and hand somebody `bound_wizard.entry_url("review")` to check and confirm in
the browser — and the two can take turns on the same run.

### Answering for somebody else

Two things follow from a caller that is not a person, and only one of them is
the library's business.

**Concluding a run is opt-in.** `done()` is where the irreversible things
live — the charge, the submission, the email — and a person confirming reaches
it through the viewset's own dispatch, never through a driver. So `finish()`
refuses unless the driver was built to allow it:

```python
driver = RunDriver.begin(QuoteViewSet, may_finish=True)
```

Without it, `finish()` raises `ConfirmationRequired`. It is a plain flag
because the interesting question is *when* it should be true — agreement
collected before the answers exist is not agreement about the answers — and
that is the caller's to answer, at the point it knows.

**Every placement records who made it.** A mapping is stored beside the
answer, and `RunDriver` marks its own placements `{"unattended": True}`, since
the answers alone cannot say so:

```python
driver.submit({"excess": "250"}, metadata={"placed_by": "person"})
driver.placements()["coverage"].metadata     # {"placed_by": "person"}
```

`placements()` is the single read of a run: every answered step, keyed by
name, carrying the answers, the files stored with them, and that metadata —
all from one walk. `answers()` is the same read with the other two dropped.

That is the fact. What to *do* with it is yours, because "whose answer is
this" is a question about your domain rather than about wizards. A caller
that must not overwrite what somebody typed asks before it submits:

```python
placement = driver.placements().get(step)
if placement and not placement.metadata.get("unattended"):
    raise SomebodyElsesAnswer(step)      # your rule, your exception
driver.submit(data, step=step)
```

A step nobody has answered has no placement at all, which is why the rule
asks for one rather than defaulting: "not the driver's own answer" and "no
answer yet" are different facts, and only the first is somebody else's.

Without the metadata there is no way to write that rule at all — a driver
cannot tell the answer it placed from the one a person changed, and correcting
its own earlier answer is something it must keep being allowed to do, since
that is how it recovers from a rejected one.

**Files go both ways.** A run whose file step was answered through a browser
reads back as an ordinary placement — `placements()` carries the stored
reference, and `json_safe=True` renders it as that reference rather than
failing on an open file. `open_file()` gets from the reference to the bytes,
which is the check a form's own `clean()` cannot make:

```python
placement = driver.placements()["licence"]
document = driver.open_file(placement.files["scan"])   # -> UploadedFile
```

And a driver can place one, exactly as a multipart POST would:

```python
driver.submit({}, files={"scan": uploaded_file})
```

A file goes in `files` rather than in `data`, because `data` is stored as
state and state is JSON. Omitting `files` says nothing about files rather
than clearing them, so reading a step, changing one field and submitting it
back keeps the document attached to it. What lands is an ordinary placement
marked `{"unattended": True}` like any other, so a rule about whose answers
may be changed governs an uploaded document with no special case for it.

A `FileField` is described as `{"type": "string", "format": "binary"}` — the
JSON Schema way of saying *this is a file*. Branch on the `format` if you
need to know; the description beside it says the same thing in words, and
words get reworded.

> **Source:** the snippets above are driven against the README's own wizards in
> [`test_driver_journeys.py`](tests/functional/test_driver_journeys.py).
>
> **See also:** [AGENT_ACCESS.md](AGENT_ACCESS.md) for the design behind this,
> including how an AI agent uses it and the worked examples in `examples/`.

---

## Driving a wizard with a model

`RunDriver` is deliberately ignorant of agents — it takes answers and gives
back schemas, and where those answers came from is not its business. If you
want the other half, it ships beside the library rather than inside it:

```
pip install django-gandalf[agent] "pydantic-ai-slim[openai]"
```

The extra brings [pydantic-ai](https://ai.pydantic.dev/) and the AG-UI
transport. **It names no provider** — that is yours to choose and yours to
install, and `build_agent` takes whatever pydantic-ai takes.

```python
from gandalf.contrib.agent import AgentProfile, build_agent

class QuoteViewSet(WizardViewSet):
    wizard = ...
    agent = AgentProfile(
        purpose="a business insurance quote",
        notes="Vehicles are added on the fleet page, not here.",
    )

agent = build_agent(QuoteViewSet, "openai:gpt-5.2")
```

`AgentProfile` is the only thing that changes between wizards. `purpose`
completes the sentence *"you are helping someone with —"*; `notes` is for
what a wizard cannot say about itself, like something the person needs
living on a different page.

The agent gets tools that are the driver: read the journey before starting,
start a run or pick an existing one back up by its id, look at it without
touching it, try a bag of answers without placing any, fill what it holds,
correct itself, hand the run back. That last pair
is what makes a handover work in both directions — the person can open the
form mid-conversation, change something, and the agent sees it when it
looks again, because a run lives in storage rather than in the chat. Two things it does not get:

- **No tool concludes a run.** `done()` is where the irreversible things
  live, and an agent that can reach them will eventually reach them on
  somebody's behalf. `handoff` returns a link to the person instead.
- **No edit policy.** Whose an answer is is a question about your domain,
  not about wizards — `placements()` tells you who placed what, and `wrap`
  is where a rule about it goes.

To serve it over HTTP, `gandalf.contrib.agent.agui.endpoint_for(agent)`
returns a Django view that speaks AG-UI. One process, one origin, one
database: the run the agent fills is the run the browser opens.

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
- **Arranging a part-answered run.** `seed_state` writes stored state
  *verbatim*, so reach for it only when the state is one no walk would place —
  a legacy shape, a tampered entry, an answer sitting behind an unanswered
  step. Answers the walk can reach are better placed than written: fill the run
  with a [`RunDriver`](#driving-a-wizard-from-python) over the client's own
  session, and the state is whatever the runtime really produces.

  ```python
  from gandalf.driver import RunDriver, fabricate_request

  session = client.session
  driver = RunDriver.resume(
      SignupWizardViewSet,
      run.run_id,
      request=fabricate_request(session=session),
  )
  driver.prefill({"name": {"name": "Ada"}, "email": {"email": "ada@example.com"}})
  session.save()   # nothing saves a session outside the request cycle
  ```

  It is also how you arrange a run that is *complete* but unfinished — the last
  answer a browser posts fires `done()` on the way past, and a driver's does
  not.
- **Session peeking and seeding.** `stored_runs(client)` /
  `stored_run(client, run_id)` / `seed_run(client, run_id, data)` read and
  write raw run entries; `stored_stash(client, key)` / `seed_stash(...)` do
  the same for stash payloads; and `stored_section_run(client, key)` /
  `seed_section_run(...)` do it for a hub's section-to-run bookkeeping — no
  session keys in your tests.
- **Outside pytest** the helpers work from any test:
  `WizardTestDriver(Client(), "signup")` (with
  `from django.test import Client` and
  `from gandalf.testing import WizardTestDriver`).
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
[ARCHITECTURE.md](ARCHITECTURE.md). For driving a wizard programmatically —
an AI agent submitting steps as data instead of clicking the forms — see
[AGENT_ACCESS.md](AGENT_ACCESS.md).

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
