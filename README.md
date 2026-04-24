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
international_flow = Wizard().step(IntlTaxForm).step(IntlKYCForm)
business_flow = (
    Wizard()
    .step(BizDetailsForm)
    .step(BizComplianceForm)
    .branch(
        condition(needs_international_checks, international_flow),
        default=None,
    )
)
personal_flow = (
    Wizard()
    .branch(
        condition(needs_international_checks, international_flow),
        default=None,
    )
    .step(ProfileForm)
)

onboarding_wizard = (
    Wizard()
    .step(AccountTypeForm)
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
        declared_wizard = Wizard().step(
            HouseholdCountForm,
            context={"step_name": "household_count"},
        )  # asks for `member_count`

        populated_wizard = declared_wizard.populate(self.request)
        household_count = populated_wizard.path.find_one_by_context(
            step_name="household_count",
        )
        household_count_data = (
            household_count.form.cleaned_data
            if household_count
            else {"member_count": 0}
        )
        member_count = int(household_count_data["member_count"])

        wizard = declared_wizard

        for index in range(member_count):
            wizard = wizard.step(build_member_form_view(index + 1))

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

When a step `FormView` chooses to return its own `HttpResponse`, the default behavior should still be that the `WizardViewSet` swallows that response and decides what to do from the status code. On a `POST`, a `200 OK` response should be treated as an error outcome for the step, while a redirect response should be treated as a successful outcome and hand control back to the wizard so normal progression can continue.

That default can still be overridden on a per-step basis when a particular step needs different semantics, but the out-of-the-box rule should be that Gandalf remains in control of the boundary and interprets the step response rather than passing it straight through unchanged.

Crucially, the wizard context is still available to the step view when it needs it. Even though the request seen by the step is a wizard-shaped request, `self.request.wizard` is still present, so an explicit `FormView` can tell that it is running inside Gandalf and can inspect wizard state when that is useful.

And if a step needs the untouched incoming request, that is preserved on the wizard itself as `self.request.wizard.original_request`. So the shaped request keeps the step experience ergonomic, while the original request remains available for cases where the distinction matters.

You only need to provide a full `FormView` yourself when you want extra per-step configuration, such as custom `get_initial()`, `form_valid()`, or other view-level behavior.

```python
from django.views.generic.edit import FormView


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

`.step()` can also accept another `Wizard`, which makes reusable subflows easy
to compose inline:

```python
address_flow = Wizard().step(AddressForm).step(PostcodeLookupForm)

checkout_wizard = (
    Wizard()
    .step(CustomerForm)
    .step(address_flow)
    .step(ConfirmForm)
)
```

So the intended progression is:

- start with plain `Form`s for the common case,
- let Gandalf create the `FormView`s automatically,
- and only reach for a custom `FormView` when a step needs more configuration.

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
    Wizard()
    .step(AccountForm)
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
    wizard = Wizard().step(AccountForm)
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
    wizard = Wizard().step(AccountForm).step(ProfileStepView)
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
    wizard = Wizard().step(AccountForm)

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
    wizard = Wizard().step(AccountStepView)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["product_name"] = "Viewset value"
        return context
```

In that case, `AccountStepView.get_context_data()` is the method that runs for
that step, because the user-supplied `FormView` always takes precedence over
the auto-generated one.

Whichever template is used for a wizard step should include the Gandalf
management form tag:

```django
{% load gandalf %}
<form method="post">
  {% csrf_token %}
  {% gandalf_management_form %}
  {{ form.as_p }}
</form>
```

`{% gandalf_management_form %}` reads the template context and checks for
wizard state on the request object. When the template is being rendered as part
of a wizard step, the tag automatically injects the wizard management form.

If no wizard is present (for example, `request.wizard` is not available in the
context), the tag is a no-op and safely renders nothing extra.

In practice, this behavior is mostly transparent: with a normal Gandalf wizard
setup, you can include the tag in your form template and usually do not need to
think about the implementation details.

### `.step()` can also carry arbitrary context

Step declarations can also include a `context` dict for metadata that belongs to
that step definition rather than to the submitted form data.

That metadata is exposed again on the runtime tree as `node.context`, so a
project can build its own lookup helpers and conventions on top of the tree.

For example, a project can choose to attach a step name explicitly:

```python
signup_wizard = (
    Wizard()
    .step(AccountForm, context={"step_name": "account", "analytics_key": "signup-account"})
    .step(ProfileForm, context={"step_name": "profile", "analytics_key": "signup-profile"})
    .step(ConfirmForm, context={"step_name": "confirm", "analytics_key": "signup-confirm"})
)
```

That keeps naming in user space instead of forcing Gandalf to define one
canonical global step-name mechanism for every project.

For the very common case where you only want to attach a `step_name`, Gandalf
should also provide a helper like `named` so the declaration stays concise:

```python
signup_wizard = (
    Wizard()
    .step(named("account", AccountForm))
    .step(named("profile", ProfileForm))
    .step(named("confirm", ConfirmForm))
)
```

This is shorthand for passing the same form with `context={"step_name": ...}`
and keeps repetitive naming boilerplate out of the flow declaration.

The context argument should also be able to accept a callable that receives the
current `request`. That allows step metadata to be derived from request state,
including prior wizard execution stored on `request.wizard`.

For example:

```python
def build_profile_context(request):
    account_step = request.wizard.path.find_one_by_context(step_name="account")
    account_data = (
        account_step.form.cleaned_data
        if account_step and account_step.is_complete
        else {}
    )

    return {
        "step_name": "profile",
        "analytics_key": "signup-profile",
        "account_type": account_data.get("account_type"),
        "prefill_source": "wizard" if account_data else "request",
    }


signup_wizard = (
    Wizard()
    .step(AccountForm, context={"step_name": "account", "analytics_key": "signup-account"})
    .step(ProfileForm, context=build_profile_context)
    .step(ConfirmForm, context={"step_name": "confirm", "analytics_key": "signup-confirm"})
)
```

This keeps context declarative in the common case while still allowing a later
step to build richer metadata as the wizard tree accumulates completed nodes.
Because the callable receives the request, it can also use tenant information,
feature flags, locale, or any other request-scoped input when shaping that
context.

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
from django.views.generic.edit import FormView


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

Implementation idea for the runtime population boundary:

```python
class Wizard:
    def populate(self, request):
        # Take the incoming request and resolve the configured storage backend.
        # Load the current wizard state for this request from that storage.
        # Combine the stored state with the declared wizard tree.
        # Populate the tree with the current runtime state for each step.
        # Reevaluate branch reachability from the root using the current data.
        # Build the path projection for the visited/completed execution route.
        # Return the request-specific runtime wizard.
        #
        # This should not execute the current step. Step execution happens later
        # when the active FormView receives a wizard-shaped request and returns
        # a response.
        pass
```

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
    .step(AccountTypeForm, context={"step_name": "account_type"})
    .branch(
        condition(is_business_account, business_flow),
        default=personal_flow,
    )
    .step(ReviewForm, context={"step_name": "review"})
)
```

At runtime, the user should be able to inspect something conceptually like:

```python
request.wizard.tree
```

where each `Step` node represents one step in the declared flow and exposes the
runtime state for that step.

Even though branch evaluation short-circuits for routing, the full declared tree
still exists in `wizard.tree`. Inactive branch nodes remain part of the
structure, so introspection code can still walk the complete flow definition
while `wizard.path` reflects only the visited/completed path.

Conceptually:

```python
step = request.wizard.tree.find_one_by_context(step_name="account")
```

The tree should expose helper methods for common context-based lookups. In
particular, it should provide a single-node lookup like
`find_one_by_context(...)` that returns `None` when no node matches and raises
an error when the provided context is too broad and matches more than one node.

and a `Step` node can hold things like:

- its position in the tree,
- the underlying form class or `FormView` class,
- the step context declared for that node (for example `{"step_name": "account"}`),
- whether it is currently reachable,
- whether it has run,
- whether it completed successfully,
- the bound form state, including `form.cleaned_data` when the step completes,
- validation errors for the most recent run,
- the request that was passed into that step view,
- the response returned by that step view,
- and any step-level metadata Gandalf records while executing the flow.

The important idea is that Gandalf is not just storing “form answers”.
It is capturing the execution of the flow step-by-step in a structure that
matches the declared tree.

So a node is not just a bag of form data. It is the runtime record of:

- what step this was,
- what view handled it,
- what request/response interaction happened there,
- and what data or metadata was produced as a result.

That means the tree can be walked not only to inspect collected values, but
also to inspect how the wizard actually ran.

### Path-shaped runtime projection (sequence of execution steps)

In addition to the full execution tree, Gandalf should expose a **path**
projection that represents the route actually taken through that tree.

Conceptually:

```python
request.wizard.path
```

The path is intended to be an **ordered sequence of steps**
in execution order. In other words, it is the linearized timeline of the run,
but only for steps that were actually visited.

Each item in `wizard.path` should be the same `Step` object exposed by
`wizard.tree`, just presented in execution order. That keeps lookups and
iteration consistent across both APIs while still allowing each `Step` to carry
whatever runtime metadata Gandalf records, such as:

- whether the step completed successfully,
- completion timestamp or sequence index,
- list index / sequence position,
- and any other step-level runtime metadata collected during execution.

This gives consumers a first-class way to iterate “what happened” without
having to flatten `wizard.tree` themselves.

For example:

```python
for step in request.wizard.path:
    print(step.context.get("step_name"), step.is_complete)

# Pythonic random access
first = request.wizard.path[0]
last = request.wizard.path[-1]
count = len(request.wizard.path)
```

The API should feel list-like, so callers can use familiar Python operations:

- iterate directly (`for item in wizard.path`),
- index and slice (`wizard.path[0]`, `wizard.path[-1]`, `wizard.path[1:4]`),
- check length (`len(wizard.path)`),
- and materialize when desired (`list(wizard.path)`).

The path should also expose helper lookups so consumers can find subsets of
steps without hand-rolling loops each time. For example:

```python
account = wizard.path.find_one_by_context(step_name="account")
completed_profile_steps = wizard.path.filter_by_context(step_name="profile")
```

`find_one_by_context(...)` should return a `Step`, return `None` when there is
no match, and raise an error when the lookup is ambiguous.
`filter_by_context(...)` should return matching `Step` objects in execution
order. Because `wizard.path` only contains visited/completed nodes, every
returned step should already be complete and should expose its submitted data
through `step.form.cleaned_data`. In other words, being part of `wizard.path`
means the step has completed successfully enough to contribute runtime data to
the execution path.

`Step` should not expose its own `cleaned_data` alias. Submitted form data
should only be read through `step.form.cleaned_data`, keeping the bound form as
the single data entry point.

The path should include nodes that were visited and completed, including
historical entries when the user changes earlier answers and causes a different
branch to become active.

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
- Code consuming wizard state can use `wizard.path` for ordered visited/completed
  steps, or walk `wizard.tree` when it needs the full structural and historical
  picture.

This keeps Gandalf honest about its core abstractions:

- the flow is declared as a tree,
- the runtime state is represented as a tree,
- and Gandalf also exposes a path projection of visited/completed steps so
  consumers do not need to flatten the tree just to get execution order.

In other words, Gandalf should not force one canonical interpretation of “all
wizard data”. It should expose both the shaped runtime tree and the execution
path so callers can pick the structure that matches their use case.

That also means Gandalf does not need a separate result-building abstraction.

The tree-shaped runtime state is the source of truth, and code running at
`done()` time can walk that tree to derive whatever final payload it needs.

For example:

```python
class CheckoutWizardViewSet(WizardViewSet):
    wizard = checkout_wizard

    def done(self, wizard):
        customer_step = wizard.path.find_one_by_context(step_name="customer")
        address_step = wizard.path.find_one_by_context(step_name="address")

        create_order(
            email=customer_step.form.cleaned_data["email"],
            shipping_address={
                "line_1": address_step.form.cleaned_data["line_1"],
                "postcode": address_step.form.cleaned_data["postcode"],
            },
        )
```

If a project wants a transformed payload, it can still build one from either
`wizard.tree` or `wizard.path`. Gandalf only needs to guarantee that:

- `wizard.tree` accurately represents the declared structure plus runtime state,
- and `wizard.path` accurately represents the visited/completed route through
  that structure.

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
    .step(CustomerForm, context={"step_name": "customer"})
    .step(AddressForm, context={"step_name": "address"})
    .step(ConfirmForm, context={"step_name": "confirm"})
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
    company_step = request.wizard.tree.find_one_by_context(step_name="company")
    cleaned = (
        company_step.form.cleaned_data
        if company_step and company_step.is_complete
        else {}
    )
    return cleaned.get("is_business")


company_wizard = (
    Wizard()
    .step(CompanyForm, context={"step_name": "company"})
    .branch(
        condition(needs_vat, VATForm),
        default=None,  # skip VAT if condition is false
    )
    .step(SummaryForm, context={"step_name": "summary"})
)
```

`find_one_by_context(...)` returns a `Step` node. To read submitted values from
that step, access the bound form state via `step.form.cleaned_data`.

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
from django.views.generic.edit import FormView


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
        account_step = self.request.wizard.tree.find_one_by_context(step_name="account")
        account_data = (
            account_step.form.cleaned_data
            if account_step and account_step.is_complete
            else {}
        )
        return {
            "contact_email": account_data.get("email"),
            "country": account_data.get("country"),
        }


class ConfirmStepView(FormView):
    form_class = ConfirmForm

    def get_initial(self):
        account_step = self.request.wizard.tree.find_one_by_context(step_name="account")
        profile_step = self.request.wizard.tree.find_one_by_context(step_name="profile")
        account_data = (
            account_step.form.cleaned_data
            if account_step and account_step.is_complete
            else {}
        )
        profile_data = (
            profile_step.form.cleaned_data
            if profile_step and profile_step.is_complete
            else {}
        )
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
    .step(AccountStepView, context={"step_name": "account"})
    .step(ProfileStepView, context={"step_name": "profile"})
    .step(ConfirmStepView, context={"step_name": "confirm"})
)
```

With `formtools`, the initial-value logic tends to accumulate in one wizard-level method keyed by step name.

With Gandalf, the easy case is still just `.step(MyForm)`. When a step needs more control, each explicit `FormView` can own its own `get_initial()` and still read prior wizard state via `self.request.wizard.tree`. If a step benefits from knowing that it is executing in wizard context, that information is available on `self.request.wizard`, and the untouched incoming request remains available as `self.request.wizard.original_request`. That keeps the wiring local to the step, and views like `PortableProfileStepView` remain completely ordinary `FormView`s when you do not want any wizard-specific mechanics at all.

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

See `CONTRIBUTING.md` for local setup, workflow expectations, and commit message conventions.
