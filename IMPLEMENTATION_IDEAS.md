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
            BranchEvaluator(request),
        )

        path_builder = WizardPathBuilder()
        runtime_wizard.tree.walk(path_builder)
        runtime_wizard.path = path_builder.build()

        return runtime_wizard
```

`populate()` should prepare a request-specific runtime wizard, not execute the
active step. Step execution should happen later, when the active `FormView`
receives a wizard-shaped request and returns a response.

The important abstraction is that the runtime wizard is a tree that can be
walked. Storage should persist serialized node state, while serializer and
visitor objects apply behavior to each node during traversal.

Serialization and deserialization should use the same traversal API. Storage
loads and saves plain data, while tree visitors translate between that data and
runtime node state.

Building the runtime tree is significant enough to be its own named
collaborator. Visitors operate on a tree that already exists; `WizardTreeBuilder`
creates that tree from the declared wizard structure for the current request.

Path building can use the same visitor pattern, but should happen after
context resolution and branch evaluation so it collects from the evaluated tree.

## `WizardTree`

```python
class WizardTree:
    def walk(self, *visitors) -> None:
        """Walk the tree in execution order and let each visitor inspect nodes."""
        ...

    def find_one_by_context(self, **context) -> "Step | None":
        """Match against Step context values using the provided context kwargs.

        Return the matching Step, or None if no match.

        Raises:
            MultipleStepsReturned: If the lookup is ambiguous.
        """
        ...
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
`Wizard` instances, creating generated `FormView` step nodes for plain forms,
preserving explicit `FormView` steps, attaching declared context, assigning
stable node keys, and preserving declaration order.

## `WizardTreeVisitor`

```python
class WizardTreeVisitor:
    """Hook object used by WizardTree.walk() while traversing nodes."""

    def enter(self, node) -> None:
        """Run before visiting the node's children."""
        ...

    def exit(self, node) -> None:
        """Run after visiting the node's children."""
        ...

    def should_descend(self, node) -> bool:
        """Return whether traversal should continue into the node's children."""
        return True
```

`WizardTree.walk()` should call `enter()` for each visitor in the order passed,
then descend into children when every visitor allows it, then call `exit()` in
reverse order. That gives visitors a predictable stack-like lifecycle while
still allowing a visitor such as `BranchEvaluator` to prevent traversal into
unreachable branches.

## `WizardStateDeserializer`

```python
class WizardStateDeserializer(WizardTreeVisitor):
    """Apply persisted storage data to runtime tree nodes."""

    def __init__(self, data: dict):
        ...

    def enter(self, node) -> None:
        node.apply_state(self.data.get(node.key))
```

## `WizardStateSerializer`

```python
class WizardStateSerializer(WizardTreeVisitor):
    """Collect runtime tree node state into plain storage data."""

    def __init__(self):
        self.data = {}

    def enter(self, node) -> None:
        self.data[node.key] = node.to_state()

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

    def enter(self, node) -> None:
        ...
```

## `BranchEvaluator`

```python
class BranchEvaluator:
    """Evaluate branch conditions and mark reachable nodes while walking."""

    def __init__(self, request):
        ...

    def enter(self, node) -> None:
        ...

    def should_descend(self, node) -> bool:
        ...
```

## `WizardPath`

```python
class WizardPath:
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
        ...

    def filter_by_context(self, **context) -> list["Step"]:
        """Match against Step context values using the provided context kwargs.

        Return the matching Step objects in execution order.
        """
        ...
```

## `WizardPathBuilder`

```python
class WizardPathBuilder(WizardTreeVisitor):
    """Collect visited/completed steps from an evaluated tree."""

    def __init__(self):
        self.steps = []

    def enter(self, node) -> None:
        if node.is_step and node.is_reachable and node.is_complete:
            self.steps.append(node)

    def should_descend(self, node) -> bool:
        return node.is_reachable

    def build(self) -> "WizardPath":
        return WizardPath(self.steps)
```

## `Step`

```python
class Step:
    key: str

    def to_state(self) -> dict:
        ...

    def apply_state(self, data: dict | None) -> None:
        ...
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
