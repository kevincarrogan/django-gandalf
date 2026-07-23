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

That starts Django at **http://127.0.0.1:8000/**, whose index page links to
every wizard. Each section below ends with a **▶ Try it live** link to that
example's start URL, e.g. http://127.0.0.1:8000/readme/signup/. These are local
URLs — they only resolve while `just serve` is running.

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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/signup/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L37-L59)

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
shorthand for `context={"step_name": "email"}`. From `url_name`, `urls()`
publishes three patterns — the start URL, the bare run URL
(`signup/<run_id>/`), and the step URL (`signup/<run_id>/email/`). A step URL is
a *claim*: it either renders that step or redirects to wherever the run actually
is, so a stale link can never land an answer on the wrong step.

**A run re-proves itself on every request.** Gandalf stores raw submissions, not
"how far you got". On each request it replays the stored answers through their
forms up to the first missing or no-longer-valid one — that is what makes
position, branch selection, editing, and completion all fall out of a single
walk, and what makes stale state impossible. (The cost of that replay is
covered in [What replaying costs](#what-replaying-costs).)

**`done(self, bound_wizard)` receives the run, not a list of forms**, so it can
read the answers however it needs:

- `bound_wizard.path` — the linked chain of completed steps, in order. Each is a
  `RuntimeStep` exposing `.form.cleaned_data`, `.data` (raw submission), and
  `.files`.
- `MergeCleanedData().reduce(bound_wizard.path)` — folds every step's
  `cleaned_data` into one dict (last-write-wins). Subclass it for a different
  merge policy.
- `bound_wizard.find_step(name=...)` / `filter_steps(...)` — look a step up by
  name or any context key.
- `bound_wizard.runtime_tree` — the head of the walked tree (`.next` to the
  following step).
- `bound_wizard.get_state()` / `get_run_data()` — the raw stored JSON.

**Plain `Form` or full `FormView`.** Pass a plain `Form` and Gandalf generates
the step's `FormView` for you, rendered with the viewset's `template_name`. Pass
your own `FormView` when a step needs `get_initial()`, `get_form_kwargs()`, a
per-step template, or other view-level behavior — it keeps its own configuration
and can be reused as a standalone view outside the wizard. Inside the wizard the
step still sees `self.request.wizard`, so it can inspect run state when useful.

---

## Branching

`.branch()` forks the flow on a prior answer. Each arm is a sub-`Wizard` (or
`None` for "nothing extra here"); a `condition(predicate, arm)` pairs a
`predicate(request)` with the arm it selects. Selection is **first-match-wins**,
falling back to `default`.

```python
from gandalf.wizard import Wizard, condition


def is_business_account(request):
    account_step = request.wizard.find_step(name="account_type")
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
`find_step(...).form.cleaned_data` unconditionally without guarding for missing
answers.

Because arms are sub-`Wizard`s, they compose: define a subflow once and drop it
into several branches. Answers for a de-selected arm are kept as dormant memory,
so flipping account type from business to personal and back restores the earlier
business answers instead of re-asking them.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/branching/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L64-L90)

---

## Dynamic wizards: `get_wizard()`

When the shape of the flow depends on **request context** — tenant, permissions,
locale, feature flags — override `get_wizard(self, bound_wizard)` instead of
setting a class-level `wizard`. It is called with the `BoundWizard` for the
current request, and it can read stored state to shape itself:

```python
class DynamicWizardViewSet(WizardViewSet):
    url_name = "collect-items"
    template_name = "collect/step.html"

    def get_wizard(self, bound_wizard):
        state = bound_wizard.get_state()
        wizard = Wizard().step(ItemCountForm, name="count")
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(ItemForm, name=f"item-{index}")
        return wizard
```

Here the user picks a count, and the same view regenerates that many item steps
from the stored count on each request.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/dynamic/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L95-L116)

---

## `.expand()`: grow the wizard from a prior answer

A branch chooses between subflows you declared up front. Sometimes the *shape*
of the flow is not known until a prior **answer** supplies it — N item steps for
a count the user just typed. `.expand()` grows the tree during the walk from a
builder you provide:

```python
def build_item_steps(request):
    count = int(request.wizard.find_step(name="count").form.cleaned_data["count"])
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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/expand/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L121-L154)

---

## Back-navigation: editing earlier steps

Because every step has its own URL, an "edit" affordance is just a link. GET a
completed step's URL to render it pre-filled; POST the changed answer back to it
to place it there. Editing is not a separate operation — putting an answer at a
step works the same whether or not it already had one.

A review template wires per-step edit links from the runtime path:

```django
<h1>Review your details</h1>
<ul>
  {% for step in request.wizard.path %}
    <li>
      <a href="../{{ step.declaration.context.step_name }}/">
        Edit {{ step.declaration.context.step_name }}
      </a>
    </li>
  {% endfor %}
</ul>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Confirm</button>
</form>
```

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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/editing/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L195-L217)

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
        photo_step = bound_wizard.find_step(name="photo")
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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/file-upload/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L159-L172)

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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/escape/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L178-L189)
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
`get_wizard_url()` / `get_step_url()` on the viewset.

For a runtime-level view of how the pieces fit together, see
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## What replaying costs

Gandalf re-proves stored submissions rather than trusting a recorded position.
The rule is small enough to keep in your head:

> A form's `clean()` runs **once per completed step per HTTP request.**

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
`find_step(...).form.cleaned_data` unconditionally.

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
    company_step = request.wizard.find_step(name="company")
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
