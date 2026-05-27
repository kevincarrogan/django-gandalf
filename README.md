# django-gandalf

Declare branching Django form wizards as one chained tree.

Aimed at journeys that branch and nest — user-type splits, regional checks,
optional sub-flows, reusable fragments — rather than a list of steps with a
few skips.

## Relationship to `django-formtools`

[`django-formtools`](https://github.com/jazzband/django-formtools) is the
de-facto Django wizard library and the reference point for the side-by-side
examples below. `django-gandalf` is a separate library (not a fork, no
dependency) aimed at the branching, tree-shaped case. For linear flows,
formtools is the simpler choice.

## Linear wizard

```python
# formtools
from formtools.wizard.views import SessionWizardView


class SignupWizard(SessionWizardView):
    form_list = [("name", NameForm), ("email", EmailForm)]
    template_name = "signup/step.html"

    def done(self, form_list, **kwargs):
        payload = {}
        for form in form_list:
            payload.update(form.cleaned_data)
        create_account(**payload)
        return HttpResponse("Thanks!")
```

```python
# django-gandalf
from gandalf import wizard
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData


class SignupWizardViewSet(WizardViewSet):
    wizard = (
        wizard.step(NameForm)
        .step(EmailForm)
        .configure(template_name="signup/step.html")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        create_account(**payload)
        return HttpResponse("Thanks!")
```

`bound_wizard.path` is the chain of completed steps in execution order.
`MergeCleanedData` is a `tree.Reducer` that folds each step's
`form.cleaned_data` into one dict (last-write-wins). Subclass it or write
your own `tree.Reducer` for a different policy.

Gandalf isn't shorter for the linear case. The point is that the same
declaration grows into the branching shapes below without switching APIs.

## Branching wizard

```python
# formtools — branching via condition_dict + helper predicates
def is_business_account(wizard):
    cleaned = wizard.get_cleaned_data_for_step("account_type") or {}
    return cleaned.get("account_type") == "business"


def needs_international_checks(wizard):
    cleaned = wizard.get_cleaned_data_for_step("account_type") or {}
    return cleaned.get("region") == "international"


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

```python
# django-gandalf — same flow, explicit as a tree
international_wizard = (
    wizard.step(IntlTaxForm)
    .step(IntlKYCForm)
)
business_wizard = (
    wizard.step(BizDetailsForm)
    .step(BizComplianceForm)
    .branch(
        condition(needs_international_checks, international_wizard),
        default=None,
    )
)
personal_wizard = (
    wizard.branch(
        condition(needs_international_checks, international_wizard),
        default=None,
    )
    .step(ProfileForm)
)

onboarding_wizard = (
    wizard.step(AccountTypeForm)
    .branch(
        condition(is_business_account, business_wizard),
        default=personal_wizard,
    )
    .step(ReviewForm)
    .step(ConfirmationForm)
)
```

Branches are first-match-wins; only the matching arm is walked. Sub-wizards
are values you can name, reuse, and compose.

## Branching from the start

```python
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

## Immutable builder

```python
base_wizard = wizard.step(AccountForm)

staff_wizard = base_wizard.step(InternalReviewForm)
customer_wizard = base_wizard.step(ProfileForm)
# base_wizard still contains only AccountForm.
```

## Dynamic wizard per request

```python
class SignupWizardViewSet(WizardViewSet):
    def get_wizard(self, bound_wizard):
        signup_wizard = wizard.step(AccountStepView)
        if self.request.user.is_staff:
            signup_wizard = signup_wizard.step(InternalReviewStepView)
        else:
            signup_wizard = signup_wizard.step(ProfileStepView)
        return signup_wizard.step(ConfirmStepView)
```

## `.step()` accepts a `Form`, `FormView`, or `Wizard`

```python
# Plain Form — Gandalf generates the FormView.
wizard.step(AccountForm)

# Custom FormView — keeps its own template_name / get_initial / etc.
class AccountStepView(FormView):
    form_class = AccountForm

    def get_initial(self):
        return {"email": self.request.user.email}


wizard.step(AccountStepView)

# Sub-wizard — composable fragments.
address_wizard = wizard.step(AddressForm).step(PostcodeLookupForm)
checkout_wizard = (
    wizard.step(CustomerForm)
    .step(address_wizard)
    .step(ConfirmForm)
)
```

When the step is a plain `Form`, the auto-generated `FormView` inherits
`template_name`, `get_context_data()`, and other `FormView` hooks from the
`WizardViewSet`. A user-supplied `FormView` takes precedence over the
viewset's own.

When Gandalf recovers a completed step's `cleaned_data` (for
`MergeCleanedData`, `request.wizard.path.form.cleaned_data`, edits, replay),
it drives your `FormView` through its composition API. Honored:
`form_class`, `get_form_class()`, `get_form_kwargs()`, `get_initial()`,
`get_prefix()`. Not honored: side effects in `form_valid()`, overrides of
`post()` / `dispatch()` / `setup()`, non-redirect success responses.

## Step context and the `named` helper

```python
signup_wizard = (
    wizard.step(named("account", AccountForm))
    .step(named("profile", ProfileForm))
    .step(named("confirm", ConfirmForm))
)
```

`named("account", AccountForm)` is shorthand for
`(AccountForm, context={"step_name": "account"})`. Any dict works — pass
`context={"analytics_key": "..."}` — and it's exposed at runtime as
`node.context`.

## `.configure(...)`

```python
signup_wizard = (
    wizard.step(AccountForm)
    .configure(storage_class=CustomSessionStorage)
)
```

All runtime touch points are configured the same way:
`storage_class`, `file_storage_class`, `form_view_factory`,
`runtime_tree_builder_class`, `cursor_walker_class`, `step_dispatcher_class`,
`state_serializer_class`, `edit_resolver_class`. Each has a default;
configure only what you need.

## Storage

`SessionStorage` is the only built-in storage class. It writes
JSON-compatible data to `request.session` and relies on Django's session
backend for the actual serialization. Gandalf does not ship a
`CookieStorage` — wizard state is too large for cookies.

## File uploads

`forms.FileField` works. Bytes are persisted through `WizardFileStorage`
(wrapping `default_storage` under `gandalf/<run_id>/` by default); the
session carries only refs (key + original `name` / `content_type` / `size` /
`charset`). On replay, files are rebuilt as `InMemoryUploadedFile` and
injected into `request.FILES` before the step view runs — validators that
inspect `content_type` see the original value. `WizardViewSet` calls
`bound_wizard.cleanup_files()` after `done()` returns; abandoned runs leave
their uploads in place (TTL sweep is future work).

```python
class TenantFileStorage(WizardFileStorage):
    def __init__(self):
        super().__init__(backend=FileSystemStorage(location="/var/tenant-uploads"))


wizard = wizard.configure(file_storage_class=TenantFileStorage)
```

## Editing earlier steps

`BoundWizard` exposes two operations:

- `render_edit(**context)` — GET-side; renders the target step with the
  stored submission pre-filled as `initial`.
- `edit(submission, **context)` — POST-side; splices the new submission
  into the runtime tree, re-runs the cursor walker, and drops any
  downstream steps whose stored data no longer fits.

The default `StepNameEditResolver` keys off `context={"step_name": ...}` and
reads `gandalf_edit_step` from the query string or POST body:

```python
wizard = (
    Wizard()
    .step(named("account", AccountForm))
    .step(named("profile", ProfileForm))
    .step(named("review", ReviewForm))
    .configure(template_name="onboarding/wizard.html")
)
```

```django
<ul>
  {% for step in wizard.path %}
    <li>
      <a href="?gandalf_edit_step={{ step.declaration.context.step_name }}">
        Edit {{ step.declaration.context.step_name }}
      </a>
    </li>
  {% endfor %}
</ul>
```

Swap the resolver via `configure(edit_resolver_class=...)`. A resolver
needs `resolve(request)` returning a context dict or `None`, and
`clean_submission(submission)` to strip its own field(s) from POST data.

## Template tag

```django
{% load gandalf %}
<form method="post">
  {% csrf_token %}
  {% gandalf_management_form %}
  {{ form.as_p }}
</form>
```

`{% gandalf_management_form %}` injects wizard state when the template is
rendered inside a wizard step; no-op otherwise.

## More

- [ARCHITECTURE.md](ARCHITECTURE.md) — runtime structure and data flow.
- [CONTRIBUTING.md](CONTRIBUTING.md) — local setup, tests, commit
  conventions.
