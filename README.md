# django-gandalf

`django-gandalf` is an alternative approach to multi-step Django form flows.

This project exists because `django-formtools` can become hard to configure when your flow stops being a straight line and starts looking like a tree (multiple branches, nested branches, optional sub-flows, and reusable path fragments).

The core idea is:

- define flows declaratively,
- compose them with chained syntax,
- and model branching as first-class structure.

---

## Why this exists

Traditional wizard tooling is great for simple, linear steps:

1. Step A
2. Step B
3. Step C

But real product journeys often branch based on earlier answers, and those branches can branch again.

For example:

- business user vs individual user,
- domestic vs international onboarding,
- risk/compliance sub-flows,
- optional feature setup paths.

These often need tree-like flow composition where pieces can be nested and reused cleanly.

`django-gandalf` is intended to make this easier to express than `django-formtools` by favoring explicit, composable flow declarations.

---

## Design goals

- **Declarative flow definitions**: read the flow structure in one place.
- **Chainable API**: build flows with `.start()`, `.then()`, and `.branch()`.
- **Branching as a first-class concept**: nested and conditional flows should be easy to model.
- **Reusable flow fragments**: define mini-wizards and compose them into larger trees.
- **Django-friendly abstraction**: compose around `FormView`-like steps instead of tightly coupling everything to raw forms.

---

## Core API shape (early)

From the prototype examples, flow construction follows this style:

```python
wizard = (
    Wizard()
    .start(FirstForm)
    .then(SecondForm)
    .branch(
        condition(is_this, Wizard().start(AForm).then(BForm)),
        condition(is_that, some_other_wizard),
        otherwise=FallbackForm,
    )
    .then(FinalForm)
)
```

This reads like a flow graph rather than a list of ad hoc callbacks.

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
    .start(CustomerForm)
    .then(AddressForm)
    .then(ConfirmForm)
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
company_wizard = (
    Wizard()
    .start(CompanyForm)
    .branch(
        condition(needs_vat, VATForm),
        otherwise=None,  # skip VAT if condition is false
    )
    .then(SummaryForm)
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
business_flow = Wizard().start(BizAForm).then(BizBForm)
personal_flow = Wizard().start(PersonAForm)

onboarding_wizard = (
    Wizard()
    .start(AccountTypeForm)
    .branch(
        condition(is_business_account, business_flow),
        otherwise=personal_flow,
    )
    .then(FinalForm)
)
```

What improves here:

- Branch targets can be full reusable sub-wizards.
- Flow shape is explicit and visible in one declaration.
- Less bespoke navigation plumbing for tree-style journeys.

---

## Examples from this project

The `examples.py` file demonstrates the intended declarative and chained style.

### 1) A nested branch flow

```python
that_wizard = (
    Wizard()
    .start(BWizardFirstForm)
    .branch(
        condition(is_this, BWizardSecondForm),
        otherwise=BWizardThirdForm,
    )
)

main_wizard = (
    Wizard()
    .start(FirstForm)
    .then(SecondForm)
    .then(ThirdForm)
    .branch(
        condition(is_this, Wizard().start(AWizardFirstForm).then(AWizardSecondForm)),
        condition(is_that, that_wizard),
    )
    .then(MyFinalForm)
)
```

Why this is important:

- A branch can point to a **single next step** or to a **full nested wizard**.
- Sub-flows are reusable objects, not one-off inline logic.
- The whole structure still reads top-to-bottom.

### 2) View-centric composition

The examples also show the intent to compose with `FormView`-like steps:

```python
view_based = (
    Wizard()
    .start(FirstFormView)
    .then(SecondForm)
)
```

This supports an architecture where existing form views can stay reusable outside wizard contexts.

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

- `examples.py` demonstrates desired usage and composition style.
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

1. Start with `examples.py` to understand the intended developer experience.
2. Use `implementation.py` to inspect current assumptions and gaps.
3. Open issues/PRs with concrete branch/tree use-cases—especially where existing wizard tooling becomes hard to maintain.
