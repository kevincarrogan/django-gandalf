# django-gandalf

`django-gandalf` helps you declare **complex, tree-like Django form flows** as readable, composable code.

It is built for the point where your journey stops being a straight line and starts branching repeatedly:

- user type branches (business vs individual),
- regional branches (domestic vs international),
- nested compliance/risk sub-flows,
- optional setup paths,
- reusable path fragments shared across journeys.

Instead of stitching this together with scattered step conditions and navigation overrides, `django-gandalf` aims to let you describe the flow as one explicit tree.

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
business_flow = Wizard().step(BizDetailsForm).step(BizComplianceForm)
international_flow = Wizard().step(IntlTaxForm).step(IntlKYCForm)
personal_flow = Wizard().step(ProfileForm)

onboarding_wizard = (
    Wizard()
    .step(AccountTypeForm)
    .branch(
        condition(is_business_account, business_flow),
        condition(needs_international_checks, international_flow),
        default=personal_flow,
    )
    .step(ReviewForm)
    .step(ConfirmationForm)
)
```

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

---

## Core API shape (early)

From the prototype examples, flow construction follows this style:

```python
wizard = (
    Wizard()
    .step(FirstForm)
    .step(SecondForm)
    .branch(
        condition(is_this, Wizard().step(AForm).step(BForm)),
        condition(is_that, some_other_wizard),
        default=FallbackForm,
    )
    .step(FinalForm)
)
```

This reads like a flow graph rather than a list of ad hoc callbacks.

### `.step()` accepts either a `Form` or a `FormView`

The default, easy case is to pass a Django `Form` directly:

```python
wizard = (
    Wizard()
    .step(AccountForm)
    .step(ProfileForm)
    .step(ConfirmForm)
)
```

In that case, Gandalf automatically generates the corresponding `FormView` under the hood for you.

You only need to provide a full `FormView` yourself when you want extra per-step configuration, such as custom `get_initial()`, `form_valid()`, or other view-level behavior.

```python
class AccountStepView(FormView):
    form_class = AccountForm

    def get_initial(self):
        return {"email": self.request.user.email}


wizard = (
    Wizard()
    .step(AccountStepView)
    .step(ProfileForm)
    .step(ConfirmForm)
)
```

So the intended progression is:

- start with plain `Form`s for the common case,
- let Gandalf create the `FormView`s automatically,
- and only reach for a custom `FormView` when a step needs more configuration.

### Branching from the beginning

You can also branch immediately based on runtime context (for example, the current day of the week):

```python
from datetime import date


def is_weekend(_request):
    return date.today().weekday() >= 5


weekday_or_weekend_wizard = (
    Wizard()
    .branch(
        condition(is_weekend, WeekendForm),
        default=WeekdayForm,
    )
    .step(CommonDetailsForm)
    .step(ConfirmationForm)
)
```

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
    Wizard()
    .step(CustomerForm)
    .step(AddressForm)
    .step(ConfirmForm)
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
    cleaned = request.wizard.data.get("company", {})
    return cleaned.get("is_business")


company_wizard = (
    Wizard()
    .step(CompanyForm)
    .branch(
        condition(needs_vat, VATForm),
        default=None,  # skip VAT if condition is false
    )
    .step(SummaryForm)
)
```

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
business_flow = Wizard().step(BizAForm).step(BizBForm)
personal_flow = Wizard().step(PersonAForm)

onboarding_wizard = (
    Wizard()
    .step(AccountTypeForm)
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

## Examples from this project

The `examples/` package demonstrates the intended declarative and chained style, split by concern (`core.py`, `forms.py`, `wizards.py`, and `views.py`).

In `django-formtools`, condition callables receive the wizard view. In Gandalf, condition callables intentionally receive the current `request`; when they need wizard state, they can read it from `request.wizard`.

### 1) A nested branch flow

```python
that_wizard = (
    Wizard()
    .step(BWizardFirstForm)
    .branch(
        condition(is_this, BWizardSecondForm),
        default=BWizardThirdForm,
    )
)

main_wizard = (
    Wizard()
    .step(FirstForm)
    .step(SecondForm)
    .step(ThirdForm)
    .branch(
        condition(is_this, Wizard().step(AWizardFirstForm).step(AWizardSecondForm)),
        condition(is_that, that_wizard),
    )
    .step(MyFinalForm)
)
```

Why this is important:

- A branch can point to a **single next step** or to a **full nested wizard**.
- Sub-flows are reusable objects, not one-off inline logic.
- The whole structure still reads top-to-bottom.

### 2) View-centric composition when you need more control

The default usage is still to pass plain `Form` classes to `.step()`. The examples below show the more configurable path, where you provide explicit `FormView`s because a step needs custom view logic.

Here is the more direct comparison for `get_initial()`-style wiring.

#### formtools style

```python
from formtools.wizard.views import SessionWizardView


class SignupWizard(SessionWizardView):
    form_list = [
        ("account", AccountForm),
        ("profile", ProfileForm),
        ("confirm", ConfirmForm),
    ]

    def get_form_initial(self, step):
        if step == "account":
            return {
                "email": self.request.user.email,
                "country": self.request.user.profile.country,
            }

        if step == "profile":
            account = self.get_cleaned_data_for_step("account") or {}
            return {
                "contact_email": account.get("email"),
                "country": account.get("country"),
            }

        if step == "confirm":
            account = self.get_cleaned_data_for_step("account") or {}
            profile = self.get_cleaned_data_for_step("profile") or {}
            return {
                "email": account.get("email"),
                "display_name": profile.get("display_name"),
            }

        return {}
```

#### gandalf style

```python
class AccountStepView(FormView):
    form_class = AccountForm

    def get_initial(self):
        return {
            "email": self.request.user.email,
            "country": self.request.user.profile.country,
        }


class ProfileStepView(FormView):
    form_class = ProfileForm

    def get_initial(self):
        account = self.request.wizard.data.get("account", {})
        return {
            "contact_email": account.get("email"),
            "country": account.get("country"),
        }


class ConfirmStepView(FormView):
    form_class = ConfirmForm

    def get_initial(self):
        account = self.request.wizard.data.get("account", {})
        profile = self.request.wizard.data.get("profile", {})
        return {
            "email": account.get("email"),
            "display_name": profile.get("display_name"),
        }


class PortableProfileStepView(FormView):
    form_class = ProfileForm

    def get_initial(self):
        return {
            "contact_email": self.request.user.email,
            "country": self.request.user.profile.country,
        }


view_based = (
    Wizard()
    .step(AccountStepView)
    .step(ProfileStepView)
    .step(ConfirmStepView)
)
```

With `formtools`, the initial-value logic tends to accumulate in one wizard-level method keyed by step name.

With Gandalf, the easy case is still just `.step(MyForm)`. When a step needs more control, each explicit `FormView` can own its own `get_initial()` and still read prior wizard data via `self.request.wizard`. That keeps the wiring local to the step, and views like `PortableProfileStepView` remain completely ordinary `FormView`s when you do not want any wizard-specific mechanics at all.

---

## How this is better for complex trees

Compared with traditional wizard configuration approaches, this style is designed to make complex flows easier to reason about because:

- flow shape is explicit in one declaration,
- nesting mirrors the real decision tree,
- conditions are attached directly to branches,
- and reusable sub-wizards reduce duplication across similar journeys.

In short: if your journey behaves like a tree, the API should look like a tree.

---

## Current status

This repository is currently an early prototype and API sketch.

- `examples/` demonstrates desired usage and composition style across dedicated modules.
- `implementation.py` contains rough implementation scaffolding and design notes.

Expect iteration on naming, validation, execution semantics, and Django integration details.

---

## Near-term direction

Planned focus areas include:

- robust flow tree data model,
- branch condition evaluation lifecycle,
- URL routing for named wizard steps,
- management form handling strategy,
- and end-to-end wizard execution through a `WizardViewSet` abstraction.

---

## Contributing

If you're exploring this project:

1. Start with the `examples/` package to understand the intended developer experience.
2. Use `implementation.py` to inspect current assumptions and gaps.
3. Open issues/PRs with concrete branch/tree use-cases—especially where existing wizard tooling becomes hard to maintain.
