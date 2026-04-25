# Implementation Ideas

## `Wizard`

```python
class Wizard:
    """Declare and evaluate a wizard flow."""

    tree: "WizardTree | None"
    path: "WizardPath | None"

    original_request: "HttpRequest | None"

    storage_class: type["BaseStorage"]
    form_view_factory_class: type["BaseFormViewFactory"]
    management_form_class: type["BaseManagementForm"]

    def __init__(
        self,
        *,
        storage_class: type["BaseStorage"] = SessionStorage,
        form_view_factory_class: type["BaseFormViewFactory"] = FormViewFactory,
        management_form_class: type["BaseManagementForm"] = ManagementForm,
    ):
        """Configure a wizard with its storage, view factory, and management form."""
        ...

    def step(self, step, context=None) -> "Wizard":
        """Append a step or sub-wizard to the flow."""
        ...

    def branch(self, *conditions, default=None) -> "Wizard":
        """Append a conditional branch to the flow."""
        ...

    def populate(self, request) -> "Wizard":
        """Return a wizard populated from the current request state."""
        runtime_wizard = self._clone_for_request(request)
        runtime_wizard.original_request = request

        storage = runtime_wizard.storage_class.from_request(request, runtime_wizard)
        serialized_state = storage.load()

        runtime_wizard.tree = WizardTreeBuilder(
            wizard=runtime_wizard,
            request=request,
        ).build()

        runtime_wizard.tree.walk(
            WizardStateDeserializer(serialized_state),
            ContextResolver(request),
        )

        path_builder = WizardPathBuilder()
        runtime_wizard.tree.walk(path_builder)
        runtime_wizard.path = path_builder.build()

        return runtime_wizard
```

`populate()` should prepare a request-specific runtime wizard, not execute the
active step. Step execution should happen later, when the active `FormView`
receives a wizard-shaped request and returns a response.

The important abstraction is that the runtime wizard is a tree of `Step` nodes
that can be walked. Storage should persist serialized step state, while
serializer and visitor objects apply behavior to each step during traversal.

Serialization and deserialization should use the same traversal API. Storage
loads and saves plain data, while tree visitors translate between that data and
runtime step state.

Building the runtime tree is significant enough to be its own named
collaborator. Visitors operate on a tree that already exists; `WizardTreeBuilder`
creates that tree from the declared wizard structure for the current request.

Path building can use the same visitor pattern, but should happen after
context resolution so it collects completed steps from the runtime tree.

## `WizardTree`

```python
class WizardTree:
    def walk(self, *visitors) -> None:
        """Walk the Step tree in execution order and let each visitor inspect steps."""
        ...

    def find_one_by_context(self, **context) -> "Step | None":
        """Match against Step context values using the provided context kwargs.

        Return the matching Step, or None if no match.

        Raises:
            MultipleStepsReturned: If the lookup is ambiguous.
        """
        finder = ContextFinder(context)
        self.walk(finder)
        return finder.one()

    def filter_by_context(self, **context) -> list["Step"]:
        """Match against Step context values using the provided context kwargs.

        Return the matching Step objects in execution order.
        """
        finder = ContextFinder(context)
        self.walk(finder)
        return finder.all()
```

## `WizardTreeBuilder`

```python
class WizardTreeBuilder:
    """Build a runtime tree from the declared wizard structure."""

    def __init__(self, *, wizard, request):
        ...

    def build(self) -> "WizardTree":
        ...
```

`WizardTreeBuilder` is responsible for structural work such as expanding nested
`Wizard` instances into a tree of `Step` nodes, creating generated `FormView`
steps for plain forms, preserving explicit `FormView` steps, attaching declared
context, assigning stable step keys, and preserving declaration order.

## `WizardTreeVisitor`

```python
class WizardTreeVisitor:
    """Hook object used by WizardTree.walk() while traversing steps."""

    def enter(self, step) -> None:
        """Run before visiting the step's children."""
        ...

    def exit(self, step) -> None:
        """Run after visiting the step's children."""
        ...
```

`WizardTree.walk()` should call `enter()` for each visitor in the order passed,
then descend into children, then call `exit()` in reverse order. That gives
visitors a predictable stack-like lifecycle without making traversal control a
visitor responsibility yet.

## `ContextFinder`

```python
class ContextFinder(WizardTreeVisitor):
    """Collect steps whose context matches the provided values."""

    def __init__(self, context: dict):
        self.context = context
        self.matches = []

    def enter(self, step) -> None:
        if step.matches_context(**self.context):
            self.matches.append(step)

    def one(self) -> "Step | None":
        if len(self.matches) > 1:
            raise MultipleStepsReturned
        if not self.matches:
            return None
        return self.matches[0]

    def all(self) -> list["Step"]:
        return self.matches
```

`ContextFinder` keeps context lookup as a traversal concern. `WizardTree` can
walk the full evaluated tree, while `WizardPath` can walk only the ordered path
steps and still reuse the same finder.

## `WizardStateDeserializer`

```python
class WizardStateDeserializer(WizardTreeVisitor):
    """Apply persisted storage data to runtime Step nodes."""

    def __init__(self, data: dict):
        ...

    def enter(self, step) -> None:
        step.apply_state(self.data.get(step.key))
```

## `WizardStateSerializer`

```python
class WizardStateSerializer(WizardTreeVisitor):
    """Collect runtime Step state into plain storage data."""

    def __init__(self):
        self.data = {}

    def enter(self, step) -> None:
        self.data[step.key] = step.to_state()

    def build(self) -> dict:
        return self.data
```

Saving wizard state can then use the same traversal pattern:

```python
serializer = WizardStateSerializer()
wizard.tree.walk(serializer)
storage.save(serializer.build())
```

## `ContextResolver`

```python
class ContextResolver:
    """Resolve request-aware context values while walking the tree."""

    def __init__(self, request):
        ...

    def enter(self, step) -> None:
        ...
```

## `WizardPath`

```python
class WizardPath:
    def walk(self, *visitors) -> None:
        """Walk the path steps in order and let each visitor inspect them."""
        for step in self:
            for visitor in visitors:
                visitor.enter(step)
            for visitor in reversed(visitors):
                visitor.exit(step)

    def __iter__(self):
        ...

    def __len__(self):
        ...

    def __getitem__(self, index):
        ...

    def find_one_by_context(self, **context) -> "Step | None":
        """Match against Step context values using the provided context kwargs.

        Return the matching Step, or None if no match.

        Raises:
            MultipleStepsReturned: If the lookup is ambiguous.
        """
        finder = ContextFinder(context)
        self.walk(finder)
        return finder.one()

    def filter_by_context(self, **context) -> list["Step"]:
        """Match against Step context values using the provided context kwargs.

        Return the matching Step objects in execution order.
        """
        finder = ContextFinder(context)
        self.walk(finder)
        return finder.all()
```

## `WizardPathBuilder`

```python
class WizardPathBuilder(WizardTreeVisitor):
    """Collect visited/completed steps from an evaluated tree."""

    def __init__(self):
        self.steps = []

    def enter(self, step) -> None:
        if step.is_complete:
            self.steps.append(step)

    def build(self) -> "WizardPath":
        return WizardPath(self.steps)
```

`WizardPathBuilder` should not filter out completed steps solely because they
are no longer on the active route after a later branch decision changes. If a
user completes a business branch, goes back, and changes an earlier answer so
the personal branch becomes active, the previous business steps should remain
in `wizard.path` as historical visited/completed entries. Active-step selection
can still decide which branch route should run next, but the path is an ordered
execution history rather than only the current active route.

## `Step`

```python
class Step:
    key: str
    context: dict

    def to_state(self) -> dict:
        ...

    def apply_state(self, data: dict | None) -> None:
        ...

    def matches_context(self, **context) -> bool:
        return all(
            self.context.get(key) == value
            for key, value in context.items()
        )
```

## `MultipleStepsReturned`

```python
class MultipleStepsReturned(ValueError):
    ...
```

## `BaseStorage`

```python
class BaseStorage:
    ...
```

Storage is intentionally session-backed for the prototype. Gandalf should
provide `SessionStorage` as its only built-in storage class, while still
allowing callers to pass a compatible custom session-backed storage class to
`Wizard(storage_class=...)`.

Do not expose `CookieStorage` as a built-in or documented configuration option
for now: wizard state may include enough structured form data and runtime
metadata that cookie-backed storage would be too size-constrained.

Storage implementations should persist plain JSON-compatible data in
`request.session`, not pickled Python objects or live runtime objects. Django
then handles serialization through the configured session backend.

## `SessionStorage`

```python
class SessionStorage(BaseStorage):
    ...
```

## `BaseFormViewFactory`

```python
class BaseFormViewFactory:
    ...
```

## `FormViewFactory`

```python
class FormViewFactory(BaseFormViewFactory):
    ...
```

## `BaseManagementForm`

```python
from django import forms


class BaseManagementForm(forms.Form):
    ...
```

## `ManagementForm`

```python
class ManagementForm(BaseManagementForm):
    ...
```

## `WizardViewSet`

```python
from django.http import HttpRequest, HttpResponse


class WizardViewSet:
    wizard: "Wizard | None"
    template_name: "str | None"

    def get_wizard(self, request: HttpRequest) -> "Wizard":
        ...

    def done(self, request: HttpRequest) -> HttpResponse:
        ...
```
