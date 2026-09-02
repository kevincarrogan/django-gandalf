# Configuration

The seams a wizard runs through, each with a default — all of them class
attributes of the [`WizardViewSet`](viewsets.md) that mounts it — plus the
Django settings a wizard needs.

```python
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    observer_class = CountRejections
    wizard = Wizard().step(ApplicantForm, name="applicant")
```

---

## Reference

A `Wizard` is a value: its shape, and nothing else. Everything a run of it
needs that is not its shape — the template its generated steps render
with, where its runs and uploads are kept, what watches it, the runtime
classes the walk is built from — is the view's, and is declared on the
viewset the way `template_name` is on any Django `FormView`. The same rule
a `Form` and a `FormView` follow, and the reason one wizard can be mounted
by two viewsets with two templates, or dropped into a task list where the
`SectionViewSet` in its slot supplies all of this.

Every attribute below is optional and independent. A section of a task
list declares them on its `SectionViewSet` subclass; a plain `Section(
wizard)` gets the page's `section_template_name` and every other default.

| Attribute | Default | Replacement must be |
| --- | --- | --- |
| `template_name` | `None` | a template path (`str`) |
| `storage_class` | `gandalf.storage.SessionStorage` | a class satisfying `gandalf.types.WizardStorage` |
| `file_storage_class` | `gandalf.file_storage.WizardFileStorage` | a class with `save()`, `open()`, `delete()`, `delete_run()` |
| `observer_class` | `gandalf.observers.WizardObserver` | a `WizardObserver` subclass |
| `form_view_factory` | `gandalf.form_views.form_view_factory` | callable `(form_class, *, template_name) -> type[FormView]` |
| `cursor_walker_class` | `gandalf.runtime.CursorWalker` | a `CursorWalker` subclass |
| `step_dispatcher_class` | `gandalf.runtime.StepDispatcher` | a `StepDispatcher` subclass |
| `state_serializer_class` | `gandalf.runtime.StateSerializer` | a `StateSerializer` subclass |
| `step_router_class` | `gandalf.wizard.StepNameRouter` | a class with `resolve()`, `reverse()`, `clean_url_kwargs()` |

The viewset applies them in [`configure_wizard()`](viewsets.md#configure_wizardwizard),
which turns the declaration `get_wizard()` returned into the
`ConfiguredWizard` a run holds as `run.wizard`. That happens once per
declaration per viewset class — a static `wizard` attribute is configured on
the first request and kept — so the routability checks in
[Validation at resolve time](wizard.md#validation-at-resolve-time) run then,
not at import.

### `template_name`

The template every *generated* step view renders. Default `None`.

- Required when any step is declared with a bare `forms.Form`; the
  `Configurer` hands it to `form_view_factory` for each such step. Its
  absence raises `ImproperlyConfigured` on the first request: *"A step
  declared from … needs template_name to generate its view."*
- Not applied to a step that brings its own `FormView`: that view keeps its
  own `template_name`, and needs one.
- On a `TaskListViewSet`, `section_template_name` is what reaches the
  sections built from plain wizards; a `SectionViewSet` subclass in a slot
  sets `template_name` itself.

### `storage_class`

Where runs are kept. Default `gandalf.storage.SessionStorage`.

Instantiated as `storage_class(context)` on every entry point — dispatch,
`begin()`, `inspect()`, `reopen()`, `resolve()` and the driver — *before*
the wizard is resolved, which is what lets a dynamic `get_wizard()` read
the run's stored state to decide its shape.

**Contract** — the `gandalf.types.WizardStorage` protocol: constructed as
`cls(context: WizardContext)`; `initialise_run() -> run_id`,
`retrieve_run(run_id) -> run_id` (raising `RunNotFound`),
`get_run_data(run_id)`, `get_state(run_id)`, `set_state(run_id, state)`,
`get_run_metadata(run_id)`, `set_run_metadata(run_id, metadata)`,
`delete_run(run_id)`, `complete_run(run_id)`, `is_run_complete(run_id) ->
bool`. `SessionStorage` keeps at most `max_completed_runs = 25` tombstones.
See [Storage](storage.md).

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

### `form_view_factory`

The callable that turns a bare `forms.Form` into a step view. Default
`gandalf.form_views.form_view_factory`.

**Contract** — `factory(form_class, *, template_name) -> type[FormView]`.
Called once per `Form` step when the wizard is configured (and once per
step of each expansion when it is built). The default returns a
`StepFormView` subclass named `<FormName>View` in the form's module, with
`form_class` and `template_name` set.

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

### `journey_store_class`

Task lists and their sections keep journey state — which run each section
is on, its stash, the journey's decided data — in a store separate from run
storage. It is a class attribute of the root task list viewset, handed to
every entry it builds:

```python
class GrantApplicationViewSet(TaskListViewSet):
    journey_store_class = DurableJourneyStore
```

Default `gandalf.storage.SessionItemStore`. Built per request as
`cls(WizardContext.from_request(request), journey)`.

**Contract** — the `gandalf.types.JourneyStore` protocol (`get_run`,
`set_run`, `clear_run`, `get_stash`, `has_stash`, `put_stash`,
`delete_stash`, `keys`, `data`, `complete`, `is_complete`); a tree with an
add-another list needs the `ItemStore` extension (`item_ids`, `has_item`,
`add_item`, `remove_item`, `get_item_title`, `set_item_title`,
`is_declared_done`, `set_declared_done`). See [Journey store](journey-store.md)
and [Task lists](tasklists.md).

### `WizardViewSet.configure_wizard(wizard)`

What the viewset does with what `get_wizard()` returns: builds a
`ConfiguredWizard` from the declaration and every attribute above. Anything
other than a `Wizard` raises `TypeError` *"WizardViewSet.wizard must be a
Wizard"*.

The result is kept by the viewset *class*, keyed on the declaration object,
so a static `wizard` attribute is configured once and every request of
every run hands back the same object — which is what lets a POST that
re-resolves to the same wizard skip its refresh walk. A dynamic
`get_wizard()` returns a new declaration each call and correctly gets no
reuse; the cache holds its keys weakly, so it leaves nothing behind.

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

### The template alone

```python
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    wizard = Wizard().step(ApplicantForm, name="applicant").step(EmailForm, name="contact")
```

Every other seam is its default.

### Watching a wizard

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
    template_name = "grants/step.html"
    observer_class = CountRejections
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
    )
```

### The same seams on a section of a task list

```python
from gandalf.tasklists import Section, SectionViewSet, TaskList


class SetupSection(SectionViewSet):
    wizard = setup
    template_name = "grants/step.html"
    observer_class = CountRejections


class GrantApplication(TaskList):
    setup = Section(SetupSection, title="Applying as")
```

The entry is unchanged; the section in its slot carries what a view
carries.

### A factory that decorates every generated step

```python
from gandalf.form_views import StepFormView
from gandalf.viewsets import WizardViewSet
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


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    form_view_factory = staticmethod(grant_form_view_factory)
    wizard = Wizard().step(ApplicantForm, name="applicant")
```

`staticmethod` because a plain function on a class body would be bound to
the view instance when read from it.

### Routing on a different context key

```python
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import StepNameRouter, Wizard


class SlugRouter(StepNameRouter):
    context_key = "slug"


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    step_router_class = SlugRouter
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant", slug="about-you")
        .step(EmailForm, name="contact", slug="how-to-reach-you")
    )
```

Every step now needs a `slug`; `name` is still what `find_step(name=...)`
and `on_field` read.

---

## Troubleshooting

### `ImproperlyConfigured: A step declared from … needs template_name to generate its view`

A step is a bare `Form` and the viewset has no `template_name`. Set one on
the viewset — or, for a section of a task list, `section_template_name`
on the page or `template_name` on the `SectionViewSet` in the slot — or
declare the step with a `FormView` of its own.

### `TypeError: WizardViewSet.wizard must be a Wizard`

`wizard` (or what `get_wizard()` returned) is not a `Wizard`. There is
nothing else to hand a viewset: a `ConfiguredWizard` is what the viewset
builds, not what it is given.

### A seam I set on the viewset is not applied to a section

The section has its own viewset. `TaskListViewSet` reaches its sections
with `storage_class`, `journey_store_class` and `section_template_name`;
any other seam goes on a `SectionViewSet` subclass in the entry's slot.

### An attribute I misspelt was silently ignored

Class attributes are Django's convention and Django's failure mode:
`observer_clas = …` is an attribute nothing reads. There is no check —
the same is true of `template_nam` on any `TemplateView`.

---

**Learn:** [Chapter 1 — Steps and completion](../learn/01-steps-and-completion.md) · **Related:** [`WizardViewSet`](viewsets.md), [`Wizard`](wizard.md), [Storage](storage.md), [File uploads](file-uploads.md), [Observers](observers.md), [Step views](step-views.md)
