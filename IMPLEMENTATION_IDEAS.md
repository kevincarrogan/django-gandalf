# Implementation Ideas

## `Wizard`

```python
class Wizard:
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

## `WizardViewSet`

```python
class WizardViewSet:
    ...
```
