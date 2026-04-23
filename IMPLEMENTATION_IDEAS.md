# Implementation Ideas

## `Wizard`

```python
class Wizard:
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
        ...

    def step(self, step, context=None) -> "Wizard":
        ...

    def branch(self, *conditions, default=None) -> "Wizard":
        ...

    def populate(self, request) -> "Wizard":
        ...
```

## `WizardTree`

```python
class WizardTree:
    def find_one_by_context(self, **context):
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

    def find_one_by_context(self, **context):
        ...

    def filter_by_context(self, **context):
        ...
```

## `Step`

```python
class Step:
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
class BaseManagementForm:
    ...
```

## `ManagementForm`

```python
class ManagementForm(BaseManagementForm):
    ...
```

## `WizardViewSet`

```python
class WizardViewSet:
    ...
```
