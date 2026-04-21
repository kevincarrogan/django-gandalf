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
        otherwise(FallbackForm),
    )
    .then(FinalForm)
)
```

This reads like a flow graph rather than a list of ad hoc callbacks.

---

## Examples from the project

The `examples.py` file shows the intended declarative and chained style.

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
