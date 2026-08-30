# BoundWizard

`gandalf.runtime` — one run of a wizard, as code sees it: its stored
answers, the route they resolve to, its URLs and its lifecycle.

```python
from gandalf.context import WizardContext
from gandalf.runtime import (
    BoundWizard,
    InvalidStash,
    MergeCleanedData,
    Path,
    RuntimeStep,
    StepNotFound,
)
from gandalf.storage import RunNotFound
from gandalf.tree import MultipleStepsReturned
from gandalf.types import WizardRequest
```

---

## Reference

A `BoundWizard` is never constructed by application code. The viewset
builds one per request and hands it to every hook — `done(bound_wizard)`,
`run_started(bound_wizard)`, `run_unavailable(bound_wizard, reason)` — and a
step view reaches the same object as `self.request.wizard`. Walk-time code
(a branch predicate, a switch selector, an expand builder) receives a
[`WizardContext`](#wizardcontext) and reaches it as `context.run`. The
classmethods on [`WizardViewSet`](viewsets.md) (`begin`, `inspect`,
`reopen`, `resolve`, and their `*_for` variants) return one for programmatic
use.

### `BoundWizard(context, storage, wizard=None)`

**Attributes — for application code**

| Attribute | Type | What it is |
| --- | --- | --- |
| `run_id` | `str` | The storage-minted id of this run. Opaque; need not be a UUID. |
| `wizard` | `ConfiguredWizard` | The resolved declaration — `wizard.tree` is the full declared structure, dormant arms included. |
| `context` | `WizardContext` | The environment the run is walked in. `context.run is bound_wizard`. |
| `path` | `Path` | The resolved route: the answered steps in walk order. See [`Path`](#path). |
| `metadata` | `RunMetadata` | The run's write-through bag. See [Run metadata](run-metadata.md). |
| `is_complete` | `bool` | `True` once the run has finished and been tombstoned. |
| `run_url` | `str \| None` | The bare run URL — redirects to the current step, so it is a "return to where I was" link. |
| `back_url` | `str \| None` | The previous active-route step's URL for the step being rendered. |
| `file_storage` | `WizardFileStorage` | Built once from `wizard.file_storage_class`. `open(ref)`, `save(run_id, file)`, `delete(ref)`, `delete_run(run_id)` — see [File uploads](file-uploads.md). |
| `observer` | `WizardObserver` | Built once from `wizard.observer_class(run_id)`; the no-op base unless configured. See [Observers](observers.md). |

**Attributes — runtime internals.** `storage` (the `WizardStorage`
instance), `urls` (the viewset acting as URL reverser; `None` outside a
viewset, which is why every URL property can be `None`), `dispatcher`
(the `StepDispatcher`), `runtime_tree` (the walked tree behind `path`,
preserved regions included), `rendering` (the `tree.Step` this request is
rendering, `None` outside a step render).

### `get_state()`

**Returns** the raw stored state list — see [The stored state
shape](#the-stored-state-shape). `[]` for a fresh run and for a completed
one.

### `get_run_data()`

**Returns** everything storage keeps about the run: `{"state": [...],
"meta": {...}}` while it is live (either key absent until first written), or
`{"completed": True}` once tombstoned, plus `"meta"` when the bag is
non-empty. Raises `RunNotFound`
for an id the storage does not hold.

### `stash(label=None)`

A caller-owned, JSON-safe payload of this run's answers, ready for
`resurrect()`.

**Parameters**

- `label` — an opt-in guard. State aligns with the wizard tree
  positionally, so a resurrection should be refused when the payload came
  from a differently-shaped wizard. Written into the payload only when
  given.

**Returns** `{"version": 1, "state": [...]}` plus `"meta"` when the run's
metadata bag is non-empty and `"label"` when one was given. File refs are
stripped at every depth — active and dormant arms, expansions — because
the bytes are deleted at completion; the step data itself is kept, so a
required file field parks the resurrected cursor there. Any CSRF token an
earlier version stored is dropped. The stored state is not mutated.

**Caveats** — callable inside `done()`: completion tears the run down only
after `done()` returns. See [Stashing](stashing.md).

### `resurrect(payload, expected_label=None)`

Seed a fresh run from a stash payload.

**Parameters**

- `payload` — a dict from `stash()`.
- `expected_label` — when given, the payload's `label` must equal it.

**Returns** the new `run_id`, which is also set on this `BoundWizard`.

**Raises** `InvalidStash` — before any run is created — when the payload is
not a dict with a `state` list, when its `version` is not `1`, or when the
label does not match. The state and metadata are deep-copied in, so
resurrecting one payload twice yields two independent runs. Every answer
is still re-proved by the walk; the payload is trusted no further than a
session's own state. `run_started()` does not fire.

### `obliterate()`

Delete the run's uploaded files and its stored state, leaving nothing to
tell it apart from a run that never existed. Contrast `complete()`, which
leaves a tombstone.

### `complete()`

Tombstone the run: `storage.complete_run(run_id)` discards the answers,
keeps the metadata bag and marks it finished, then
`observer.run_completed()` fires. Called by `WizardViewSet.finish()` after
`done()` returns; application code calls `finish()` rather than this.

### `keep_readable()`

Pin the run's walked tree so `path` keeps answering after `complete()`.

`done()` may return a `TemplateResponse`, which Django renders after the
view has returned — by which point the run has been tombstoned. `finish()`
calls this after `done()` returns and before `complete()`, so a completion
template that iterates `bound_wizard.path` still finds the answers. The
walk it costs is the run's last. Application code calls it only when
driving completion by hand.

### `step_url(step)`

**Parameters** — `step`: a `RuntimeStep` or the `tree.Step` behind one.

**Returns** that step's URL — a GET there renders the step pre-filled, so
it is the "change this answer" link. Needs no render context. `None`
without a URL reverser.

### `entry_url(step=None)`

The link *into* a run from outside it: a task list row, a resurrected stash, a
link in an email. Never the bare run URL, because on a run whose answers
all validate that URL redirects straight to completion and fires `done()`.

**Parameters** — `step`: a URL segment. Walks nothing when given.

**Returns** the URL of `step`; otherwise the cursor step's URL (one walk);
for a run whose answers all validate, the first step on the active route;
`run_url` only for a wizard with no steps at all. `None` without a URL
reverser.

### `run_url`

`None` without a URL reverser.

### `back_url`

`None` without a URL reverser or render context, at the first step, or
when the predecessor is inside a preserved branch region. Branch-aware:
the predecessor is the previous step in active-route order.

### `walk(*args, claim=None, submission=None, files=None, metadata=None)` — internal

The whole operation. Replays the stored answers in order through their
real form views; where `claim` (a context dict or a `tree.Step`) names a
step, places `submission` there instead of what is stored; stops at the
first step that does not hold and *seals* — later entries ride through
verbatim. Returns a `Walk` with `cursor` (`node` is the step to render or
`None` when every answer holds; `state` the walked tree; `response` the
errored render for an invalid stored answer; `escapes` any raised), plus
`reached`, `target` and `replaced_refs`. **Nothing is persisted.**

### `persist(walk)` — internal

Reduce `walk.cursor.state` back to a state list with
`wizard.state_serializer_class`, store it, then delete the file refs the
walk superseded — in that order, so nothing deletes a live file.

### `cursor(*args, **kwargs)` — internal

`walk(...).cursor`.

**Other internals** — `bind(wizard)`, `initialise()`, `retrieve(run_id)`
(raises `RunNotFound`), `walking(head)` (the context manager that exposes
the validated prefix to code running inside a walk), `previous_step`,
`mark_rendering` / `clear_rendering`, `render_step(...)` (raises
`StepNotFound` for a step the run cannot reach or that has no stored
answer), `store_uploads`, `delete_file_refs`, `cleanup_files()`,
`switch_value`.

### `Path`

The resolved route through a run: the answered steps in walk order, with
selected branch arms and expansions inlined. Reached as
`bound_wizard.path`.

**Attributes** — `head`: the first `RuntimeStep`, or `None`.

- Iterable — `for step in bound_wizard.path` yields `RuntimeStep`s.
- Falsy when the run has completed no steps yet.

### `Path.find_step(**context)`

**Parameters** — context lookups matched against each step's declared
context with equality on every key; `name=` matches the `name=` given to
`.step()`.

**Returns** the single matching `RuntimeStep`, or `None`. Raises
`gandalf.tree.MultipleStepsReturned` on ambiguity.

### `Path.filter_steps(**context)`

**Returns** every matching `RuntimeStep` in walk order, as a list. Same
lookups as `find_step`.

**Caveats**

- Both only ever see answers actually on the taken path — never the
  current (unanswered) step, a step not yet reached, a step in a dormant
  arm, or anything inside a preserved region past the cursor. `find_step`
  returns `None` for all of those, so guard the lookup unless the step is
  unconditionally upstream.
- **Each access of `bound_wizard.path` rebuilds the step nodes**, and
  outside a step render each access walks. A `RuntimeStep.form` is memoised
  per node, so `wizard.path.find_step(name="x").form` twice is two
  validations. Read `path` once and hold the steps you iterate. See [Walk
  costs](walk-costs.md).
- Inside a walk — a predicate, a builder, a replayed step view — `path` is
  the prefix validated so far on this request, not a fresh walk.

### `RuntimeStep`

Runtime mirror of a declared `tree.Step`, carrying one run's answer.
Dataclass; nodes are built by the walk and by `path`.

**Attributes**

| | |
| --- | --- |
| `name` | The step's routable name — its `name` context. `None` for a step declared without one. |
| `url` | `bound_wizard.step_url(self.declaration)`. `None` without a URL reverser. |
| `form` | A bound, validated form (memoised per node). Built through the step view's public composition API — `setup()` with a synthetic POST of the stored submission and files, then `get_form()` and `is_valid()` — so `form_class`, `get_form_class()`, `get_form_kwargs()`, `get_initial()` and `get_prefix()` overrides are honoured. `form_valid()`, `post()`, `dispatch()` and `setup()` overrides are not run. A stored answer whose `clean()` escapes still reconstructs, but `cleaned_data` holds only what was cleaned before the raise. |
| `data` | The raw stored submission: POST keys to their single value, or a list for a key sent more than once. `None` for a hole. |
| `files` | `{field_name: FileRef}` for the step's stored uploads, or `None`. |
| `metadata` | What the placement recorded about itself (`{"unattended": True}` from a driver), or `None`. Not the run's metadata bag. |
| `declaration` | The `tree.Step` — `declaration.context` is the full context dict, `declaration.form_view` the step view class. |
| `next` | The next node in the chain. |

### `RuntimeStep.matches_context(**context)`

**Returns** whether this step's declared context satisfies every lookup
given, as `find_step` would judge it.

### `MergeCleanedData`

A reducer that folds every step's `form.cleaned_data` on a path into one
dict, last write wins: `MergeCleanedData().reduce(bound_wizard.path)`.
Subclass and override `combine`, `visit_step`, `visit_branch` or
`visit_expand` for another policy. Costs one validation per answered step.

### `WizardContext`

`gandalf.context.WizardContext` — the environment a walk runs in: who is
answering, where state is kept, what the mount captured, and — when a
browser is genuinely involved — the request.

**`WizardContext(*, actor=None, session=None, url_kwargs=None, request=None, path="/")`**

**`WizardContext.from_request(request, **url_kwargs)`** — the context a
browser request implies. What the viewset builds per request.

**Attributes**

| | |
| --- | --- |
| `run` | The `BoundWizard`, set as it is constructed. `None` before that. What `request.wizard` used to be. |
| `actor` | Whoever is answering: `request.user` on the HTTP path (read lazily), or whoever a programmatic caller named. `None` when nobody said. A durable storage scopes runs by this. |
| `session` | The browser's session when there is a request; otherwise the one given, or an in-memory `gandalf.context.Session` (a dict with a `modified` flag). The same object for the life of the context. |
| `url_kwargs` | What the mount prefix captured, minus the wizard's own `run_id` and step segment. |
| `request` | The `HttpRequest`, or `None` when no browser is driving. A predicate that reads it is declaring it needs a browser, and under the driver will fail saying so. |
| `path` | The path a fabricated request reports. Default `"/"`. Nothing routes on it. |

**Methods**

- `addressing(**url_kwargs)` — this environment pointed at a different
  URL: same actor, session and request, with the given kwargs overriding.
  `run` is not carried over.
- `session_changed()` — mark the session modified, then `persist()`. The
  one call a session-backed storage makes after a write.
- `persist()` — write the session back now. A no-op when there is a
  request (the middleware will save it); otherwise calls `session.save()`
  if the session has one. A cookie-backed session cannot be written back
  this way — driven runs need a server-side session backend.
- `http_request()` — a request to dispatch a step view with: a fresh
  shallow copy of the browser's request, or of one fabricated once
  (a `WSGIRequest`, carrying `session` and, when set, `user`), with
  `.wizard` set to `run`. The only place a request is built when none was
  given; there is no public `fabricate_request`.

### `WizardRequest`

`gandalf.types.WizardRequest` — `HttpRequest` plus `wizard: BoundWizard`.
Never instantiated; a typing narrowing for step views, which
`StepFormView` already declares as its `request`. Not what walk-time code
receives — that is a `WizardContext`.

### Exceptions

| Exception | Base | Imported from | Raised when |
| --- | --- | --- | --- |
| `StepNotFound` | `LookupError` | `gandalf.runtime` | `render_step()` / `RunDriver.submit()` target a step the run cannot reach or that has no stored answer. |
| `InvalidStash` | `ValueError` | `gandalf.runtime` | `resurrect()` is given a non-envelope, an unsupported `version`, or a mismatched label. Task lists route it to `stash_unusable()`. |
| `RunNotFound` | `LookupError` | `gandalf.storage` | `retrieve_run()` / `get_run_data()` are asked for an id this storage does not hold — never started, obliterated, or lost with the session. The viewset answers it with `run_unavailable(..., "unknown")`. |
| `MultipleStepsReturned` | `ValueError` | `gandalf.tree` | `find_step()` matches more than one step. |

### What each caller sees of the path

| Caller | Handed | Sees in `path` |
| --- | --- | --- |
| A step view (`self.request.wizard`) | `WizardRequest` | The validated prefix before it — never its own answer, nothing after. Holds whether it is being rendered or replayed. |
| A branch predicate / switch selector (`context.run`) | `WizardContext` | The validated prefix before the branch. |
| An expand builder (`context.run`) | `WizardContext` | The validated prefix before the expansion. |
| `done(bound_wizard)` | `BoundWizard` | The whole route; every answer validated. |
| `run_started(bound_wizard)` | `BoundWizard` | An empty path — nothing is answered yet. |
| A completion template, after `finish()` | `BoundWizard` | The whole route, from the tree `keep_readable()` pinned. |

### The stored state shape

`get_state()` returns a list with one positional entry per node of the
declared tree, holes included:

```python
[
    {"step": {"applying_as": "organisation"}},          # an answer
    {"step": None},                                     # a hole
    {"step": {"full_name": "Ada"}, "files": {"logo": {...}}, "meta": {"unattended": True}},
    {"branch": {"0": [{"step": {...}}, {"step": None}], "default": [{"step": {...}}]}},
    {"expand": [{"step": {...}}, {"step": {...}}]},
]
```

| Entry | Meaning |
| --- | --- |
| `{"step": <submission>}` | The raw POST for that step, minus the CSRF token. An empty submission `{}` is still an answer. |
| `{"step": None}` | A hole — nothing stored. |
| `"files"` | Present only when the step holds uploads: `{field: FileRef}`. |
| `"meta"` | Present only when the placement recorded something about itself. |
| `{"branch": {arm_id: [entries]}}` | One list per arm ever answered, keyed by arm id: the arm's declaration-order index as a string, a switch case's name, or `"default"`. The selected arm's key is omitted when it has nothing stored; the others are dormant memory. A bare list is the legacy pre-per-arm shape and belongs to whichever arm is active. |
| `{"expand": [entries]}` | The expansion's sub-entries, a plain positional list — one computed subtree, so no arms. |

Trailing holes are trimmed at every level on persist; interior holes are
kept for positional alignment. Which arm is selected is never stored — it
is re-derived on every walk.

---

## Usage

### Reading a prior answer from a step view

```python
from gandalf.form_views import StepFormView


class BudgetLinesStepView(StepFormView):
    form_class = BudgetLinesForm
    template_name = "steps/budget_lines.html"

    def get_initial(self):
        organisation = self.request.wizard.path.find_step(name="organisation")
        if organisation is None:   # not on this route
            return super().get_initial()
        return {"currency": organisation.form.cleaned_data["currency"]}
```

### Reading a prior answer from a predicate

```python
from gandalf.context import WizardContext


def is_organisation(context: WizardContext) -> bool:
    step = context.run.path.find_step(name="applying_as")
    return step is not None and step.form.cleaned_data["applying_as"] == "organisation"
```

### Folding every answer in `done()`

```python
from django.shortcuts import redirect

from gandalf.runtime import MergeCleanedData
from gandalf.viewsets import WizardViewSet


class GrantApplicationViewSet(WizardViewSet):
    url_name = "grant"
    wizard = application

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        application = Application.objects.create(**answers)
        return redirect("grant-received", pk=application.pk)
```

### Listing answered steps with change links

```python
def done(self, bound_wizard):
    steps = list(bound_wizard.path)          # walk once, hold the nodes
    rows = [
        (step.name, step.form.cleaned_data, step.url)
        for step in steps
    ]
    ...
```

### Stashing inside `done()` and resurrecting later

```python
from gandalf.runtime import InvalidStash


def done(self, bound_wizard):
    payload = bound_wizard.stash(label="grant-v2")
    Draft.objects.create(applicant=bound_wizard.context.actor, payload=payload)
    ...

# elsewhere, on a fresh BoundWizard:
try:
    run_id = bound_wizard.resurrect(draft.payload, expected_label="grant-v2")
except InvalidStash:
    ...
```

---

## Troubleshooting

### `find_step(name=...)` returns `None` for a step I know was answered

The step is not on the resolved route *as this caller sees it*: it is the
step being rendered or replayed (a step never sees its own answer), it is
downstream of the caller, it sits in a dormant arm, or it is past the
cursor in a preserved region. Guard the lookup, or move the read to
`done()`, where the whole route is validated.

### My summary page is slow, and slower the longer the run

Each access of `bound_wizard.path` rebuilds its nodes, and each node's
`.form` is a validation. `wizard.path.find_step(...)` once per row is one
walk per row. Read `path` once, keep the list, and read `.form` off the
nodes you hold. See [Walk costs](walk-costs.md) and [Summary](summary.md).

### `run_url` / `step_url()` / `back_url` are `None`

No URL reverser: `bound_wizard.urls` is set by the viewset when it serves a
request, and is `None` under the driver or in a unit test. `back_url`
additionally needs a render context, so it is `None` from `done()` and from
a predicate.

### A GET of the bare run URL fired `done()`

Every stored answer validated, so the cursor had nowhere to land. Link into
a run with `entry_url()`, which always names a step.

### `TemplateResponse` from `done()` renders an empty path

Something called `complete()` before `keep_readable()`. `finish()` does
them in the right order; use it rather than re-spelling the sequence.

### `RunNotFound` on a run id I just created

The id is scoped to the storage: a `SessionStorage` run lives in the
session that minted it, and a context with no request has an in-memory
session unless handed one. Pass `session=` to the context, and use a
server-side session backend.

---

**Learn:** [Chapter 1 — Steps and completion](../learn/01-steps-and-completion.md) · **Related:** [Run metadata](run-metadata.md), [Step views](step-views.md), [`WizardViewSet`](viewsets.md), [Stashing](stashing.md), [Storage](storage.md), [Walk costs](walk-costs.md), [Driver](driver.md)
