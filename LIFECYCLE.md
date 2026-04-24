# Request / Response Lifecycle

This document describes the intended Gandalf request/response lifecycle at the
prototype design level. `IMPLEMENTATION_IDEAS.md` remains the source of truth
for concrete API shape, while this document explains how the moving parts fit
together during one wizard request.

## Core Idea

Gandalf owns the outer Django request/response boundary, then delegates the
active step to an ordinary `FormView`-like object.

The step view should feel as if it is running in a normal Django view lifecycle.
Gandalf maintains that illusion by preparing a wizard-shaped request for the
step, interpreting the response it returns, updating wizard state, and deciding
where the browser should go next.

That gives the project two complementary layers:

- `WizardViewSet` handles the public wizard endpoint and routing semantics.
- Step `FormView`s handle ordinary form rendering, binding, validation, and
  view-level customization.

## High-Level Flow

One incoming request should conceptually move through these phases:

1. Django routes the request to a Gandalf `WizardViewSet`.
2. The viewset gets the declared wizard with `get_wizard()`.
3. The declared wizard is populated into a request-specific runtime wizard.
4. Storage loads previously persisted wizard state.
5. A runtime `WizardTree` is built from the declared wizard structure.
6. Tree visitors apply loaded state, resolve context, and evaluate branches.
7. A `WizardPath` projection is built from the evaluated tree.
8. Gandalf finds the active step for this request.
9. Gandalf prepares a wizard-shaped request for that step.
10. The active step `FormView` handles the request and returns a response.
11. Gandalf interprets the step response.
12. Gandalf serializes and saves updated tree state.
13. Gandalf returns the final HTTP response for this request.

## Declared Wizard vs Runtime Wizard

The declared wizard is the reusable flow definition written by application
code. It is the thing a project assigns to a viewset or returns from
`get_wizard()`.

For example:

```python
from django.views.generic.edit import FormView


class ProfileStepView(FormView):
    form_class = ProfileForm


signup_wizard = (
    Wizard()
    .step(AccountForm, context={"step_name": "account"})
    .step(ProfileStepView, context={"step_name": "profile"})
    .step(ConfirmForm, context={"step_name": "confirm"})
)
```

The runtime wizard is a per-request clone produced by `Wizard.populate()`. It
holds request-specific state such as:

- `original_request`
- loaded storage data
- the evaluated `tree`
- the completed `path`
- resolved context values
- step form state and response metadata

`populate()` should not execute the active step. It prepares the runtime model
that later execution needs.

## ViewSet Boundary

`WizardViewSet` is the object that Django routes to. It is responsible for the
outside-world concerns:

- selecting or building the wizard for the current request
- calling `populate()` to create the runtime wizard
- selecting the active step
- shaping the request passed into the active step
- interpreting the step response
- saving state
- deciding whether to render, redirect, advance, go back, or call `done()`

The viewset can use a static class-level wizard for simple cases:

```python
class SignupWizardViewSet(WizardViewSet):
    wizard = signup_wizard
```

It can also build the declaration dynamically from the request:

```python
class SignupWizardViewSet(WizardViewSet):
    def get_wizard(self):
        wizard = Wizard().step(AccountForm)

        if self.request.user.is_staff:
            wizard = wizard.step(InternalReviewForm)

        return wizard.step(ConfirmForm)
```

Dynamic declarations are still declarations. They should be populated into a
runtime wizard before Gandalf tries to inspect prior answers or execute a step.

## Population Phase

Population converts a declaration into request-specific runtime state.

The intended shape is:

```python
runtime_wizard = declared_wizard.populate(request)
request.wizard = runtime_wizard
```

During population:

1. Gandalf clones the declared wizard for request-local use.
2. `SessionStorage.from_request(request, runtime_wizard)` locates persisted
   state.
3. `storage.load()` returns plain JSON-compatible data.
4. `WizardTreeBuilder` expands the declaration into a runtime tree.
5. `WizardStateDeserializer` applies persisted node state.
6. `ContextResolver` resolves static and callable step context.
7. `WizardPathBuilder` collects visited/completed steps from the evaluated
   tree.

The important ordering is that path building happens after context resolution
so request-aware step metadata is available. The path should describe what has
completed in execution order, including historical completed steps from
branches that are no longer active.

## Runtime Tree

`wizard.tree` is the complete runtime representation of the declared flow.

The tree should keep the full structure even when some branch nodes are not on
the currently active route. This matters because callers may need to inspect
historical or inactive branch state after a user changes an earlier answer.

Each `Step` node should represent one form interaction and can carry:

- a stable node key
- declared or resolved context
- the underlying form class or `FormView` class
- whether the step is on the currently active route, if Gandalf records that
  metadata
- completion state
- the bound form instance
- validation errors
- the shaped request passed to the step
- the response returned by the step
- serialized runtime metadata

Storage should not save the tree object itself. It should save plain node state
collected by walking the tree with `WizardStateSerializer`.

## Runtime Path

`wizard.path` is the ordered projection of steps that have been visited and
completed.

The tree answers "what is the whole flow and what state exists on each node?"
The path answers "what completed steps have happened, in execution order?"

The path should expose the same `Step` objects as the tree, just in execution
order. That makes lookup behavior consistent:

```python
account_step = wizard.path.find_one_by_context(step_name="account")
account_data = account_step.form.cleaned_data if account_step else {}
```

The path may include historical completed steps from branches that are no
longer active after a user changes an earlier answer. Code that needs only the
currently active route should use route-selection metadata or a route-specific
tree/path projection once that design is settled.

Code that needs ordered submitted data will usually read from `wizard.path`.
Code that needs structural or inactive branch information should walk
`wizard.tree`.

## Active Step Selection

After population, Gandalf should know enough to select the active step.

Conceptually, the active step is the next step on the selected branch route
that still needs to run, unless the request explicitly targets a previous step
or a management form action changes navigation.

The management form is the bridge between the rendered browser form and the
wizard controller. It should give Gandalf enough information to identify the
wizard interaction without forcing every step `FormView` to understand Gandalf
internals.

The template tag:

```django
{% load gandalf %}

<form method="post">
  {% csrf_token %}
  {% gandalf_management_form %}
  {{ form.as_p }}
</form>
```

should render the hidden wizard management fields when the request is running
inside Gandalf. Outside a wizard, it should render nothing.

## Wizard-Shaped Step Request

Before invoking the active step, Gandalf prepares a request object for that
step.

That request should preserve ordinary Django assumptions for the `FormView`,
while also exposing wizard context:

- `step_request.wizard` points at the runtime wizard.
- `step_request.wizard.original_request` points at the untouched incoming
  request.
- request method, POST data, files, user, session, messages, and other Django
  request attributes remain available in the shape a `FormView` expects.

The goal is that a configured step view can run both inside and outside
Gandalf when its behavior is otherwise reusable.

## Step Execution

The active step is a `FormView` class either supplied directly by the user or
generated by `FormViewFactory` from a plain Django form class.

For a `GET`, the step normally renders its form using ordinary `FormView`
behavior.

For a `POST`, the step binds and validates the submitted form using ordinary
`FormView` behavior. Gandalf then records the result on the active `Step` node
and decides how to continue.

A user-supplied `FormView` should keep its own behavior. A generated `FormView`
can inherit viewset-level defaults such as `template_name` or
`get_context_data()` according to the API direction in the README.

## Interpreting Step Responses

Gandalf should remain in control after the active step returns a response.

The default response interpretation is:

- A `GET` response from the active step is returned as the rendered wizard step.
- On `POST`, a `200 OK` response means the step did not successfully advance,
  usually because the form is invalid and needs to be re-rendered.
- On `POST`, a redirect response means the step completed successfully and
  Gandalf can update state and move to the next wizard decision.

That default keeps step views ordinary while allowing the wizard controller to
own multi-step navigation. Later extension points can override this for unusual
step semantics.

## Saving State

After step execution changes runtime state, Gandalf should serialize the tree:

```python
serializer = WizardStateSerializer()
wizard.tree.walk(serializer)
storage.save(serializer.build())
```

The saved data should be plain JSON-compatible state keyed by stable node key.
It should not include live `Form`, `FormView`, request, response, or tree
objects.

On the next request, `WizardStateDeserializer` applies that saved state back
onto a freshly built runtime tree.

## Completion

When every step on the selected branch route is complete, the viewset should
call `done()`.

`done()` should receive the runtime wizard, not a separate flattened result
object. Application code can derive its final payload from `wizard.path` or
`wizard.tree` depending on what it needs.

For example:

```python
class CheckoutWizardViewSet(WizardViewSet):
    wizard = checkout_wizard

    def done(self, wizard):
        customer_step = wizard.path.find_one_by_context(step_name="customer")
        address_step = wizard.path.find_one_by_context(step_name="address")

        create_order(
            email=customer_step.form.cleaned_data["email"],
            postcode=address_step.form.cleaned_data["postcode"],
        )
```

## Responsibility Map

- `Wizard`: Declares the flow and stores constructor-level configuration such
  as storage, form view factory, and management form classes.
- `WizardViewSet`: Owns the public request/response boundary and wizard
  navigation semantics.
- `WizardTreeBuilder`: Expands a declared wizard into a request-specific
  runtime tree.
- `WizardTree`: Holds the full evaluated flow structure and supports visitor
  traversal.
- `WizardPath`: Presents the completed route as an ordered sequence of `Step`
  objects.
- `Step`: Records one runtime form interaction inside the tree.
- `SessionStorage`: Loads and saves plain serialized wizard state in
  `request.session`.
- `WizardStateDeserializer`: Applies persisted node state to a freshly built
  tree.
- `WizardStateSerializer`: Collects runtime node state into storage-safe data.
- `ContextResolver`: Resolves static and request-aware context values.
- `FormViewFactory`: Builds a step `FormView` class when a user declares a
  plain form.
- `ManagementForm`: Carries wizard control metadata through rendered forms.

## Open Design Questions

- How exactly should Gandalf identify an explicitly targeted previous step?
- Which management form fields are required for routing and tamper detection?
- Should response interpretation be configured per step, per wizard, or both?
- What metadata belongs in serialized state versus runtime-only node state?
- How should historical branch state be exposed when a changed answer makes a
  previous branch inactive?
