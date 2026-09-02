# `WizardViewSet`

`gandalf.viewsets` — the Django view that publishes a wizard's URLs, runs it
one request at a time, and completes it once.

```python
from gandalf.viewsets import WizardViewSet
```

---

## Reference

### `class WizardViewSet(View)`

One viewset serves three URLs: the start URL that mints a run, the run URL
that redirects to wherever the run has got to, and the step URL that renders
one step. Subclass it, set `url_name`, give it a wizard, and define `done()`.

**Attributes**

| Attribute | Default | What it is |
| --- | --- | --- |
| `url_name` | `None` | **Required.** The name of the start URL, verbatim; `-run` and `-step` are derived from it. `urls()` and the three URL hooks raise `ImproperlyConfigured` without it. |
| `wizard` | *(undeclared)* | A `Wizard`. Read by the default `get_wizard()`; a viewset with neither raises `ImproperlyConfigured` on its first request. |
| `template_name` | `None` | The template every step generated from a bare `Form` renders with. A step that brings its own view sets its own. Required as soon as a step is a bare `Form`. |
| `storage_class` | `SessionStorage` | Where runs are kept. Instantiated once per request with the request's `WizardContext`, before the wizard is resolved, so `get_wizard()` can read state from it — see [Storage](storage.md). |
| `file_storage_class`, `observer_class`, `form_view_factory`, `cursor_walker_class`, `step_dispatcher_class`, `state_serializer_class`, `step_router_class` | the library's | The wizard's other seams, each with a default; see [Configuration](configuration.md). A `Wizard` is a value and carries none of them. |
| `reserved_url_kwargs` | `frozenset({"run_id", "gandalf_step"})` | URL kwargs owned by the patterns `urls()` publishes. Everything else the request captures is mount-prefix context. |

Instance attributes Django sets in `setup()` — `request`, `args`, `kwargs` —
are available in every hook, so `self.kwargs["fund"]` reads a mount-prefix
kwarg.

### `WizardViewSet.urls()` *(classmethod)*

**Returns** a list of three `URLPattern`s, derived from `url_name`. Mount with
`path("apply/", include(MyViewSet.urls()))`.

| URL name | Pattern | Captures | What it is |
| --- | --- | --- | --- |
| `<url_name>` | `""` | — | the start URL — begins a fresh run |
| `<url_name>-run` | `<uuid:run_id>/` | `run_id` | a run — redirects to wherever it has got to, or completes |
| `<url_name>-step` | `<uuid:run_id>/<slug:gandalf_step>/` | `run_id`, `gandalf_step` | one step of a run |

The step segment is whatever the wizard's `step_router_class` (default
`StepNameRouter`) reverses from each step's `name` context. When the wizard
is resolved every step in the declared tree is checked for a reversible,
unique segment; an unnamed or duplicated step raises `ImproperlyConfigured`.

**Raises** `ImproperlyConfigured` — *"WizardViewSet.urls() requires url_name
to be set."*

**Caveats**

- The names are global and the URL hooks reverse them unprefixed. Mounting
  under a namespace (`include((patterns, "grants"))`) breaks the wizard's own
  redirects — the first one raises `NoReverseMatch` — unless all three URL
  hooks are overridden to reverse `"grants:<url_name>"` and friends. To avoid
  a name clash, prefix `url_name` instead; it needs no overrides.
- The mount prefix may capture kwargs of its own
  (`path("funds/<slug:fund>/", include(...))`). They are forwarded into every
  reverse by `get_url_kwargs()`, and handed to each step view as view kwargs.

### `get_url_kwargs()`

**Returns** the request's captured URL kwargs minus `reserved_url_kwargs` —
the mount-prefix context every reverse of this wizard's URLs needs. Reads
`self.kwargs`; returns `{}` on a viewset with no request. Override when
reversing needs context the URL does not capture.

### `get_start_url()`

**Returns** `reverse(url_name, kwargs=self.get_url_kwargs())`.

Called by the default `run_unavailable()`, so it is where a request for a
run that cannot be continued lands.

### `get_wizard_url(run_id)`

**Returns** `reverse(f"{url_name}-run", kwargs={..., "run_id": run_id})`.

Called for the redirect after the start URL mints a run, for a redirect whose
cursor has no step left to land on, and for `run.run_url`.

### `get_step_url(run_id, step_segment)`

**Returns** `reverse(f"{url_name}-step", kwargs={..., "run_id": run_id,
"gandalf_step": step_segment})`.

Called for every step-to-step redirect, and behind `run.step_url()`,
`entry_url()` and `back_url`.

All three URL hooks raise `ImproperlyConfigured` — *"Set url_name (or
override get_…_url) on this WizardViewSet."* — when `url_name` is `None`.
They are instance methods that read `self.kwargs` off a live request; from
anywhere else (an email, a management command) reverse the name with explicit
kwargs.

### `get_wizard(run)`

Per-request hook returning the wizard to run for this dispatch.

**Parameters** — `run`: the run being resolved. Exposes
`run.context` (request, actor, session, `url_kwargs`) and — once a
run has been retrieved or seeded — `get_state()` / `get_run_data()` /
`metadata`. Under `begin()` or the start URL the run is freshly minted, so
its state is `[]`; under `resolve()` there is no run at all.

**Returns** a `Wizard`. The default returns the `wizard` class attribute.

**Raises** `ImproperlyConfigured` — *"… has no wizard to run. Define
….wizard as a Wizard declaration, or override ….get_wizard() to build one
per request."*

**Caveats**

- Called at least once per request, and twice on a POST: once before the
  submission is placed, and again after it is persisted, so a wizard whose
  shape depends on the answer just given is re-walked before completion is
  judged. Returning the same object both times skips the second walk; a
  plain `Wizard` class attribute does this automatically.
- Called after the run is retrieved (`inspect()`, GET, POST) or seeded
  (`reopen()`), so it may read stored state to decide the tree.

### `configure_wizard(wizard)`

Turns the declaration `get_wizard()` returned into the `ConfiguredWizard` a
run holds as `run.wizard`, from this viewset's attributes: `template_name`
for the steps it generates, and every other seam in
[Configuration](configuration.md). The one place a `ConfiguredWizard` is
built.

The result is kept by the viewset *class*, keyed on the declaration
object, so a static `wizard` attribute is configured once and is the same
object on every request — which is what lets a POST that re-resolves to
the same wizard skip its refresh walk. A dynamic `get_wizard()` returns a
new declaration each call and gets no reuse.

**Raises** `TypeError` — *"WizardViewSet.wizard must be a Wizard"*.

### `context_for(request)`

**Returns** `WizardContext.from_request(request, **self.get_url_kwargs())` —
the environment this request implies. GET and POST build their `Run`
from it. Override to build the context differently (a different actor, a
session that is not the request's).

### `run_started(run)`

A fresh run of this wizard was just created. Does nothing by default.

The only hook that fires **exactly once per run**: a run is minted once, so
this is called once — unlike a step view, which is re-dispatched on every
later request as stored answers are replayed. It is handed a run that has an
id and a resolved wizard, so it can read `run.wizard` and write
`run.metadata` — the place to open a record outside the wizard and
remember it.

| Fires from | Does not fire from |
| --- | --- |
| the start URL, `begin()`, `begin_for()` (and `RunDriver.begin()`, which uses them) | `inspect()`, `inspect_for()`, `reopen()`, `resurrect()`, `resolve()`, any GET or POST of an existing run |

**Caveats**

- The start URL mints a run and redirects, so this fires for a drive-by
  visit that answers nothing. If that is too expensive to do speculatively,
  do it on first answer instead — from the first step's `form_valid()`,
  guarded on the metadata bag.
- Unlike an observer, it may raise. A raise propagates to whoever asked for
  the run, so a `run_started()` that cannot set its record up refuses to
  start the run.
- A run seeded from a stash is a continuation, not a start: its metadata
  comes back with its answers, so firing here would open a second record
  every time a task list section is re-entered.

### `done(run)`

Called once, when a walk finds every step satisfied. **Must be overridden**:
the default raises `NotImplementedError` — *"WizardViewSet subclasses must
define done()."*

**Parameters** — `run`: the completed run. `run.path` is
the answered steps in order; `MergeCleanedData().reduce(run.path)`
folds their `cleaned_data` into one dict; `run.metadata` is the
run's bag. See [`Run`](run.md).

**Returns** the `HttpResponseBase` to send. A redirect, an `HttpResponse`, or
a `TemplateResponse` — the last is rendered later by Django's middleware, and
the run stays readable until it has (see `finish()`).

### `finish(run)`

Completes the run. Called by GET and POST when the cursor has no step left;
also the programmatic completion for a caller driving a run outside a
dispatch — reach a cursor whose `node` is `None`, then call this.

In order:

1. `response = self.done(run)`
2. `run.keep_readable()` — pins the walked tree so a deferred
   completion page can still iterate `path`.
3. Uploaded files are swept: immediately for a plain response, or in a
   post-render callback for a `SimpleTemplateResponse`, since a completion
   template may still open a file step's `.form`.
4. `run.complete()` — the tombstone. The answers are discarded, the
   metadata bag is kept, and the run stays addressable.

**Returns** the response `done()` returned.

**Caveats**

- The tombstone is written after `done()` returns, so a `done()` that raises
  leaves the run's answers stored and the run resumable. It is *not*
  deferred with the file sweep: a completion template that raises must not
  leave a run whose `done()` can fire a second time.
- A programmatic caller that drops an unrendered `TemplateResponse` leaves
  the run's uploads behind; anything driving a run headlessly wants a
  rendered or plain response from `done()`.

### `run_unavailable(run, reason)`

Response for a run this request cannot continue. Runs *before* the wizard is
resolved, so `get_wizard()` is never asked to read a run that has no state.

**Parameters**

- `run` — the run. For `"completed"`, `run.metadata` is
  still readable, so a completion page can name what the run created; for
  `"unknown"`, `retrieve()` raised before anything was set, so
  `run.run_id` is `None`; the id asked for is `self.kwargs["run_id"]`.
- `reason` — a `RunUnavailable` (from `gandalf.viewsets`), one of:

| `reason` | Meaning |
| --- | --- |
| `RunUnavailable.COMPLETED` | The run finished; `done()` has already fired for it. |
| `RunUnavailable.UNKNOWN` | Storage raised `RunNotFound`: never started, obliterated, or lost with an expired session. |

  Each member is also a `str` equal to its lowercase name, so an existing
  `reason == "completed"` still holds; the member is what a type-checker
  can vouch for.

**Returns** an `HttpResponseBase`. The default is
`redirect(self.get_start_url())`, so refreshing a completion page quietly
begins a fresh run rather than re-firing `done()`'s side effects. Override to
render a completion page, raise `Http404`, or treat the two reasons
differently.

### `for_context(context)` *(classmethod)*

**Parameters** — `context`: a `WizardContext`.

**Returns** `(view, run)` — an instance of this viewset set up with
`context.request` (or a fabricated request when the context has none) and
`context.url_kwargs`, and a `Run` on the viewset's `storage_class`.
Nothing is resolved, retrieved or minted. The door a caller with no request
comes through — `gandalf.driver` uses it.

### `begin_for(context)` / `inspect_for(context, run_id)` / `resolve_for(context)` *(classmethods)*

The `*_for` variants of `begin()`, `inspect()` and `resolve()`: same
behaviour, taking a `WizardContext` instead of a request, and returning the
`(view, run)` pair rather than the `Run` alone. Reach for
them when the view itself is wanted — to call `view.finish(run)`,
for instance. `begin_for()` fires `run_started()`; the other two do not.

### `begin_driven_for(context)` / `inspect_driven_for(context, run_id)` *(classmethods)*

The same pair with `check_door()` asked first — what
[`RunDriver`](driver.md) uses, and the only callers that do. A wizard
reached over HTTP comes through a dispatch, and whatever guards it guards
it there; a caller with no request dispatches nothing, so the rules are
asked here instead.

`begin_driven_for()` checks before the run is minted and
`inspect_driven_for()` before it is retrieved, so a refusal leaves nothing
behind and a door that has shut since the run started shuts on the run too.

### `check_door()`

Refuse a run this caller may not open, by raising `DoorRefused`. Does
nothing by default: a wizard mounted on its own is open to whoever can
reach its URL, and that is the whole of its rule.

[`JourneyScoped`](tasklists.md) implements it over the journey's store,
which is what makes a submitted journey, a `hidden()` section and a
`blocked()` one closed to a driver as well as to a browser.

### `DoorRefused`

`Exception` with a `reason: str`. Re-exported from
[`gandalf.driver`](driver.md), which is where callers meet it.
[`EntryUnavailable`](tasklists.md) holds the reasons a task list raises.

### `begin(request, **url_kwargs)` *(classmethod)*

A fresh run, returned rather than redirected to — what the start URL does,
minus the redirect. Mints the run, resolves the wizard against it, fires
`run_started()`.

**Parameters** — `request`; `url_kwargs`: mount-prefix context, forwarded
into every reverse via `get_url_kwargs()`.

**Returns** a `Run` with `run_id` set, `get_state() == []`, and
`entry_url()` pointing at its first step.

### `inspect(request, run_id, **url_kwargs)` *(classmethod)*

This wizard bound to an existing run, outside its own request cycle.
Retrieves the run, *then* resolves the wizard — so a dynamic `get_wizard()`
reads the run's state. Walks nothing: a caller that only wants `get_state()`
or `is_complete` pays a storage read and no form validation.

**Returns** a `Run` on which `cursor()`, `path`, `step_url()`,
`entry_url()` and `run_url` work as they do inside a dispatch.

**Raises** `RunNotFound` (`gandalf.storage`) for a run this storage does not
hold. A tombstoned run is *found* — it stays addressable — so check
`is_complete` before running it, exactly as a dispatch does.

### `reopen(request, payload, expected_label=None, **url_kwargs)` *(classmethod)*

A fresh run seeded from a stash payload — the run behind `resurrect()`.
Seeds *then* resolves, unlike `inspect()`: the state a dynamic
`get_wizard()` reads is the state the payload just supplied. Does not fire
`run_started()`.

**Parameters** — `payload`: a `Stash` from `run.stash()`;
`expected_label`: refuse a payload whose label differs.

**Returns** a `Run`.

**Raises** `InvalidStash` (`gandalf.runtime`) — before any run is created —
when the payload is malformed, of an unsupported version, or its label does
not match. See [Stashing](stashing.md).

### `resurrect(request, payload, step=None, expected_label=None, **url_kwargs)` *(classmethod)*

`reopen()` plus `entry_url(step)`: seed a run and return the URL to send the
user to.

**Parameters** — `step`: the URL segment to land on. Without it, the cursor's
step, or — for a stash whose every answer validates — the first step on the
active route.

**Returns** a step URL (`str`), never the bare run URL: a resurrected run's
answers all validate, so a GET there would walk straight to completion and
fire `done()` before the user edited anything. Only a wizard with no steps at
all falls back to the run URL. `None` when no URL reverser is available.

**Raises** `InvalidStash`, as `reopen()`.

### `resolve(request, **url_kwargs)` *(classmethod)*

This wizard, bound but not started — no run is created and nothing is left
behind. The third door alongside `begin()` and `inspect()`: not to run a
wizard, nor to reach a run, but to ask what the wizard *is* —
`run.wizard.outline()` reads its declared shape from here.

**Returns** a `Run` with `run_id` unset. A dynamic `get_wizard()`
resolves with no stored state to read, so it describes itself as it would
begin.

### Request handling

Both handlers start the same way: build a `Run` from
`context_for(request)`; if the URL carries a `run_id`, retrieve it (an
unknown or completed run is answered by `run_unavailable()` and goes no
further); resolve the wizard.

| URL | GET | POST |
| --- | --- | --- |
| start | Mint a run, resolve, fire `run_started()`, redirect to `get_wizard_url(run_id)`. | Not supported: `post()` requires `run_id`, and a POST without one raises `TypeError`. Submissions go to a step URL. |
| run | Walk the stored answers. Cursor at a step: redirect to its step URL. No step left: `finish()`. | Redirect to the cursor's step URL. Stores nothing. |
| step | A *claim*. Walk with the claim; if the walk reaches the named step it renders — the cursor's step empty, an already-answered step pre-filled with its stored submission (`initial`) — otherwise redirect to the cursor. | A claim, with the submission placed at the named step. Not reached: uploads discarded, redirect to the cursor, nothing stored. Reached and the step escaped: settle the escape and redirect (see [Escapes](escapes.md)). Otherwise persist, re-resolve the wizard against the new state, and redirect to the next step — or `finish()` when there is none. |

A step that is unknown, not yet reached, or parked in a dormant branch arm
is never rendered; the URL is a claim, not an instruction, so a stale link
cannot land an answer on the wrong step.

A submission that fails validation is still stored, so the redirect back to
the same step renders the form with its errors (post-redirect-get). A GET of
a completed run's step URL redirects to the run URL, and from there to
`finish()`.

**Completion is once-only.** The first walk that satisfies every step calls
`finish()`: `done()` fires, files are swept, the run is tombstoned. Every
later request for that `run_id` — run URL or any step URL, GET or POST — is
answered by `run_unavailable(reason="completed")` without reaching the
wizard, so a stale tab cannot submit twice and a refreshed completion page
cannot re-run side effects.

**Escapes.** A `Park`, `Advance` or `Obliterate` raised while the submitted
step validates is caught around the POST: `Park` discards the submission and
its uploads, `Advance` persists it, `Obliterate` deletes the run; all three
then redirect to the escape's target. A bare `Escape` raises
`ImproperlyConfigured`. Nothing has been persisted when the escape is caught,
so `Park` declines to write rather than undoing one.

### Template context of a generated step view

A step declared from a form class gets a `FormView` generated by
`form_view_factory()`, with the viewset's `template_name`. It is dispatched as
an ordinary Django view, so its template context is Django's:

| Name | What it is |
| --- | --- |
| `form` | The step's form — unbound for the cursor's step, bound to `initial` for an answered one, with errors after a rejected POST. |
| `view` | The generated `FormView`. `view.request.run` and `view.kwargs` are reachable through it. |
| `request.run` | The `Run` for this run: `back_url` (the previous active-route step, `None` at the first), `run_url`, `step_url(step)`, `path`, `metadata`. Set on the request the step view is dispatched with — it is not a context variable, so reach it as `request.run` (with the request context processor) or `view.request.run`. |

The step view's own kwargs are the request's mount-prefix kwargs;
`gandalf_step` is stripped and `run_id` is not passed. A step that brings its
own `StepFormView` gets the same request and kwargs but its own
`template_name` — the viewset's does not reach it. See
[Step views](step-views.md).

---

## Usage

### A minimal viewset

```python
from django import forms
from django.http import HttpResponse
from django.urls import include, path

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard


class ApplicantForm(forms.Form):
    full_name = forms.CharField(label="Your full name")


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email address")


class GrantApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
    )

    def done(self, run):
        answers = MergeCleanedData().reduce(run.path)
        return HttpResponse(f"Application received from {answers['full_name']}")


urlpatterns = [
    path("apply/", include(GrantApplicationViewSet.urls())),
]
```

`{% url 'grant-application' %}` is the link to publish. The step template is
a plain form — `{% csrf_token %}{{ form.as_p }}` and a submit button.

### A wizard shaped by the request

```python
from django.urls import include, path

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class FundApplicationViewSet(WizardViewSet):
    url_name = "fund-application"
    template_name = "grants/step.html"

    def get_wizard(self, run):
        wizard = Wizard().step(ApplicantForm, name="applicant")
        if self.kwargs["fund"] == "arts":
            wizard = wizard.step(PortfolioForm, name="portfolio")
        return wizard.step(EmailForm, name="contact")

    def done(self, run):
        ...


urlpatterns = [
    path("funds/<slug:fund>/", include(FundApplicationViewSet.urls())),
]
```

`fund` is a mount-prefix kwarg: `get_url_kwargs()` forwards it into every
redirect, so a run started at `/funds/arts/` stays there, and
`self.kwargs["fund"]` is present on each request of the run. From outside,
`reverse("fund-application", kwargs={"fund": "arts"})`.

### Opening a record on start and submitting it on completion

```python
from django.http import Http404
from django.shortcuts import redirect

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData


class RecordedApplicationViewSet(WizardViewSet):
    url_name = "recorded-application"
    template_name = "grants/step.html"
    wizard = application_wizard

    def run_started(self, run):
        application = Application.objects.create(applicant=self.request.user)
        run.metadata["application_id"] = application.pk

    def done(self, run):
        application = Application.objects.get(pk=run.metadata["application_id"])
        answers = MergeCleanedData().reduce(run.path)
        application.submit(answers["email"])
        return redirect("application-received", pk=application.pk)

    def run_unavailable(self, run, reason):
        if reason == RunUnavailable.COMPLETED:
            return redirect(
                "application-received", pk=run.metadata["application_id"]
            )
        raise Http404("That application has expired.")
```

`run_started()` fires once per run; `done()` fires once per run; the
metadata bag survives completion, so the completed run's own page is still
reachable from `run_unavailable()`.

### Mounting under a namespace

```python
from django.urls import include, path, reverse

from gandalf.viewsets import WizardViewSet


class GrantApplicationViewSet(WizardViewSet):
    url_name = "application"
    ...

    def get_start_url(self):
        return reverse("grants:application", kwargs=self.get_url_kwargs())

    def get_wizard_url(self, run_id):
        return reverse(
            "grants:application-run",
            kwargs={**self.get_url_kwargs(), "run_id": run_id},
        )

    def get_step_url(self, run_id, step_segment):
        return reverse(
            "grants:application-step",
            kwargs={
                **self.get_url_kwargs(),
                "run_id": run_id,
                "gandalf_step": step_segment,
            },
        )


urlpatterns = [
    path("grants/", include((GrantApplicationViewSet.urls(), "grants"))),
]
```

Keeping the `get_url_kwargs()` call keeps mount-prefix support.

---

## Troubleshooting

### `ImproperlyConfigured: WizardViewSet.urls() requires url_name to be set.`

`urls()` derives all three URL names from `url_name`. Set it on the subclass.
The same attribute backs the three URL hooks, which raise *"Set url_name (or
override get_start_url) on this WizardViewSet."* and friends without it.

### `NoReverseMatch` on the first redirect after mounting under a namespace

The names `urls()` publishes are global and the default hooks reverse them
unprefixed, so `include((patterns, "ns"))` leaves `reverse("application-run")`
with nothing to find. Either drop the namespace and prefix `url_name` instead,
or override `get_start_url()`, `get_wizard_url()` and `get_step_url()` to
reverse the namespaced names, as in the example above.

### `done()` fired on a GET

A GET of the run URL walks the stored answers, and if every step is
satisfied the run completes — a GET is as good as a POST for that. This is by
design, and it bites in two places: a link *into* a run that points at the
bare run URL rather than a step (use `run.entry_url()`, which never
returns the run URL for a wizard with steps), and a resurrected stash whose
answers all validate (`resurrect()` returns a step URL for exactly this
reason). A step URL is always safe: it renders rather than completes.

### A completed run redirects to the start URL

That is the default `run_unavailable()`. After `done()` returns the run is
tombstoned, and every later request for it — run URL, any step URL, GET or
POST — is answered by `run_unavailable(reason="completed")` and sent to
`get_start_url()`, so a refresh begins a fresh run instead of re-firing
`done()`. Override `run_unavailable()` to render a completion page; the
run's `metadata` is still readable there.

### `ImproperlyConfigured: … has no wizard to run`

The default `get_wizard()` reads the `wizard` class attribute. Declare one,
or override `get_wizard()`.

### `ImproperlyConfigured: Every wizard step needs a routable name`

Every step is addressed by URL, so each needs a segment the router can
reverse. Declare steps with `.step(Form, name="...")`, and give each a
distinct name — *"Wizard step names must be unique"* is the same check.

---

**Learn:** [Chapter 1 — Steps and completion](../learn/01-steps-and-completion.md) · [Chapter 5 — A wizard per request](../learn/05-a-wizard-per-request.md) · [Chapter 10 — Completion hooks and metadata](../learn/10-completion-hooks-and-metadata.md) · **Related:** [`Wizard`](wizard.md), [`Run`](run.md), [Storage](storage.md), [Stashing](stashing.md), [Escapes](escapes.md), [Step views](step-views.md), [Run metadata](run-metadata.md), [Driver](driver.md)
