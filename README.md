# django-gandalf

`django-gandalf` helps you declare **complex, tree-like Django form flows** as readable, composable code.

It is built for the point where your journey stops being a straight line and starts branching repeatedly:

- user type branches (business vs individual),
- regional branches (domestic vs international),
- nested compliance/risk sub-flows,
- optional setup paths,
- reusable path fragments shared across journeys.

Instead of stitching this together with scattered step conditions and navigation overrides, `django-gandalf` aims to let you describe the flow as one explicit tree.

## Relationship to `django-formtools`

[`django-formtools`](https://github.com/jazzband/django-formtools) is the
de-facto library for multi-step form wizards in Django. It provides
`SessionWizardView` / `CookieWizardView`, a `form_list` of steps, and a
`condition_dict` for skipping steps based on prior input. It is solid for
linear or lightly-conditional flows, and many Django projects already use it.

`django-gandalf` is not a fork of `django-formtools` and does not depend on it.
It is a separate library that targets the same problem space — multi-step form
journeys — but takes a different approach aimed at the case where the flow
becomes a branching tree rather than a list with a few skips. Where formtools
expresses branching as a `condition_dict` mapping step names to predicate
callables (with navigation hooks like `get_next_step()` for anything more
involved), Gandalf expresses the entire flow as a single chained declaration
built from `.step(...)` and `.branch(...)`.

The examples throughout this README put the two styles side by side. They are
written that way because `django-formtools` is the most familiar reference
point for what a Django wizard normally looks like, not because Gandalf is a
drop-in replacement or a migration target. If your flows are linear, formtools
is likely the simpler choice; Gandalf is aimed at the branching, tree-shaped
case described above.

## The simplest case: a linear wizard with a merged-payload `done()`

Before the branching examples, here is the shortest end-to-end flow:
a linear two-step signup wizard that collects form data and dispatches a
merged payload from `done()`. This is the shape you start with; the
branching examples below show how the same declarations grow.

### formtools style

```python
from django import forms
from django.http import HttpResponse
from formtools.wizard.views import SessionWizardView


class NameForm(forms.Form):
    name = forms.CharField()


class EmailForm(forms.Form):
    email = forms.EmailField()


class SignupWizard(SessionWizardView):
    form_list = [
        ("name", NameForm),
        ("email", EmailForm),
    ]
    template_name = "signup/step.html"

    def done(self, form_list, **kwargs):
        payload = {}
        for form in form_list:
            payload.update(form.cleaned_data)
        create_account(**payload)
        return HttpResponse("Thanks!")
```

### django-gandalf style

```python
from django import forms
from django.http import HttpResponse
from gandalf import wizard
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData


class NameForm(forms.Form):
    name = forms.CharField()


class EmailForm(forms.Form):
    email = forms.EmailField()


class SignupWizardViewSet(WizardViewSet):
    url_name = "signup"
    wizard = (
        wizard.step(NameForm, name="name")
        .step(EmailForm, name="email")
        .configure(template_name="signup/step.html")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        create_account(**payload)
        return HttpResponse("Thanks!")
```

mounted with a single include:

```python
from django.urls import include, path

urlpatterns = [
    path("signup/", include(SignupWizardViewSet.urls())),
]
```

A few things to notice:

- The wizard is declared as a chained builder rather than a list of
  `(name, form)` tuples. Each `.step(...)` returns a new `Wizard`; nothing
  mutates in place.
- Every step is named, and every step gets its own URL
  (`signup/<run_id>/name/`, `signup/<run_id>/email/`) derived from
  `url_name` by `urls()`.
- `bound_wizard.path` is the linked chain of completed steps for the
  current run, in execution order.
- `MergeCleanedData` is a `tree.Reducer` that folds each step's
  `form.cleaned_data` into a single dict using last-write-wins. The merge
  policy lives in the reducer, not in the wizard — subclass
  `MergeCleanedData` (or write your own `tree.Reducer`) for a different
  policy.
- `done()` receives the `BoundWizard` itself rather than a list of forms,
  so it can also inspect the path, look up steps by context, or read the
  raw storage state as needed.

Gandalf is not dramatically shorter for the linear case. The point is
that the same declaration grows naturally into the tree-shaped flows
shown below; you do not switch APIs when the flow gets complex.

## The core aim (up front): model branching flows cleanly

Here is the same branching onboarding idea in both styles.

### formtools style (when the flow becomes tree-like)

```python
from formtools.wizard.views import SessionWizardView


def is_business_account(wizard):
    account_type = wizard.get_cleaned_data_for_step("account_type") or {}
    return account_type.get("account_type") == "business"


def needs_international_checks(wizard):
    account_type = wizard.get_cleaned_data_for_step("account_type") or {}
    return account_type.get("region") == "international"


class OnboardingWizard(SessionWizardView):
    form_list = [
        ("account_type", AccountTypeForm),
        ("biz_details", BizDetailsForm),
        ("biz_compliance", BizComplianceForm),
        ("intl_tax", IntlTaxForm),
        ("intl_kyc", IntlKYCForm),
        ("profile", ProfileForm),
        ("review", ReviewForm),
        ("confirmation", ConfirmationForm),
    ]

    condition_dict = {
        "biz_details": is_business_account,
        "biz_compliance": is_business_account,
        "intl_tax": needs_international_checks,
        "intl_kyc": needs_international_checks,
        "profile": lambda wizard: not is_business_account(wizard),
    }
```

### django-gandalf style (same flow, explicit as a tree)

```python
international_flow = (
    wizard.step(IntlTaxForm)
    .step(IntlKYCForm)
)
business_flow = (
    wizard.step(BizDetailsForm)
    .step(BizComplianceForm)
    .branch(
        condition(needs_international_checks, international_flow),
        default=None,
    )
)
personal_flow = (
    wizard.branch(
        condition(needs_international_checks, international_flow),
        default=None,
    )
    .step(ProfileForm)
)

onboarding_wizard = (
    wizard.step(AccountTypeForm)
    .branch(
        condition(is_business_account, business_flow),
        default=personal_flow,
    )
    .step(ReviewForm)
    .step(ConfirmationForm)
)
```

Branch selection is **first-match-wins**. Gandalf evaluates branch conditions in
the order you declare them and short-circuits on the first truthy condition,
then routes into only that branch for the active execution path.

Why this is better in this project’s sweet spot (complex branching):

- Branch condition and target flow stay together (no separate lookup table).
- Branch targets can be reusable subflows (`business_flow`, `international_flow`, etc.).
- The overall journey is visible in one declaration as a tree.
- You avoid growing custom step-navigation plumbing as branches multiply.

This is the project’s focus: make real-world flow trees clear and composable, not just linear demos.

---

## Why this exists

Traditional wizard tooling is great for simple, linear steps, but it gets harder to reason about once branching and nested subflows become the norm.

`django-gandalf` is intended to make tree-style journeys easier to express than `django-formtools` by favoring explicit, composable flow declarations.

---

## Design goals

- **Declarative flow definitions**: read the flow structure in one place.
- **Chainable API**: build flows with `.step()` and `.branch()`.
- **Branching as a first-class concept**: nested and conditional flows should be easy to model.
- **Reusable flow fragments**: define mini-wizards and compose them into larger trees.
- **Easy by default**: pass a plain `Form` to `.step()` for the common case.
- **Django-friendly abstraction**: each step is still treated as a `FormView`-like unit under the hood.
- **Advanced escape hatch**: pass a full `FormView` to `.step()` when a step needs extra configuration.
- **A way out**: a step can [escape the wizard](#escaping-the-wizard) entirely, redirecting the user elsewhere mid-flow.

For a runtime-level view of how the pieces fit together, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Core API shape (early)

From the prototype examples, flow construction follows this style:

```python
signup_wizard = (
    wizard.step(FirstForm)
    .step(SecondForm)
    .branch(
        condition(
            is_this,
            (
                wizard.step(AForm)
                .step(BForm)
            ),
        ),
        condition(is_that, some_other_wizard),
        default=FallbackForm,
    )
    .step(FinalForm)
)
```

This reads like a flow graph rather than a list of ad hoc callbacks.

Wizard declarations should use this parenthesized, one-builder-call-per-line
style throughout tests and documentation. Even short one-step examples should
prefer the same shape so wizard declarations remain visually consistent as they
grow.

### Builder calls are immutable (ORM-style)

`Wizard()` is intended to behave like Django `QuerySet` chaining: each call to
`.step()` or `.branch()` returns a **new wizard instance** instead of mutating
the existing one in place.

That makes it safer to define reusable bases and derive variants without
unexpected side effects:

```python
base_wizard = (
    wizard.step(AccountForm)
)

staff_wizard = base_wizard.step(InternalReviewForm)
customer_wizard = base_wizard.step(ProfileForm)
```

In the example above, `base_wizard` still contains only `AccountForm`, while
`staff_wizard` and `customer_wizard` each represent their own extended flow.

### `WizardViewSet.get_wizard()` can be dynamic per request

You can still declare a static class-level wizard when that is enough:

```python
class SignupWizardViewSet(WizardViewSet):
    wizard = onboarding_wizard
```

But the viewset can also provide a request-aware `get_wizard()` hook that
builds or selects the wizard at runtime. `get_wizard()` is called with the
`BoundWizard` for the current request, so you can read prior wizard state to
shape later steps:

```python
class SignupWizardViewSet(WizardViewSet):
    def get_wizard(self, bound_wizard):
        flow = wizard.step(AccountStepView)

        if self.request.user.is_staff:
            flow = flow.step(InternalReviewStepView)
        else:
            flow = flow.step(ProfileStepView)

        return flow.step(ConfirmStepView)
```

When `get_wizard()` returns a plain `Wizard`, the viewset configures it with
defaults before executing it.

This allows flow shape to change by tenant, permissions, feature flags, locale,
or any other request context, while keeping the same `WizardViewSet` entry
point.

### `.step()` accepts either a `Form` or a `FormView`

The default, easy case is to pass a Django `Form` directly:

```python
signup_wizard = (
    wizard.step(AccountForm)
    .step(ProfileForm)
    .step(ConfirmForm)
)
```

In that case, Gandalf automatically generates the corresponding `FormView` under the hood for you.

The important idea is the illusion: the `FormView` handling a step is not operating on the original incoming request unchanged. Instead, the wizard prepares a request object for that step so the view experiences what looks like an ordinary Django request/response cycle.

In other words, the step-level `FormView` should still be able to behave as if it lives in normal Django control flow. The wizard maintains that illusion by shaping the request so the step can keep its normal assumptions, while Gandalf itself handles the extra bookkeeping needed to move through a multi-step tree.

That illusion is where a lot of the power comes from: because the wizard owns the transformed request/response boundary, it can inspect, augment, and process those step interactions as the flow progresses without forcing each `FormView` to understand wizard mechanics directly.

When a step `FormView` chooses to return its own `HttpResponse`, the default behavior should still be that the `WizardViewSet` swallows that response and decides what to do from the status code. Gandalf stores raw submissions, then replays those submissions through the step `FormView`s in order. A `200 OK` response is treated as the first step that needs user attention, while a redirect response is treated as a successful outcome and traversal continues to the next step.

That default can still be overridden on a per-step basis when a particular step needs different semantics, but the out-of-the-box rule should be that Gandalf remains in control of the boundary and interprets the step response rather than passing it straight through unchanged.

Crucially, the wizard context is still available to the step view when it needs it. Even though the request seen by the step is a wizard-shaped request, `self.request.wizard` is still present, so an explicit `FormView` can tell that it is running inside Gandalf and can inspect wizard state when that is useful.

You only need to provide a full `FormView` yourself when you want extra per-step configuration, such as custom `get_initial()`, `form_valid()`, or other view-level behavior.

```python
from django.views.generic.edit import FormView


class AccountStepView(FormView):
    form_class = AccountForm

    def get_initial(self):
        return {"email": self.request.user.email}


signup_wizard = (
    wizard.step(AccountStepView)
    .step(ProfileForm)
    .step(ConfirmForm)
)
```

`.step()` can also accept another `Wizard`, which makes reusable subflows easy
to compose inline:

```python
address_flow = (
    wizard.step(AddressForm)
    .step(PostcodeLookupForm)
)

checkout_wizard = (
    wizard.step(CustomerForm)
    .step(address_flow)
    .step(ConfirmForm)
)
```

So the intended progression is:

- start with plain `Form`s for the common case,
- let Gandalf create the `FormView`s automatically,
- and only reach for a custom `FormView` when a step needs more configuration.

#### What's automatic when you bring your own `FormView`

When Gandalf needs to recover a completed step's `cleaned_data` — for
`MergeCleanedData`, `request.wizard.path.form.cleaned_data`, or any other
context-aware read — it does so by driving the step's `FormView` through its
public composition API. That means the following overrides on your `FormView`
are honored automatically:

- `form_class` (static attribute)
- `get_form_class()` (dynamic form-class selection)
- `get_form_kwargs()` (extra kwargs like `user=self.request.user` or
  `instance=obj`)
- `get_initial()`, `get_prefix()`

What's not automatic, because `.form` recovers cleaned data without running
the full dispatch pipeline:

- Side effects or data transformations performed in `form_valid()` — Gandalf
  reads `cleaned_data` straight from `form.is_valid()`, not from anything
  `form_valid()` does to it.
- Overrides of `post()`, `dispatch()`, or `setup()` that change how the
  request flows through the view.
- `FormView`s that return non-redirect responses on success.

The recovered request also uses the *current* request — so
`self.request.user` reflects whoever is currently driving the wizard, not
necessarily whoever originally submitted the step (relevant only for flows
where one user edits another's run).

### Why standalone `FormView` + wizard step reuse matters

One practical payoff of this design is that a configured `FormView` can be
reused in two contexts:

1. as a step inside a wizard flow, and
2. as a normal standalone Django view outside any wizard.

That lets teams keep form behavior in one place instead of duplicating it for
“create in wizard” vs “edit later” screens.

For example, imagine onboarding captures a billing profile in a multi-step
wizard. Later, users can edit that same billing profile from account settings.

```python
from django.views.generic.edit import FormView


class BillingProfileStepView(FormView):
    form_class = BillingProfileForm
    template_name = "account/billing_profile_form.html"

    def get_initial(self):
        initial = super().get_initial()
        customer = getattr(self.request.user, "customer", None)
        if customer:
            initial["company_name"] = customer.company_name
            initial["vat_id"] = customer.vat_id
        return initial


onboarding_wizard = (
    wizard.step(AccountForm)
    .step(BillingProfileStepView)  # same configured view
    .step(ConfirmForm)
)


class BillingProfileEditView(BillingProfileStepView):
    """Standalone edit screen reusing the same form/view configuration."""
```

In this setup, validation rules, initial-data behavior, template choice, and
any custom view hooks live in one shared step view. The wizard gains that
behavior during onboarding, while the account settings page reuses it later
without a separate implementation.

### `WizardViewSet.template_name` is applied to auto-generated step `FormView`s

When a step is declared with a plain `Form`, Gandalf generates the step
`FormView` and lets the viewset-level `template_name` control which template it
renders:

```python
class SignupWizardViewSet(WizardViewSet):
    template_name = "signup/step.html"
    wizard = (
        wizard.step(AccountForm)
    )
```

If you pass your own `FormView` to `.step()`, that step keeps its own
`template_name` instead of inheriting the one from the `WizardViewSet`:

```python
from django.views.generic.edit import FormView


class ProfileStepView(FormView):
    form_class = ProfileForm
    template_name = "signup/profile_step.html"


class SignupWizardViewSet(WizardViewSet):
    template_name = "signup/step.html"
    wizard = (
        wizard.step(AccountForm)
        .step(ProfileStepView)
    )
```

In that example, `AccountForm` is rendered with `signup/step.html` because
Gandalf generated the step `FormView`, while `ProfileStepView` is rendered with
`signup/profile_step.html` because the step supplied its own `FormView`.

The same idea applies more generally to `FormView` behavior on the
`WizardViewSet`. If Gandalf is generating the step `FormView` for you, methods
defined on the `WizardViewSet` can act as the corresponding `FormView` methods
for that generated step view.

For example, a viewset-level `get_context_data()` can be used by the
auto-generated `FormView`:

```python
class SignupWizardViewSet(WizardViewSet):
    template_name = "signup/step.html"
    wizard = (
        wizard.step(AccountForm)
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product_name"] = "Gandalf Pro"
        return context
```

That inheritance only applies when Gandalf is generating the step view. If you
pass an explicit `FormView` to `.step()`, Gandalf uses that `FormView` as-is
instead of taking the corresponding method from the `WizardViewSet`:

```python
from django.views.generic.edit import FormView


class AccountStepView(FormView):
    form_class = AccountForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product_name"] = "Step-specific value"
        return context


class SignupWizardViewSet(WizardViewSet):
    template_name = "signup/step.html"
    wizard = (
        wizard.step(AccountStepView)
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product_name"] = "Viewset value"
        return context
```

In that case, `AccountStepView.get_context_data()` is the method that runs for
that step, because the user-supplied `FormView` always takes precedence over
the auto-generated one.

Step templates need no wizard-specific markup — a plain Django form template
works as-is. Gandalf derives the user's position from stored state on every
request, so unlike `django-formtools` there is no management form to include
and no step bookkeeping travels in the POST body:

```django
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
</form>
```

### Every step is named; `.step()` can also carry arbitrary context

Steps are addressed by URL, so every step needs a name. The canonical
spelling is the `name=` keyword:

```python
signup_wizard = (
    wizard.step(AccountForm, name="account")
    .step(ProfileForm, name="profile")
    .step(ConfirmForm, name="confirm")
)
```

`name="account"` is shorthand for `context={"step_name": "account"}` — the
name lives in the step's context like any other metadata, and the default
`StepNameRouter` turns it into the step's URL segment. The `named()` helper
(`.step(named("account", AccountForm))`) is an equivalent older spelling.

Step declarations can also include a `context` dict for any other metadata
that belongs to the step definition rather than the submitted form data.
That metadata is exposed again on the runtime tree as `node.context`, so a
project can build its own lookup helpers and conventions on top of the tree:

```python
signup_wizard = (
    wizard.step(AccountForm, name="account", context={"analytics_key": "signup-account"})
    .step(ProfileForm, name="profile", context={"analytics_key": "signup-profile"})
    .step(ConfirmForm, name="confirm", context={"analytics_key": "signup-confirm"})
)
```

### Additional configuration follows the same pattern

Calling `.configure(...)` is optional and only needed when overriding default runtime configuration. A `WizardViewSet` can receive a plain `Wizard` declaration and will configure it automatically with defaults.

In the common case, declare the wizard steps and rely on Gandalf defaults (for example, for generating step `FormView` classes from plain forms).

When you do need to override a default, pass it as a keyword to `.configure(...)`. For example, file-storage customization:

```python
signup_wizard = (
    wizard.step(AccountForm)
    .configure(file_storage_class=TenantFileStorage)
)
```

The same pattern applies to every other touch point on `ConfiguredWizard` (`form_view_factory`, `cursor_walker_class`, `step_dispatcher_class`, `state_serializer_class`, `step_router_class`). That keeps the mental model consistent:

- `Wizard()` remains focused on step/branch declaration,
- `configure(...)` receives configuration touch points,
- each touch point has a sensible default so you only configure what you need,
- and future configuration hooks should follow this same `configure(...)` pattern instead of introducing unrelated mechanisms.

### Storage

Wizard state is backed by a session storage class. Gandalf provides
`SessionStorage` as its only built-in storage class, and users may pass a
compatible custom session-backed class as `WizardViewSet.storage_class`:

```python
class SignupWizardViewSet(WizardViewSet):
    storage_class = CustomSessionStorage
```

Storage is the one touch point that lives on the viewset rather than on
`configure(...)`, because it has to exist *before* the wizard does: the
viewset builds the `BoundWizard` first, then hands it to `get_wizard()` so a
dynamic wizard can read stored state to shape itself. A wizard therefore
cannot supply the storage used to resolve it, and
`Wizard().configure(storage_class=...)` raises `ImproperlyConfigured`
pointing here rather than silently doing nothing.

Gandalf does not ship a `CookieStorage` option. Wizard state can include enough
structured form data and runtime metadata that cookie-backed storage is too
size-constrained.

`SessionStorage` stores plain JSON-compatible data in `request.session`, not
pickled Python objects or live runtime objects. Django's configured session
backend then handles the actual serialization and persistence.

A run's answers live there only while it is in progress. Finishing a run
replaces them with a completion marker (see
[Completion](#completion-done-runs-exactly-once)), and asking for a run the
session does not hold raises `gandalf.storage.RunNotFound`, which the viewset
turns into a `run_unavailable()` response.

### File uploads

Wizard steps may declare `forms.FileField` and friends. Uploaded files cannot
live in `request.session` (session backends serialize to JSON or pickled bytes,
neither is appropriate for binary blobs), so Gandalf persists them through a
companion `WizardFileStorage` class. The wizard state in the session carries
only string refs (a per-field dict capturing the storage key plus original
`name`/`content_type`/`size`/`charset`); the actual bytes live behind whatever
Django `Storage` backend you configure.

The default `file_storage_class` wraps `django.core.files.storage.default_storage`
and writes under a `gandalf/<run_id>/` prefix. Swap it via
`Wizard.configure(file_storage_class=...)` — the same shape as `storage_class`.
For example, to keep wizard uploads in their own backend (S3, encrypted store,
per-tenant location), subclass `WizardFileStorage` and point its `backend` at
a different `Storage` instance:

```python
from django.core.files.storage import FileSystemStorage
from gandalf.wizard import WizardFileStorage


class TenantFileStorage(WizardFileStorage):
    def __init__(self):
        super().__init__(backend=FileSystemStorage(location="/var/tenant-uploads"))


wizard = wizard.configure(file_storage_class=TenantFileStorage)
```

**Replay semantics.** `CursorWalker.visit_step` re-runs form validation on
every replay. For file steps it opens each stored ref via
`file_storage.open(ref)`, rebuilds an `InMemoryUploadedFile` with the original
filename, content-type, size, and charset, then injects it into `request.FILES`
before dispatching the step view. Validators that inspect `uploaded_file.content_type`
(image-only forms, MIME sniffing) see the same value on replay as on the
original POST.

**Edit semantics.** `bound_wizard.render_edit(...)` merges the opened files
into the form's `initial`, so a `ClearableFileInput` widget displays the
existing upload alongside the rest of the prior submission. `bound_wizard.edit`
respects keep-vs-replace per field: a field with no new upload preserves its
old ref; a field with a new upload saves the new file and deletes the old one
from storage in a single step.

**Cleanup.** `WizardViewSet` invokes `bound_wizard.cleanup_files()` automatically
after `done()` returns — successful completion wipes everything under the
run's prefix. Abandoned runs (the user closes the tab before finishing) leave
their uploads in place; a periodic TTL sweep over the storage prefix is future
work. If you need files to survive past `done()` (e.g. an asynchronous job
that consumes them after the response renders), override `_finish()` or
arrange the work to capture what it needs synchronously before returning.

### Branching from the beginning

You can also branch immediately based on runtime context (for example, the current day of the week):

```python
from datetime import date


def is_weekend(_request):
    return date.today().weekday() >= 5


weekday_or_weekend_wizard = (
    wizard.branch(
        condition(is_weekend, WeekendForm),
        default=WeekdayForm,
    )
    .step(CommonDetailsForm)
    .step(ConfirmationForm)
)
```

---

## Back-navigation: editing earlier steps

A wizard often needs an "edit" affordance — a review screen with links back to
each prior step, or a sidebar that lets the user revisit any completed section.
Because every step has its own URL, the edit affordance is just a link: a
completed step's URL renders it pre-filled, and posting the changed answer to
that URL applies a transactional edit.

A review template wires per-step edit links from the runtime path:

```html
<h1>Review your details</h1>
<ul>
  {% for step in wizard.path %}
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

The per-step edit form is the ordinary step form — it posts back to its own
step URL, so no marker fields or wizard-specific markup are needed. A valid
edit redirects back to wherever the wizard's cursor is (usually the summary);
an invalid edit re-renders at the same URL with errors and stored state
untouched.

Programmatically, the same operations live on `BoundWizard`:

- `render_edit(**context)` — GET-side. Resolves the targeted runtime step via
  context matching, then dispatches its form view with the stored submission
  pre-filled as `initial`.
- `edit(submission, **context)` — POST-side and transactional. The new
  submission is validated against the target step first: if it fails, the
  rendered error response is returned and stored state is left untouched. On
  success the submission is spliced into the runtime tree, the cursor walker
  re-validates the run, and the rebuilt state is persisted; `edit()` returns
  `None`.

### The re-entrant summary pattern

The edit operations exist to serve one very common flow: a wizard that runs
linearly to a summary screen where every answer has a "change" link. The
promise is that changing an answer costs the user exactly as much of the
wizard as the change actually invalidates — usually nothing:

- **Trivial edit** — the new answer validates and no branch re-routes. Every
  other stored answer still validates, so the first unanswered step is the
  summary itself and the edit POST lands the user straight back on it. There
  is no step pointer to rewind and no re-cycling through completed steps;
  position is always derived from state.
- **Diverting edit** — the new answer flips a branch arm (or makes a
  dependent step's stored data invalid). The cursor parks at the first step
  that genuinely needs attention; the user answers only those steps, and the
  wizard fast-forwards through every still-valid downstream answer back to
  the summary.
- **Invalid edit** — rejected outright. The error render comes back, stored
  state is untouched, and nothing downstream is lost to a typo.
- **Flip-flop** — answers for a de-selected branch arm are kept as dormant
  memory. Changing account type from business to personal and back restores
  the business answers (re-validated like any stored data) instead of
  re-asking them.

Under the hood this works because state is a full-tree mirror with holes
rather than a truncate-on-change prefix: after `edit()` splices the new
submission into the runtime tree, `CursorWalker` re-validates entries up to
the first missing or no-longer-valid answer, then carries everything after it
verbatim. Branch entries are stored per arm (`{"branch": {"0": [...],
"default": [...]}}`), so the active arm is still re-derived from your
predicates on every walk while inactive arms simply wait. A stored answer
that no longer validates keeps its data and replays as the errored form, so
the user corrects it rather than retyping it.

Some practical caveats:

- Dormant arms live in the session until the run completes, so state grows
  by the size of the abandoned arms.
- Arm identity is positional (declaration order), so a dynamic
  `get_wizard()` that reorders branch arms between requests will
  misattribute dormant memory — the same positional-alignment rule that
  already applies to steps.
- Preservation applies to *every* still-valid answer, including a
  confirmation step that was already answered: after a diverting edit the
  stored confirmation stays confirmed, and once the diverted steps are
  answered the wizard completes without re-showing it. If your flow
  requires re-confirmation after changes, model that explicitly (keep the
  confirmation as the final unanswered step until the user truly submits
  it, or make its validation depend on the answers it confirms).
- While a divert is in progress, `bound_wizard.path` includes preserved
  downstream steps that hold data but have not been re-validated on the
  current walk — treat mid-run `path` reads as "answered", not
  "confirmed-valid". Steps inside branch regions that cannot be reached
  yet are invisible to `path` and `find_step` until the answers they
  depend on exist — which is also why branch predicates can dereference
  prior answers unconditionally: they only ever run behind a
  fully-validated prefix.

## Step URLs

Every step is addressed by its own URL. Steps are named at declaration time
(`.step(..., name=...)`, or the `named()` helper, or a
`context={"step_name": ...}` entry), the name becomes a URL segment, and the
name is resolved back to a step by context lookup on every request. The bare
run URL stays canonical and the cursor keeps sole authority over position; a
step URL is a *claim* that either resolves or redirects to where the wizard
actually is. Gandalf takes an opinionated stance here — unlike some wizard
tooling there is no unrouted mode, so every step must carry a routable name;
the viewset raises `ImproperlyConfigured` at request time for a wizard with
an unnamed step.

A wizard needs three URL patterns (start, bare run URL, step URL). Set
`url_name` and mount `urls()` to get them, plus the reverse hooks, for free:

```python
from django.http import HttpResponse
from django.urls import include, path

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class OnboardingViewSet(WizardViewSet):
    url_name = "onboarding"
    template_name = "onboarding/step.html"
    wizard = (
        Wizard()
        .step(AccountForm, name="account")
        .step(ProfileForm, name="profile")
        .step(ReviewForm, name="review")
    )

    def done(self, bound_wizard):
        return HttpResponse("Thanks!")


urlpatterns = [
    path("onboarding/", include(OnboardingViewSet.urls())),
]
```

`urls()` publishes `onboarding` (start), `onboarding-run`
(`onboarding/<uuid:run_id>/`), and `onboarding-step`
(`onboarding/<uuid:run_id>/<slug:gandalf_step>/`). The mount prefix can
capture kwargs of its own — `path("<slug:team>/onboarding/",
include(OnboardingViewSet.urls()))` — and the default reverse hooks
forward them into every redirect via `get_url_kwargs()`, which returns
the current request's captured kwargs minus the wizard-owned `run_id` /
`gandalf_step`. For a custom URL scheme (different converters, reverse
context not captured in the URL), write the patterns yourself and
override `get_wizard_url(run_id)` / `get_step_url(run_id, step_segment)`
instead of setting `url_name`.

The request semantics:

- **GET the cursor's step URL** → renders the form (with errors if the
  stored answer no longer validates).
- **GET a completed step's URL** → renders it pre-filled — this *is* the
  edit affordance; summary "change" links are just step URLs. "Completed"
  means answered on a run still in progress; once the *run* finishes, every
  one of its URLs goes to `run_unavailable()` instead.
- **GET anything else** — unknown, not yet reached, or parked in a dormant
  arm — → redirects to the cursor's URL. A stale "change" link after a
  diverting edit snaps back to the current step instead of erroring.
- **POST to the cursor's step URL** → a plain submission; **POST to a
  completed step's URL** → a transactional edit; **POST to anything else**
  → redirects to the cursor without storing the payload or its uploads.
  A submission from a stale tab can therefore never land on the wrong step.
- **Successful POSTs redirect** (POST → redirect → GET), so refreshing
  never re-submits — even after an invalid submission, which persists and
  re-renders with errors on the following GET. A rejected edit stays a
  direct render so nothing about it is persisted.
- **The bare run URL redirects** to the cursor's step URL when that step is
  routable, and fires `done()` when the run is complete — once, after which
  the run is finished and the URL resolves to `run_unavailable()`.

Because history then contains only GETs of step URLs, the browser back
button works naturally: going back shows an earlier answer pre-filled, and
re-submitting it is just an edit that returns you to the cursor.

For an explicit in-page back link, the wizard object exposes two lazy
navigation properties, reachable from any step template via
`request.wizard`:

- `request.wizard.back_url` — the previous active-route step's URL
  (branch-aware: on a branch arm's first step it points at the step before
  the branch). `None` on the first step, so templates can show the link
  conditionally.
- `request.wizard.run_url` — the bare run URL, which redirects to the
  current step; useful as a "cancel, return to where I was" affordance on
  edit pages.

```django
{% if request.wizard.back_url %}
  <a href="{{ request.wizard.back_url }}">Back</a>
{% endif %}
```

Going back is non-destructive by construction: nothing after the step you
return to is discarded, and re-submitting an unchanged answer is a trivial
edit that redirects straight back to the cursor.

Like every other touch point, the router is pluggable — subclass
`StepNameRouter` (or supply your own with `resolve(url_kwargs)`,
`reverse(step)`, and `clean_url_kwargs(url_kwargs)`) via
`Wizard.configure(step_router_class=...)` to route on a different context
key or a composite lookup:

```python
from gandalf.wizard import StepNameRouter, Wizard


class SectionRouter(StepNameRouter):
    context_key = "section"


wizard = (
    Wizard()
    .step(AccountForm, context={"section": "account"})
    .step(ProfileForm, context={"section": "profile"})
    .configure(
        template_name="onboarding/wizard.html",
        step_router_class=SectionRouter,
    )
)
```

---

## Completion: `done()` runs exactly once

A run finishes the first time the wizard is walked and every slot is
satisfied. `done()` is called there, its files are cleaned up, and the run is
then **retired**: its answers are dropped and a small completion marker takes
their place.

That marker is what makes the guarantee enforceable. Once a run is retired,
every request for it — the bare run URL, any step URL, GET or POST — is
answered by `run_unavailable()` without ever reaching the wizard. So:

- a stale tab re-POSTing the final form cannot finalize a second time,
- a bookmarked completion page cannot re-charge a card on refresh,
- a completed run's step URLs stop offering edits, because there is nothing
  left to edit.

Put side effects in `done()` and they happen once, full stop.

```python
class CheckoutWizardViewSet(WizardViewSet):
    url_name = "checkout"

    def done(self, bound_wizard):
        order = create_order(MergeCleanedData().reduce(bound_wizard.path))
        charge(order)                      # happens exactly once
        return redirect("order-detail", pk=order.pk)
```

The marker is written *after* `done()` returns, so a `done()` that raises
leaves the run intact and resumable rather than stranded half-finished. Retired
runs are pruned to the most recent `SessionStorage.max_completed_runs` (25 by
default), so completed runs cannot grow a session without bound.

### `run_unavailable()`

One hook answers every request that cannot be run, with `reason` saying which:

| `reason` | Meaning |
| --- | --- |
| `"completed"` | the run finished; `done()` has already fired for it |
| `"unknown"` | no such run — never started, obliterated, or lost with an expired session |

The default redirects to the wizard's start URL, so a refreshed completion page
quietly begins a fresh run rather than erroring. Override it to say something
more specific:

```python
class CheckoutWizardViewSet(WizardViewSet):
    def run_unavailable(self, bound_wizard, reason):
        if reason == "completed":
            return redirect("order-thanks")
        raise Http404("That checkout has expired.")
```

Because the hook covers unknown runs too, a tampered or long-bookmarked run URL
is an ordinary redirect rather than a `KeyError`.

### Completion and dynamic wizards

A dynamic `get_wizard()` is built from stored state, so the tree resolved at
the start of a POST predates that POST's own submission. Gandalf re-derives the
wizard after a submission is stored and judges completion against *that* tree —
otherwise answering the step that decides the shape (a count, a branch key)
would look like finishing a wizard whose generated steps do not exist yet.
Nothing is required of you here; it is why a `get_wizard()` that reads
`bound_wizard.get_state()` behaves as written.

---

## Escaping the wizard

Sometimes an answer means the user should not be in the wizard any more. An
email lookup finds an existing account, so the right destination is the login
page, not the next step. A step raises an escape to say so:

```python
from django import forms
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

The user is redirected to `reverse("login")` instead of moving on. Escapes are
ordinary exceptions, in the spirit of `Http404` and `PermissionDenied`, so they
can be raised from wherever the decision is naturally made — a plain form's
`clean()` as above, or a step `FormView`'s `form_valid()` when the check needs
the view:

```python
from django.urls import reverse
from django.views.generic.edit import FormView

from gandalf.escapes import Obliterate


class CancelSignupStepView(FormView):
    form_class = CancelSignupForm
    template_name = "signup/step.html"

    def get_success_url(self):
        return self.request.path

    def form_valid(self, form):
        if form.cleaned_data["cancel"]:
            raise Obliterate(reverse("home"))
        return super().form_valid(form)
```

### What happens to the run

Which exception you raise decides what the user comes back to. All three take
the same arguments as `django.shortcuts.redirect`, so a URL, a named route with
arguments, or a model with `get_absolute_url()` all work.

| Exception | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded, with any files it uploaded | the same step, unanswered |
| `Advance` | stored, and satisfies the step | the next step |
| `Obliterate` | destroyed with the rest of the run | a fresh run |

`Park` treats the escape as a detour the step never completed — right for the
email lookup above, where the address was a question rather than an answer.
`Advance` is for a step that genuinely finished, when the user should be sent
elsewhere before carrying on. `Obliterate` ends the run: state and uploaded
files are both removed.

`Escape` is the base class, so `except Escape` catches all three, and you can
subclass any of them to carry extra context. Raising `Escape` itself is an
error — it names no disposition for the run, so the viewset rejects it with
`ImproperlyConfigured`.

### Escapes and re-entrancy

A wizard re-validates every stored answer on each request, so an answer stored
by `Advance` raises its escape again on every later walk. Those replays only
mark the step satisfied: the redirect is issued for the submission the user
actually made, and never again. Two consequences are worth knowing:

- **Editing a completed step never escapes.** An escape raised while validating
  an edit means the step is satisfied and the edit is stored, so the flow
  continues as normal. Escapes are for the step the user is on.
- **`Advance` on the final step defers `done()`.** The escape's redirect is
  returned rather than the completion response; the run is complete but not
  yet finished, so returning to it runs `done()` then — and only then, since
  finishing the run retires it.

One caveat on reading an escaped answer afterwards: a step that escaped from
`clean()` still reconstructs via `.form`, but its `cleaned_data` holds only the
fields cleaned before the raise. Raise from `form_valid()` instead when the
answer needs to stay wholly readable in `done()`.

---

## `django-formtools` to `django-gandalf` examples

These examples show equivalent flow setups, then how `django-gandalf` is intended to express the same thing with chained, declarative syntax.

> Note: `django-gandalf` is still early/prototypal, so these are illustrative API examples.

### 1) Linear 3-step wizard

#### formtools style

```python
from formtools.wizard.views import SessionWizardView

class CheckoutWizard(SessionWizardView):
    form_list = [CustomerForm, AddressForm, ConfirmForm]
```

#### gandalf style

```python
checkout_wizard = (
    wizard.step(CustomerForm, name="customer")
    .step(AddressForm, name="address")
    .step(ConfirmForm, name="confirm")
)
```

What improves here:

- Same readability for linear flows.
- Keeps the same API style you will use for branching and nested flows.

### 2) Conditional step inclusion

#### formtools style (`condition_dict`)

```python
from formtools.wizard.views import SessionWizardView


def needs_vat(wizard):
    cleaned = wizard.get_cleaned_data_for_step("company") or {}
    return cleaned.get("is_business")


class CompanyWizard(SessionWizardView):
    form_list = [
        ("company", CompanyForm),
        ("vat", VATForm),
        ("summary", SummaryForm),
    ]
    condition_dict = {"vat": needs_vat}
```

#### gandalf style

```python
def needs_vat(request):
    company_step = request.wizard.find_step(name="company")
    return company_step.form.cleaned_data.get("is_business")


company_wizard = (
    wizard.step(CompanyForm, name="company")
    .branch(
        condition(needs_vat, VATForm),
        default=None,  # skip VAT if condition is false
    )
    .step(SummaryForm, name="summary")
)
```

`BoundWizard.find_step(**context)` returns the matching `RuntimeStep` from the active runtime tree; `name=` is shorthand for the `step_name` context key, mirroring `.step(..., name=...)` (`filter_steps` accepts it too). Branch conditions run after the prior steps have completed, so reading `step.form.cleaned_data` from there is safe.

What improves here:

- Conditional routing is represented directly in the flow tree.
- No step-name-to-condition lookup table; condition and target live together.

### 3) Tree-like branching with reusable subflows

#### formtools style (custom step navigation)

```python
from formtools.wizard.views import SessionWizardView

class OnboardingWizard(SessionWizardView):
    form_list = [AccountTypeForm, BizAForm, BizBForm, PersonAForm, FinalForm]

    def get_next_step(self, step=None):
        # custom branching logic based on cleaned step data
        # ... return the next step name dynamically
        ...
```

#### gandalf style

```python
business_flow = (
    wizard.step(BizAForm)
    .step(BizBForm)
)
personal_flow = (
    wizard.step(PersonAForm)
)

onboarding_wizard = (
    wizard.step(AccountTypeForm)
    .branch(
        condition(is_business_account, business_flow),
        default=personal_flow,
    )
    .step(FinalForm)
)
```

What improves here:

- Branch targets can be full reusable sub-wizards.
- Flow shape is explicit and visible in one declaration.
- Less bespoke navigation plumbing for tree-style journeys.

---

## How this is better for complex trees

Compared with traditional wizard configuration approaches, this style is designed to make complex flows easier to reason about because:

- flow shape is explicit in one declaration,
- nesting mirrors the real decision tree,
- conditions are attached directly to branches,
- and reusable sub-wizards reduce duplication across similar journeys.

In short: if your journey behaves like a tree, the API should look like a tree.

---

## Contributing

See `CONTRIBUTING.md` for local setup, workflow expectations, separated unit
and functional test commands, and commit message conventions.
