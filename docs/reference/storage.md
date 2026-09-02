# Storage

`gandalf.storage` — where a run's answers and metadata live, and the
protocol a backend of your own has to satisfy.

```python
from gandalf.storage import RunNotFound, SessionStorage
from gandalf.types import StorageClass, WizardStorage
```

---

## Reference

### `WizardStorage` (protocol)

What `WizardViewSet.storage_class` has to provide. Structural, not a base
class: `SessionStorage` satisfies it without inheriting anything, and so
does a backend that keeps runs somewhere longer-lived. `Run` calls
exactly these eleven methods; nothing in the runtime, the walker or the
viewset reaches past them.

A run id is minted by the storage and opaque to everything else, so it need
not be a UUID — but the URL patterns `WizardViewSet.urls()` publishes use
`<uuid:run_id>`, so a backend minting anything else needs its own URL
scheme too.

| Method | Contract |
| --- | --- |
| `__init__(context)` | Built from the run's `WizardContext`, not a request — so a backend can scope by `context.actor` or a tenant whether a browser or a driver is filling the run in |
| `initialise_run()` | Create a run and return its id |
| `retrieve_run(run_id)` | Return the id, or raise `RunNotFound`. **This is the whole authorisation model** — see below |
| `get_run_data(run_id)` | Everything kept about the run: `{"state": [...], "meta": {...}}` for a live one, `{"completed": True, "meta": {...}}` for a finished one. Raises `RunNotFound` |
| `get_state(run_id)` | The state list; `[]` for a run that has stored nothing and for a completed run |
| `set_state(run_id, state)` | Store the list verbatim |
| `get_run_metadata(run_id)` | The run's metadata bag; `{}` for a run that recorded nothing. Readable on a completed run |
| `set_run_metadata(run_id, metadata)` | Store the bag verbatim, **now** — this is called from places that never persist state |
| `delete_run(run_id)` | Forget the run entirely. Idempotent |
| `complete_run(run_id)` | Discard the state and mark the run finished, *keeping the metadata* and leaving the run *addressable*. Idempotent |
| `is_run_complete(run_id)` | Whether the run has been tombstoned. `False` for an unknown run |

**Caveats**

- `set_run_metadata` writes immediately, not at the end of a walk. A walk
  persists nothing on its own — a GET only replays, and a `Park` declines
  to write — and `run_started()` writes the bag before any state exists. A
  backend that batched metadata with state would lose the record it names.
  See [Run metadata](run-metadata.md).
- `complete_run` leaves a tombstone rather than deleting, so a revisit can
  be answered as "finished" rather than "no such run" —
  `WizardViewSet.run_unavailable()` receives `reason="completed"` for the
  one and `"unknown"` for the other. The metadata survives the tombstone
  because it describes what the run did *outside* itself — all but the
  proof bucket, which describes the answers completion has just discarded
  and is swept with them. See [Proofs](proofs.md).
- `get_state` and `get_run_metadata` default missing keys: a freshly
  initialised `SessionStorage` run is stored as `{}`, with neither `state`
  nor `meta` present until something writes them.

### `StorageClass`

The type of `WizardViewSet.storage_class`: `type[WizardStorage]` or any
callable taking a `WizardContext` and returning something satisfying the
protocol.

### `SessionStorage(context)`

The shipped backend: plain JSON in the session behind the walk's
`WizardContext` — the browser's own session when a browser is driving, and
whichever one a script was handed otherwise. Every write calls
`context.session_changed()` so Django saves the session; `retrieve_run`
does too, which keeps a resumed run's session alive.

**Parameters**

- `context` — the `WizardContext` for the request or drive.

**Attributes**

- `SESSION_KEY = "gandalf_runs"` — the session key everything sits under.
- `max_completed_runs = 25` — how many completion tombstones are kept.
  `complete_run` re-inserts the run's entry, which orders the mapping by
  completion, then drops the oldest tombstones beyond this count. Runs
  still in progress are never pruned. Override on a subclass.

**Session layout**

```python
session["gandalf_runs"] = {
    "<run_id>": {"state": [...], "meta": {...}},   # in progress
    "<run_id>": {"completed": True, "meta": {...}},  # tombstone; "meta" only if non-empty
}
```

Run ids are `str(uuid.uuid4())`; every method accepts a `UUID` or a string
and normalises with `str()`.

### `RunNotFound`

`LookupError` raised by `retrieve_run`, `get_run_data` and everything built
on them when a run id names no run this storage can serve — never started,
already deleted, or lost with an expired session. The viewset catches it
around `retrieve()` and answers with `run_unavailable(reason="unknown")`,
whose default redirects to the start URL. `WizardViewSet.inspect()` lets it
propagate.

### Authorisation

`retrieve_run` is the gate. A run URL is a claim, and the storage is the
only thing that decides whether this context may serve that id. For
`SessionStorage` the check is implicit — the session either holds the key
or it does not — so one browser can never name another's run. A durable
backend has to make the check explicit: scope every lookup by
`context.actor` (or tenant), and raise `RunNotFound` for a run outside the
scope exactly as for one that does not exist, so an intruder learns nothing
from the difference. Treat a malformed id the same way rather than letting
the ORM raise.

### `WizardViewSet.storage_class`

```python
class GrantApplicationViewSet(WizardViewSet):
    storage_class = ModelStorage
```

Defaults to `SessionStorage`. Like every other seam it is the viewset's,
and it is the one that has to exist *before* the wizard does:
`get_wizard()` is handed a `Run` that can already read stored state to
decide its shape. The viewset instantiates it as `storage_class(context)`
on every entry point — dispatch, `begin()`, `inspect()`, `reopen()`,
`resolve()` and the driver.

### A durable backend

Gandalf ships `SessionStorage` and nothing else: a durable backend means
models, migrations and a retention policy, and those belong to the project.
The worked example is
[`tests/testapp/durable.py`](../../tests/testapp/durable.py) —
`ModelStorage`, eleven methods against a `WizardRun` table scoped to
`context.actor` — driven end to end by
[`tests/functional/test_durable_storage.py`](../../tests/functional/test_durable_storage.py)
with the session holding nothing but the login.

A durable **task list** or **add-another page** needs both seams swapped,
once, on the root viewset: `storage_class` for the runs and
`journey_store_class` for the bookkeeping (a `ModelJourneyStore` and
`ModelItemStore` are in the same module), and every entry the root
builds gets the same two.
Swapping only one gives durable answers nobody can find, or a durable index
into runs that have expired. See [Journey store](journey-store.md).

---

## Usage

### Keeping fewer tombstones

```python
from gandalf.storage import SessionStorage
from gandalf.viewsets import WizardViewSet


class SmallSessionStorage(SessionStorage):
    max_completed_runs = 5


class GrantApplicationViewSet(WizardViewSet):
    storage_class = SmallSessionStorage
    ...
```

Worth doing on the signed-cookie session backend, where the whole session
has to fit in 4KB.

### A storage scoped to the applicant

```python
import uuid

from django.core.exceptions import ValidationError

from gandalf.storage import RunNotFound

from .models import ApplicationRun


class ApplicantStorage:
    def __init__(self, context):
        self.context = context

    def _runs(self):
        return ApplicationRun.objects.filter(applicant=self.context.actor)

    def _get(self, run_id):
        try:
            return self._runs().get(pk=run_id)
        except (ApplicationRun.DoesNotExist, ValidationError, ValueError):
            raise RunNotFound(str(run_id))

    def initialise_run(self):
        run = ApplicationRun.objects.create(id=uuid.uuid4(), applicant=self.context.actor)
        return str(run.pk)

    def retrieve_run(self, run_id):
        self._get(run_id)
        return str(run_id)

    def get_run_data(self, run_id):
        run = self._get(run_id)
        if run.completed:
            return {"completed": True, "meta": run.meta}
        return {"state": run.state, "meta": run.meta}

    def get_state(self, run_id):
        return self.get_run_data(run_id).get("state", [])

    def set_state(self, run_id, state):
        self._runs().filter(pk=run_id).update(state=state)

    def get_run_metadata(self, run_id):
        return self._get(run_id).meta

    def set_run_metadata(self, run_id, metadata):
        self._runs().filter(pk=run_id).update(meta=metadata)

    def delete_run(self, run_id):
        self._runs().filter(pk=run_id).delete()

    def complete_run(self, run_id):
        self._runs().filter(pk=run_id).update(completed=True, state=[])

    def is_run_complete(self, run_id):
        return self._runs().filter(pk=run_id, completed=True).exists()
```

`ApplicationRun` needs a UUID primary key, an `applicant` foreign key, two
`JSONField`s (`state` default `list`, `meta` default `dict`) and a
`completed` boolean. Every query goes through `_runs()`, which is what makes
`retrieve_run` an authorisation check.

### Reading a run from outside its request

```python
from django.http import Http404
from django.shortcuts import redirect, render

from gandalf.storage import RunNotFound


def application_status(request, run_id):
    try:
        wizard = GrantApplicationViewSet.inspect(request, run_id)
    except RunNotFound:
        raise Http404
    if wizard.is_complete:
        return render(request, "submitted.html", {"reference": wizard.metadata.get("reference")})
    return redirect(wizard.entry_url())
```

`inspect()` walks nothing, so a caller that only wants `is_complete` or the
metadata pays one storage read and no form validation.

---

## Troubleshooting

### Every visit to a run URL redirects to the start

`retrieve_run` raised `RunNotFound`, so `run_unavailable(reason="unknown")`
answered. On `SessionStorage` that means the session no longer holds the
run — expired, a different browser, or the run was obliterated. On a
durable backend, check the scope: a run owned by someone else *should* look
exactly like this.

### A completed run's summary page shows no answers

`complete_run` discards the state; only the metadata bag survives. Read
what the completion page needs inside `done()` — or pin the tree there —
rather than walking the run afterwards. See
[`Run.keep_readable()`](run.md).

### Old completed runs vanish from the session

That is `max_completed_runs` pruning tombstones, oldest first. A pruned run
answers as `"unknown"` rather than `"completed"`. Raise the limit on a
subclass, or keep completed runs somewhere durable.

### My durable task list shows sections as "not started" after a new login

The root swapped `storage_class` but kept `SessionJourneyStore`, so the
bookkeeping that says which run a section is in went with the old session.
Swap `journey_store_class` on the root too — every section it builds gets
both — see [Journey store](journey-store.md).

---

**Learn:** [Chapter 10 — Completion hooks and run metadata](../learn/10-completion-hooks-and-metadata.md) · **Related:** [`WizardViewSet`](viewsets.md), [Run metadata](run-metadata.md), [Journey store](journey-store.md), [Stashing](stashing.md), [File uploads](file-uploads.md)
