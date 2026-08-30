# Configuration

`Wizard.configure(**configuration)` — the runtime seams of a wizard, each
with a default, plus the two seams that live on a viewset instead and the
Django settings a wizard needs.

```python
from gandalf.wizard import Wizard

wizard = (
    Wizard()
    .step(ApplicantForm, name="applicant")
    .configure(template_name="grants/step.html", observer_class=CountRejections)
)
```

---

## Reference

### `Wizard.configure(**configuration)`

Freeze a declaration into a [`ConfiguredWizard`](wizard.md#configuredwizard).
Optional: a `WizardViewSet` configures a bare `Wizard` itself, passing only
its own `template_name`. Call it when any other key is needed, and then
give `template_name` here too — a pre-configured wizard is taken as-is.

**Parameters** — every key below is optional and independent. A key not
listed here is refused with `ImproperlyConfigured` (*"Wizard.configure()
does not read …"*), since one that is stored and never applied is a
misspelling that would otherwise go unnoticed. A `ConfiguredWizard`
subclass that reads more extends `configuration_keys`.

| Key | Default | Replacement must be |
| --- | --- | --- |
| `template_name` | `None` | a template path (`str`) |
| `form_view_factory` | `gandalf.form_views.form_view_factory` | callable `(form_class, *, template_name) -> type[FormView]` |
| `cursor_walker_class` | `gandalf.runtime.CursorWalker` | a `CursorWalker` subclass |
| `step_dispatcher_class` | `gandalf.runtime.StepDispatcher` | a `StepDispatcher` subclass |
| `state_serializer_class` | `gandalf.runtime.StateSerializer` | a `StateSerializer` subclass |
| `step_router_class` | `gandalf.wizard.StepNameRouter` | a class with `resolve()`, `reverse()`, `clean_url_kwargs()` |
| `file_storage_class` | `gandalf.file_storage.WizardFileStorage` | a class with `save()`, `open()`, `delete()`, `delete_run()` |
| `observer_class` | `gandalf.observers.WizardObserver` | a `WizardObserver` subclass |

**Returns** — a `ConfiguredWizard`; the configured values are its
attributes of the same names.

**Raises**

- `ImproperlyConfigured` — `storage_class` was passed (see
  [`storage_class`](#storage_class) below).
- `ImproperlyConfigured` — a step is a bare `forms.Form` and
  `template_name` is `None`: *"Wizard.configure() must receive template_name
  when generating FormView steps from Form classes."*
- `ImproperlyConfigured` — called on a `ConfiguredWizard`: *"ConfiguredWizard
  instances cannot be configured."*

### `template_name`

The template every *generated* step view renders. Default `None`.

- Required when any step is declared with a bare `forms.Form`; the
  `Configurer` hands it to `form_view_factory` for each such step.
- Not applied to a step that brings its own `FormView`: that view keeps its
  own `template_name`, and needs one.
- `WizardViewSet.configure_wizard()` copies the viewset's `template_name`
  attribute into this key when it configures a bare `Wizard`. It does
  nothing to a `ConfiguredWizard`, so for one of those set `template_name`
  in `.configure()`; a `template_name` on the viewset is then ignored.

### `form_view_factory`

The callable that turns a bare `forms.Form` into a step view. Default
`gandalf.form_views.form_view_factory`.

**Contract** — `factory(form_class, *, template_name) -> type[FormView]`.
Called once per `Form` step at configure time (and once per step of each
expansion when it is built). The default returns a `StepFormView` subclass
named `<FormName>View` in the form's module, with `form_class` and
`template_name` set.

The generated class is what the walk dispatches, so a factory is the place
to give every generated step a mixin — extra context, a success message,
a base class of your own — without declaring a view per step. A
`StepFormView` subclass is the right base: it already answers every POST
with the no-op redirect the walk reads as "this answer stands".

### `cursor_walker_class`

The interpreter that replays stored answers over the declaration tree,
places a submission, and finds the cursor. Default `gandalf.runtime.CursorWalker`.

**Contract** — constructed by `Run.walk()` as
`cls(dispatcher, entries, args, kwargs, run, claim=, submission=,
files=, metadata=)`; must expose `walk(tree)`, `cursor() -> Cursor`, and the
attributes `reached`, `target`, `replaced_refs`. Subclass `CursorWalker`
and override the `visit_*` methods rather than writing one from scratch.

### `step_dispatcher_class`

The HTTP adapter: builds the request a step view is dispatched with, calls
the view, decides whether the response means the step is satisfied, and
renders a cursor. Default `gandalf.runtime.StepDispatcher`.

**Contract** — constructed once per run as `cls(run)` (memoised on
`Run.dispatcher`); methods `dispatch(step, request, *args,
initial=None, **kwargs)`, `build_request(method, submission=None,
files=None)`, `response_satisfies_step(response) -> bool` (the default: any
3xx), `render_cursor(cursor, *args, **kwargs)`.

### `state_serializer_class`

The reducer that flattens a runtime tree into the JSON-shaped state storage
keeps. Default `gandalf.runtime.StateSerializer`.

**Contract** — constructed with no arguments; `reduce(runtime_head) ->
State`. The default writes `{"step": data[, "files": refs][, "meta": ...]}`
per step, `{"branch": {arm_id: [...]}}` per branch (dormant arms carried
back untouched), `{"expand": [...]}` per expansion, and trims trailing holes
at every level. A replacement must produce something the walker can read
back; see [Storage](storage.md) for the shape.

### `step_router_class`

Maps a URL step segment to a step-context lookup and back. Default
[`StepNameRouter`](wizard.md#stepnamerouter), which routes on the `name`
context.

**Contract** — constructed with no arguments; `resolve(url_kwargs) ->
Context | None`, `reverse(step) -> str | None`, `clean_url_kwargs(url_kwargs)
-> dict`. The viewset uses `reverse()` to validate that every declared step
routes and every segment is unique, so a router that returns `None` for a
step makes resolution fail with `ImproperlyConfigured`.

### `file_storage_class`

Where uploads go. Default `gandalf.file_storage.WizardFileStorage`, which
wraps `django.core.files.storage.default_storage` under a `gandalf/<run_id>/`
prefix.

**Contract** — constructed once per run with no arguments (memoised on
`Run.file_storage`); `save(run_id, uploaded_file) -> FileRef`,
`open(ref) -> UploadedFile`, `delete(ref)`, `delete_run(run_id)`. A
`FileRef` is `{tmp_name, name, content_type, size, charset}`. Subclassing
`WizardFileStorage` and passing a different backend to `__init__`, or
overriding `prefix`, covers most cases. See [File uploads](file-uploads.md).

### `observer_class`

Told what happened to a run, as it happens, without being shown the
answers. Default `gandalf.observers.WizardObserver`, which does nothing.

**Contract** — constructed once per run on first use as `cls(run_id)`;
`submission(step, accepted, metadata)` fires once per placement (not per
replay), `run_completed()` fires after `done()`. It must not raise. See
[Observers](observers.md).

### `storage_class`

**Not a configure key.** Set it on the viewset:

```python
class ApplicationViewSet(WizardViewSet):
    storage_class = DurableStorage
```

Default `gandalf.storage.SessionStorage`. Passing it to `.configure()`
raises `ImproperlyConfigured`: *"storage_class belongs on the WizardViewSet,
not the wizard. Storage has to exist before the wizard does — get_wizard()
is handed a Run that can already read stored state — so the wizard
cannot supply it."* A dynamic `get_wizard()` reads the run's stored state to
decide its shape, and the run is created and retrieved before the wizard is
resolved, so storage cannot be a property of the thing it precedes.

**Contract** — the `gandalf.types.WizardStorage` protocol: constructed as
`cls(context: WizardContext)`; `initialise_run() -> run_id`,
`retrieve_run(run_id) -> run_id` (raising `RunNotFound`),
`get_run_data(run_id)`, `get_state(run_id)`, `set_state(run_id, state)`,
`get_run_metadata(run_id)`, `set_run_metadata(run_id, metadata)`,
`delete_run(run_id)`, `complete_run(run_id)`, `is_run_complete(run_id) ->
bool`. `SessionStorage` keeps at most `max_completed_runs = 25` tombstones.
See [Storage](storage.md).

### `journey_store_class`

Task lists and their sections keep journey state — which run each section
is on, its stash, the journey's decided data — in a store separate from run
storage. It is a class attribute of the root task list viewset, handed to
every entry it builds, not a configure key:

```python
class GrantApplicationViewSet(TaskListViewSet):
    journey_store_class = DurableJourneyStore
```

Default `gandalf.storage.SessionCollectionStore`. Built per request as
`cls(WizardContext.from_request(request), journey)`.

**Contract** — the `gandalf.types.JourneyStore` protocol (`get_run`,
`set_run`, `clear_run`, `get_stash`, `has_stash`, `put_stash`,
`delete_stash`, `keys`, `data`, `complete`, `is_complete`); a tree with an
add-another list needs the `CollectionStore` extension (`item_ids`, `has_item`,
`add_item`, `remove_item`, `get_item_title`, `set_item_title`,
`is_declared_done`, `set_declared_done`). See [Journey store](journey-store.md)
and [Task lists](tasklists.md).

### `WizardViewSet.configure_wizard(wizard)`

What the viewset does with what `get_wizard()` returns:

| Given | Result |
| --- | --- |
| a `ConfiguredWizard` | returned unchanged — no key on the viewset reaches it |
| a `Wizard` | `wizard.configure(template_name=self.template_name)` if the viewset has a `template_name`, else `wizard.configure()` |
| anything else | `TypeError` *"WizardViewSet.wizard must be a Wizard or ConfiguredWizard"* |

The result is cached on the view instance for the request, keyed on the
identity of the declaration it came from, so a static `wizard` attribute is
configured once per request even though a POST resolves twice.

### Django settings

Gandalf's defaults are session-backed, and a step is an ordinary Django
view rendering an ordinary template. The settings that matter:

| Setting | Needed for |
| --- | --- |
| `"django.contrib.sessions"` in `INSTALLED_APPS` | `SessionStorage`, `SessionJourneyStore`, `WizardFileStorage` refs — every default store lives in the session |
| `"django.contrib.sessions.middleware.SessionMiddleware"` in `MIDDLEWARE` | `request.session` on every wizard request; storage sets `session.modified` so the middleware saves it |
| `"django.template.context_processors.request"` in `TEMPLATES[...]["OPTIONS"]["context_processors"]` | templates that read `{{ request.run.back_url }}`, `{{ request.run.run_url }}` or `{{ request.run.path }}` |
| `"django.middleware.csrf.CsrfViewMiddleware"` | ordinary POST protection; the walk strips the CSRF token before storing a submission |
| `DEFAULT_FILE_STORAGE` / `STORAGES["default"]` | where `WizardFileStorage` puts uploads |

Listing `gandalf` in `INSTALLED_APPS` is not required — the package ships no
models, templates or static files. The cookie session backend caps a session
at 4KB; a wizard of any size wants a server-side `SESSION_ENGINE` (the test
suite uses `django.contrib.sessions.backends.cache`).

**Versions** (from `pyproject.toml`): Python 3.10 to 3.14; Django 4.2, 5.2
and 6.0 (`django>=4.2,<6.1`). The `agent` extra adds
`pydantic-ai-slim[ag-ui]~=2.30` for `gandalf.contrib.agent`; the core
depends on Django alone.

---

## Usage

### Configuring on the viewset only

```python
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    wizard = Wizard().step(ApplicantForm, name="applicant").step(EmailForm, name="contact")
```

The viewset configures the bare `Wizard` with its `template_name` and every
other default.

### Configuring the wizard, with the template alongside

```python
from gandalf.observers import WizardObserver
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class CountRejections(WizardObserver):
    def submission(self, step, accepted, metadata):
        if not accepted:
            statsd.increment("grants.rejected", tags=[f"step:{step.context['name']}"])


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
        .configure(
            template_name="grants/step.html",   # the viewset will not add it
            observer_class=CountRejections,
        )
    )
```

### A factory that decorates every generated step

```python
from gandalf.form_views import StepFormView
from gandalf.wizard import Wizard


class GrantStepView(StepFormView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["programme"] = self.request.run.metadata.get("programme")
        return context


def grant_form_view_factory(form_class, *, template_name):
    return type(
        f"{form_class.__name__}View",
        (GrantStepView,),
        {"form_class": form_class, "template_name": template_name},
    )


wizard = (
    Wizard()
    .step(ApplicantForm, name="applicant")
    .configure(template_name="grants/step.html", form_view_factory=grant_form_view_factory)
)
```

### Routing on a different context key

```python
from gandalf.wizard import StepNameRouter, Wizard


class SlugRouter(StepNameRouter):
    context_key = "slug"


wizard = (
    Wizard()
    .step(ApplicantForm, name="applicant", slug="about-you")
    .step(EmailForm, name="contact", slug="how-to-reach-you")
    .configure(template_name="grants/step.html", step_router_class=SlugRouter)
)
```

Every step now needs a `slug`; `name` is still what `find_step(name=...)`
and `on_field` read.

### Uploads on a separate backend

```python
from django.core.files.storage import FileSystemStorage

from gandalf.file_storage import WizardFileStorage
from gandalf.wizard import Wizard


class ScratchFileStorage(WizardFileStorage):
    def __init__(self, backend=None):
        super().__init__(backend or FileSystemStorage(location="/srv/grants/scratch"))


wizard = (
    Wizard()
    .step(SupportingDocumentForm, name="documents")
    .configure(template_name="grants/step.html", file_storage_class=ScratchFileStorage)
)
```

---

## Troubleshooting

### `ImproperlyConfigured: Wizard.configure() must receive template_name`

A step declared with a bare `forms.Form` has no template to render. Either
set `template_name` on the viewset (for a bare `Wizard`), pass it to
`.configure()` (for a pre-configured wizard), or declare the step with a
`StepFormView` that carries its own.

### I set `template_name` on the viewset but the steps render another template

The viewset's `wizard` is already a `ConfiguredWizard`, and
`configure_wizard()` returns one unchanged. Move `template_name` into the
`.configure()` call.

### `ImproperlyConfigured: storage_class belongs on the WizardViewSet`

`storage_class` was passed to `.configure()`. Set it as a class attribute on
the viewset instead; the run's storage has to exist before `get_wizard()` is
called.

### My `.configure(observer_clas=...)` had no effect

Unknown keys are stored and ignored, not rejected. Check the spelling
against the table above.

### `TypeError: WizardViewSet.wizard must be a Wizard or ConfiguredWizard`

`wizard` (or `get_wizard()`'s return) is something else — commonly a
declaration tree or a run. Return the `Wizard` value itself.

### Answers vanish between requests

Sessions are not being saved: `SessionMiddleware` is missing, or the
session backend is unavailable. The walk writes state to `request.session`
and relies on the middleware to persist it.

---

**Learn:** [Chapter 10 — Completion hooks and metadata](../learn/10-completion-hooks-and-metadata.md) · **Related:** [Wizard](wizard.md), [`WizardViewSet`](viewsets.md), [Storage](storage.md), [File uploads](file-uploads.md), [Observers](observers.md), [Journey store](journey-store.md)
