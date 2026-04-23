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
        ...
```

## `WizardTree`

```python
class WizardTree:
    def find_one_by_context(self, **context) -> "Step | None":
        """Match against Step context values using the provided context kwargs.

        Return the matching Step, or None if no match.

        Raises:
            MultipleStepsReturned: If the lookup is ambiguous.
        """
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

## `Step`

```python
class Step:
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
