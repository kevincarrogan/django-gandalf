# Chapter 9 — Finishing, and what it leaves behind

An application is a record in a database, not a string in a response. This
chapter opens one when the run starts, submits it when the run finishes, and
makes sure both happen exactly once.

```python
class RecordedApplicationViewSet(WizardViewSet):
    url_name = "readme-record"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def run_started(self, bound_wizard):
        application = Application.objects.create()
        bound_wizard.metadata["application_id"] = application.pk

    def done(self, bound_wizard):
        application = Application.objects.get(pk=bound_wizard.metadata["application_id"])
        answers = MergeCleanedData().reduce(bound_wizard.path)
        application.submit(answers["email"])
        return redirect("readme-received", pk=application.pk)

    def run_unavailable(self, bound_wizard, reason):
        if reason == "completed":
            return redirect("readme-received", pk=bound_wizard.metadata["application_id"])
        raise Http404("That application has expired.")
```

### `done()` runs exactly once

A run finishes the first time it is walked and every step is satisfied;
`done()` is called, its files are cleaned up, and the run is retired — its
answers are dropped and a small completion marker takes their place. After
that, every request for it (bare run URL or any step URL, GET or POST) is
answered by `run_unavailable()` without reaching the wizard. So a stale tab
cannot submit twice, and a refreshed completion page cannot re-charge a card.
Put side effects in `done()` and they happen once, full stop. The marker is
written *after* `done()` returns, so a `done()` that raises leaves the run
intact and resumable.

`run_unavailable(self, bound_wizard, reason)` answers everything that cannot
be run — `reason` is `"completed"` or `"unknown"` (never started, obliterated,
or a lost session). The default redirects to the start URL; here a completed
run goes to its own received page instead.

### `run_started()`: the once-per-run hook

A wizard's state is answers, and every answer is re-proved from scratch on
every request. That leaves nowhere to keep the other kind of fact a run
accumulates: **the record it opened somewhere else.** Nobody typed it, no form
validates it, and doing it twice is the bug.

`run_started(self, bound_wizard)` fires when a fresh run of this wizard is
created, and does nothing by default. It is the only hook that runs **exactly
once per run** without you having to arrange it — a run is minted once, so it
is called once. It is handed a run that already has an id and a resolved
wizard, so it can read `bound_wizard.wizard` and write
`bound_wizard.metadata`. Both doors a fresh run comes through call it — the
start URL and `begin()` / `RunDriver` (chapter 15).

`reopen()` and `resurrect()` (chapter 10) do not fire it, and neither does
`inspect()`. A run seeded from a stash is a continuation, not a start: its
metadata comes back with its answers, so the record it created is already
there. Unlike an observer, it may raise, and a raise propagates to whoever
asked for the run. The cost worth knowing: the bare start URL mints a run and
redirects, so this fires for a drive-by visit that answers nothing. If that
is too expensive to do speculatively, do it on first answer instead — from
the first step's `form_valid()`, guarded on the metadata bag.

### `bound_wizard.metadata`: what it remembers

A dict, readable and writable from anywhere holding the run — a step view, a
branch predicate, `done()`, a driver. `metadata.for_step("website")` addresses
a sub-bag per step name, so two steps cannot tread on each other and neither
can tread on the run's own keys.

**Every write goes straight to storage**, and that is the whole point. A walk
persists nothing: `walk()` builds a tree and hands it back, and only the
caller decides to `persist()`. A GET never does, yet a GET still replays
every stored answer through its real `FormView` — `form_valid()` included. So
a record id written into *state* during a GET is thrown away, and the next
GET opens a second record. The bag is stored beside the state, through its
own storage seam, and survives:

| | |
| --- | --- |
| a walk that never persists | the write already reached storage |
| a `Park` | same — nothing was waiting on the walk |
| re-answering a step | state is rewritten wholesale; the bag is not touched |
| **completion** | `complete_run` discards the answers and keeps the bag, so `run_unavailable()` above can still name the application |
| **a stash round trip** | the bag rides in the payload, unlike file refs — a ref names bytes that completion deletes, a record id names something that outlives the run |

Three sharp edges. Values must be JSON-safe. Only *assignment* writes
through: a read hands back a deep copy, so mutating a nested value in place
changes that copy and nothing else — assign the whole value back instead.
That refusal is deliberate and uniform: left alone it would depend on the
backend (a session hands back its live dict and the mutation lands but is
never saved; a durable store re-reads the row and the change is gone at
once), and working in development while losing data in production is the
worst of the outcomes. And when several keys change together, `update()`
puts them in with **one** write rather than one per key.

A write from a step view runs on every walk, because the step is
re-dispatched every time the run is replayed — so a step that writes metadata
must be idempotent about it, exactly as its `clean()` must be. That is
precisely why the thing you only want to do once belongs in `run_started()`,
which is walked past rather than re-run.

### Storage

Storage is session-backed. Gandalf ships `SessionStorage`, which keeps plain
JSON in the session behind the walk's `WizardContext` — the browser's own
when a browser is driving, and whichever one a script was handed otherwise.
It is the one touch point set on the viewset rather than via `.configure()`,
because it must exist *before* the wizard does — a `get_wizard()` reads
stored state to shape itself:

```python
class RecordedApplicationViewSet(WizardViewSet):
    storage_class = CustomSessionStorage
```

Retired runs are pruned to the most recent `SessionStorage.max_completed_runs`
(25 by default), so completed runs cannot grow a session without bound.

### Storage that outlives a session

An application the applicant comes back to over days needs somewhere better
than a session. Gandalf ships no durable backend — that would mean models,
migrations and a retention policy, and the only dependency here is Django — so
`storage_class` is the seam, and it is small enough to swap. `BoundWizard`
calls exactly these eleven things and nothing in the runtime, the walker or
the viewset reaches past them:

| Method | Contract |
| --- | --- |
| `__init__(context)` | The `WizardContext` is passed in, so a backend can scope by `context.actor` or a tenant |
| `initialise_run()` | Create a run, return its id |
| `retrieve_run(run_id)` | Return the id, or raise `RunNotFound`. **This is the whole authorisation model** — scoping the queryset by owner is what stops one user resuming another's run |
| `get_run_data(run_id)` | `{"state": [...], "meta": {...}}`, or `{"completed": True, "meta": {...}}` for a finished run |
| `get_state(run_id)` | The state list; `[]` for a completed run |
| `set_state(run_id, state)` | Store the list verbatim |
| `get_run_metadata(run_id)` | The run's metadata bag; `{}` for a run that recorded nothing. Readable on a completed run |
| `set_run_metadata(run_id, metadata)` | Store the bag verbatim, **now** — this is called from places that never persist state |
| `delete_run(run_id)` | Forget it entirely. Idempotent |
| `complete_run(run_id)` | Discard the state and mark it finished, *keeping the metadata*, and leaving the run *addressable*. Idempotent |
| `is_run_complete(run_id)` | Whether it has been tombstoned |

A [worked `ModelStorage`](../tests/testapp/durable.py) lives in the test app,
driven end to end by
[`test_durable_storage.py`](../tests/functional/test_durable_storage.py) — a
whole task list over the database, with the session holding nothing but the
login. The task list (chapter 11) and the journey (chapter 14) have a second,
smaller seam of their own, `section_store_class`; the same module implements
that too, and a durable task list needs **both** swapped — durable answers
nobody can find, or a durable index into runs that have expired, is what
swapping one gives you.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/record/ &nbsp;·&nbsp; **Source:** [`ch09_records.py`](../tests/testapp/readme/ch09_records.py)

---

[← Chapter 8 — Proof it exists](08-proof-it-exists.md) · [README](../README.md) · [Chapter 10 — Coming back later →](10-coming-back-later.md)
