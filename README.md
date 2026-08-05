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

- `bound_wizard.path` — the resolved route: the answered steps in order,
  iterable, each a `RuntimeStep` exposing `.form.cleaned_data`, `.data` (raw
  submission), and `.files`.
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
the step's `FormView` for you, rendered with the viewset's `template_name`. Pass
your own `FormView` when a step needs `get_initial()`, `get_form_kwargs()`, a
per-step template, or other view-level behavior — it keeps its own configuration
and can be reused as a standalone view outside the wizard. Inside the wizard the
step still sees `self.request.wizard`, so it can inspect run state when useful.
See [Step views](#step-views-bringing-your-own-formview) for what such a view
must provide and what it sees when it reads run state.

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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/editing/ &nbsp;·&nbsp; **Source:** [`readme_examples.py`](tests/testapp/readme_examples.py#L216-L238)

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

Pass a plain `Form` and Gandalf generates the step's view. Pass your own
`FormView` when the step needs view-level behavior — a per-step template,
`get_initial()`, `get_form_kwargs()`, a custom `form_valid()`.

A step view is dispatched as an ordinary Django view, so it needs the two things
any standalone `FormView` needs. Gandalf supplies neither for a view you bring
yourself:

- **`template_name`** (or `get_template_names()`). A step with its own view does
  *not* inherit the viewset's `template_name` — that default only reaches the
  views Gandalf generates. Without one, rendering raises `ImproperlyConfigured`.
- **`get_success_url()`** (or `success_url`). Gandalf reads only the *status
  code* of the step's response — a 3xx means "this answer stands, carry on" —
  and discards the response, so the URL is never followed. `self.request.path`
  is the idiomatic no-op, and is what the generated views use. Without one, a
  valid POST raises `ImproperlyConfigured`.

```python
from django.views.generic.edit import FormView


class BillingStepView(FormView):
    form_class = BillingForm
    template_name = "billing/step.html"

    def get_success_url(self):
        return self.request.path

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
`self.request.path` no-op.

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
        return redirect("contact-section")  # nothing stashed — start fresh
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
  default is the cursor, or the first step when complete). For the same reason,
  one successful edit walks straight through to completion and fires `done()`
  again — give the wizard a review step if you want an explicit confirm gate.
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

## Testing your wizards

Driving a multi-step wizard with the raw Django test client means chasing the
run id through the session and hand-building step URLs. `gandalf.testing` does
that plumbing for you, and a pytest plugin ships with the package — installing
django-gandalf makes the `wizard_driver` fixture available with no conftest
wiring (it builds on [pytest-django](https://pytest-django.readthedocs.io/)'s
`client` fixture, so pytest-django must be installed).

`wizard_driver` is a factory: give it your viewset's `url_name` and drive the
whole wizard in one call. For the quickstart's signup wizard:

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
  the same for stash payloads — no session keys in your tests.
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
