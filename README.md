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

### `WizardViewSet.get_wizard()` can be dynamic per request

You can still declare a static class-level wizard when that is enough:

```python
class SignupWizardViewSet(WizardViewSet):
    wizard = onboarding_wizard
```

But the viewset can also provide a request-aware `get_wizard()` hook that
builds or selects the wizard at runtime:

```python
class SignupWizardViewSet(WizardViewSet):
    def get_wizard(self):
        wizard = Wizard().step(AccountStepView)

        if self.request.user.is_staff:
            wizard = wizard.step(InternalReviewStepView)
        else:
            wizard = wizard.step(ProfileStepView)

        return wizard.step(ConfirmStepView)
```

You can also build a dynamic *range* of auto-generated steps from a previous
answer. For example, ask how many household members to collect, then append one
generated step per member:

```python
class HouseholdWizardViewSet(WizardViewSet):
    def get_wizard(self):
        wizard = Wizard().step(HouseholdCountForm)  # asks for `member_count`

        step_node = self.request.wizard.tree.step("household_count")
        step_count_data = step_node.cleaned_data if step_node and step_node.is_complete else {}
        member_count = int(step_count_data.get("member_count", 0) or 0)

        for index in range(1, max(member_count, 0) + 1):
            wizard = wizard.step(build_member_form_view(index))

        return wizard.step(ConfirmStepView)
```

This allows flow shape to change by tenant, permissions, feature flags, locale,
or any other request context, while keeping the same `WizardViewSet` entry
point.

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

The important idea is the illusion: the `FormView` handling a step is not operating on the original incoming request unchanged. Instead, the wizard prepares a request object for that step so the view experiences what looks like an ordinary Django request/response cycle.

In other words, the step-level `FormView` should still be able to behave as if it lives in normal Django control flow. The wizard maintains that illusion by shaping the request so the step can keep its normal assumptions, while Gandalf itself handles the extra bookkeeping needed to move through a multi-step tree.

That illusion is where a lot of the power comes from: because the wizard owns the transformed request/response boundary, it can inspect, augment, and process those step interactions as the flow progresses without forcing each `FormView` to understand wizard mechanics directly.

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

### Additional configuration follows the same pattern

Configuration for auto-generated step views is **optional** and follows the same inline constructor style as storage configuration.

You do not need to pass anything for this in the common case: Gandalf should provide a sensible default factory for generating step `FormView` classes from plain forms.

In other words, this:

```python
wizard = Wizard(storage_class=CookieStorage)
```

and auto FormView generation customization (when you need it) follows the same shape:

```python
wizard = Wizard(form_view_factory_class=CustomFormViewFactory)
```

Where `CustomFormViewFactory` is a class responsible for building the dynamic `FormView` class used when you call `.step(SomeForm)`.

```python
class CustomFormViewFactory:
    def build(self, form_class):
        class GeneratedFormView(FormView):
            def get_initial(self):
                initial = super().get_initial()
                initial["source"] = "custom-factory"
                return initial

        GeneratedFormView.form_class = form_class
        return GeneratedFormView
```

That keeps the mental model consistent:

- `Wizard(...)` receives configuration touch points inline,
- each touch point has a sensible default so you only configure what you need,
- those touch points control how step `FormView` classes are produced,
- and future configuration hooks should follow this same constructor-level pattern instead of introducing unrelated mechanisms.

### Storage backends

Wizard state will be backed by a storage object.

The intended built-in options are:

- `SessionStorage` (default),
- `CookieStorage`.

The intended configuration story is:

1. **Default behavior**: do nothing and use `SessionStorage`.
2. **Global setting** (Django settings):

   ```python
   GANDALF_WIZARD_STORAGE_CLASS = "gandalf.storage.CookieStorage"
   ```

3. **Per wizard**: pass a storage class when constructing the wizard.

   ```python
   from gandalf import Wizard
   from gandalf.storage import CookieStorage

   wizard = Wizard(storage_class=CookieStorage)
   ```

> This section describes the API direction; storage behavior internals are intentionally deferred.

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

### Tree-shaped runtime data contract

The *mechanics* of tracking the current step are an implementation detail.

The *behavior* is not.

Because Gandalf models the journey as a real tree, the runtime data contract
should also be shaped like a tree.

The intent is that Gandalf reevaluates the flow from the root on each
request/response cycle using the data it currently has.

That means the primary runtime object is not a flattened `data` dict. It is the
evaluated tree itself, with step results attached to the nodes that have run.

More concretely, `wizard.tree` should be a tree of `Step` nodes.

For example:

```python
business_flow = Wizard().step(BizDetailsForm).step(BizComplianceForm)
personal_flow = Wizard().step(ProfileForm)

onboarding_wizard = (
    Wizard()
    .step(AccountTypeForm)
    .branch(
        condition(is_business_account, business_flow),
        default=personal_flow,
    )
    .step(ReviewForm)
)
```

At runtime, the user should be able to inspect something conceptually like:

```python
request.wizard.tree
```

where each `Step` node represents one step in the declared flow and exposes the
runtime state for that step.

Conceptually:

```python
step = request.wizard.tree.step("account")
```

and a `Step` node can hold things like:

- the step name,
- its position in the tree,
- the underlying form class or `FormView` class,
- whether it is currently reachable,
- whether it has run,
- whether it completed successfully,
- any cleaned data produced by that step,
- validation errors for the most recent run,
- the request that was passed into that step view,
- the response returned by that step view,
- and any step-level metadata Gandalf records while executing the flow.

The important idea is that Gandalf is not just storing “form answers”.
It is capturing the execution of the flow step-by-step in a structure that
matches the declared tree.

So a node is not just a bag of cleaned data. It is the runtime record of:

- what step this was,
- what view handled it,
- what request/response interaction happened there,
- and what data or metadata was produced as a result.

That means the tree can be walked not only to inspect collected values, but
also to inspect how the wizard actually ran.

So if a user does this:

1. Completes `AccountTypeForm` with `account_type="business"`.
2. Completes `BizDetailsForm`.
3. Completes `BizComplianceForm`.
4. Goes back to `AccountTypeForm` and changes the answer to `account_type="personal"`.

then Gandalf should reevaluate the tree from the root using the new
`AccountTypeForm` answer.

That means:

- `BizDetailsForm` and `BizComplianceForm` are no longer on the current active path.
- The next step should now be `ProfileForm`, not `BizDetailsForm`.
- Any previously collected business-branch data can remain attached to those
  nodes in the tree as historical runtime state.
- Code consuming wizard state can walk the tree and decide for itself whether
  it wants current-path data, historical data, completed-node data, or some
  custom projection.

This keeps Gandalf honest about its core abstraction:

- the flow is declared as a tree,
- the runtime state is represented as a tree,
- and consumers derive whatever flattened view they need from that tree.

In other words, Gandalf should not force one canonical interpretation of “all
wizard data”. It should expose the shaped runtime structure and let callers
decide what data they want from each step.

That also means Gandalf does not need a separate result-building abstraction.

The tree-shaped runtime state is the source of truth, and code running at
`done()` time can walk that tree to derive whatever final payload it needs.

For example:

```python
class CheckoutWizardViewSet(WizardViewSet):
    wizard = checkout_wizard

    def done(self, wizard):
        customer = wizard.tree.step("customer")
        address = wizard.tree.step("address")

        create_order(
            email=customer.cleaned_data["email"],
            shipping_address={
                "line_1": address.cleaned_data["line_1"],
                "postcode": address.cleaned_data["postcode"],
            },
        )
```

If a project wants a flattened or transformed view of the data, it can build
that by traversing the tree itself. Gandalf only needs to guarantee that the
tree accurately represents what ran and what data each step produced.

For example, a project could flatten completed steps into a plain dict:

```python
def flatten_completed_steps(tree):
    flattened = {}

    for node in tree.walk():
        if not node.is_complete:
            continue

        if not node.cleaned_data:
            continue

        flattened[node.step_name] = node.cleaned_data

    return flattened


class CheckoutWizardViewSet(WizardViewSet):
    wizard = checkout_wizard

    def done(self, wizard):
        payload = flatten_completed_steps(wizard.tree)
        create_order_from_payload(payload)
```

That flattening logic belongs to the consumer, not to Gandalf itself, because
different projects may want different projections of the same tree.

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
    company = request.wizard.tree.step("company")
    cleaned = company.cleaned_data if company and company.is_complete else {}
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
        account = self.request.wizard.tree.step("account")
        account_data = account.cleaned_data if account and account.is_complete else {}
        return {
            "contact_email": account_data.get("email"),
            "country": account_data.get("country"),
        }


class ConfirmStepView(FormView):
    form_class = ConfirmForm

    def get_initial(self):
        account = self.request.wizard.tree.step("account")
        profile = self.request.wizard.tree.step("profile")
        account_data = account.cleaned_data if account and account.is_complete else {}
        profile_data = profile.cleaned_data if profile and profile.is_complete else {}
        return {
            "email": account_data.get("email"),
            "display_name": profile_data.get("display_name"),
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

With Gandalf, the easy case is still just `.step(MyForm)`. When a step needs more control, each explicit `FormView` can own its own `get_initial()` and still read prior wizard state via `self.request.wizard.tree`. That keeps the wiring local to the step, and views like `PortableProfileStepView` remain completely ordinary `FormView`s when you do not want any wizard-specific mechanics at all.

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
