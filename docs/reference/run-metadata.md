# Run metadata

`gandalf.runtime.RunMetadata` — a run's record of what it did outside
itself, written through to storage the moment it changes.

```python
from gandalf.metadata import MetadataBag
from gandalf.runtime import RunMetadata
```

---

## Reference

A wizard's state is answers, and every answer is re-proved from scratch on
every request. That leaves nowhere to keep the other kind of fact a run
accumulates — the record it opened somewhere else. Nobody typed it, no form
validates it, and doing it twice is the bug. `run.metadata` is
where it goes.

### `run.metadata`

A `RunMetadata`. Built fresh on every access and holding nothing itself:
the bag reads and writes storage directly, so a handle taken at the top of
a request sees a write made further down it, and the viewset's handle and a
step view's handle always agree.

### `RunMetadata(storage, run_id, path=("run",))`

A `MetadataBag` over the run's metadata envelope, which storage keeps
*beside* the state — `get_run_metadata(run_id)` / `set_run_metadata(run_id,
metadata)` — never in it. The envelope has two buckets:

```python
{
    "run":   {"application_id": 42},                      # the run's own keys
    "steps": {"referees": {"emailed": True}},             # one sub-bag per step name
}
```

### `RunMetadata.for_step(name)`

**Parameters** — `name`: a step name.

**Returns** a `RunMetadata` addressing `steps.<name>`. Always from the root:
`metadata.for_step("a").for_step("b")` is `metadata.for_step("b")`, not a
nesting. A name no step has is not an error — checking would cost a walk —
it is a bag nothing else reads. A step bag nothing wrote to reads as empty
rather than missing.

### `MetadataBag(read, write, path)`

`gandalf.metadata.MetadataBag` — the `MutableMapping[str, Any]` both
`RunMetadata` and `JourneyData` are. `read` returns the whole envelope (or
`None`); `write` stores a whole envelope; `path` names the bucket.

**Mapping API** — `bag[key]`, `bag[key] = value`, `del bag[key]`, `key in
bag`, `len(bag)`, `iter(bag)`, `bag.get(key, default)`, `dict(bag)`,
`bag.update(...)`, `repr(bag)` (shows the bucket: `RunMetadata({'a': 1})`).

### `MetadataBag.update(other=(), /, **kwargs)`

Set several keys in **one** write. `MutableMapping`'s default would loop
over `__setitem__` — one full read-modify-write of the envelope per key,
which is one `SELECT` and one `UPDATE` per key on a durable backend.

### Write semantics

| Operation | Storage write? |
| --- | --- |
| `bag[key] = value` | Yes, immediately — one read-modify-write of the envelope. |
| `bag.update(a=1, b=2)` | Yes, once for all keys. |
| `del bag[key]` | Yes. A `KeyError` for an absent key leaves storage untouched — the mutation is applied before the write. |
| `bag[key]` and every read | No. Hands back a **deep copy**. |
| `bag[key]["inner"] = value` | **No.** Mutates the copy; storage and the next read are unchanged. |

Only *assignment* writes through. That refusal is deliberate and uniform:
left alone, in-place mutation would depend on the backend — a session hands
back its live dict, so the mutation lands but nothing marks the session and
the middleware never saves it; a durable store re-reads the row and the
change is gone at once. Working in development while losing data in
production is the worst outcome, so it is refused everywhere. Assign the
whole value back:

```python
bag["refs"] = {**bag["refs"], "second": 2}
```

**Values must be JSON-safe** — the bag is stored with the run. Nothing is
memoised between operations, because two handles on one envelope are the
normal case and a cache would let one go stale mid-request.

### What the bag survives

| | |
| --- | --- |
| A walk that never persists (every GET) | Kept — the write already reached storage. |
| A `Park` | Kept — nothing was waiting on the walk. |
| Re-answering a step | Kept — state is rewritten wholesale; the bag is not touched. |
| An `Obliterate` / `obliterate()` | **Gone** with the run. |
| Completion | Kept — `complete_run` discards the answers and keeps the bag, so `run_unavailable(..., "completed")` and a completion page can still name what was created. |
| `stash()` / `resurrect()` | Kept — the bag rides in the payload's `"meta"` (omitted when empty), unlike file refs. A ref names bytes that completion deletes; a record id names something that outlives the run. Resurrecting one payload twice gives two independent bags. |

### When to write it

A write from a step view runs on **every walk**, because the step is
re-dispatched each time the run is replayed — so a step that writes
metadata must be idempotent about it, exactly as its `clean()` must be:
check the bag before doing the work, or write a value that is the same
every time.

That is why the thing you only want to do once belongs in
[`run_started()`](viewsets.md), the one hook that fires exactly once per
run — a run is minted once — and is handed a run that already has an id and
a resolved wizard. `reopen()`, `resurrect()` and `inspect()` do not fire it:
a run seeded from a stash is a continuation, and its bag comes back with its
answers. If the start URL's drive-by visit makes `run_started()` too
speculative, do the work on first answer from the first step's
`form_valid()`, guarded on the bag.

### `JourneyData`

`gandalf.storage.JourneyData` is the same `MetadataBag`, reached as
`store.data` on a journey store, with buckets `"journey"` and `"members"`
and `for_member(key)` in place of `for_step(name)`. It is where a section's
`run_done()` records what the rest of the journey needs to know, and what
its `blocked()` and `hidden()` read without paying a walk. See [Journey
store](journey-store.md).

---

## Usage

### Opening a record once, and finding it again

```python
from django.shortcuts import redirect
from django.http import Http404

from gandalf.viewsets import WizardViewSet


class GrantApplicationViewSet(WizardViewSet):
    url_name = "grant"
    wizard = application

    def run_started(self, run):
        record = Application.objects.create(applicant=run.context.actor)
        run.metadata["application_id"] = record.pk

    def done(self, run):
        record = Application.objects.get(pk=run.metadata["application_id"])
        record.submit()
        return redirect("grant-received", pk=record.pk)

    def run_unavailable(self, run, reason):
        if reason == "completed":
            return redirect("grant-received", pk=run.metadata["application_id"])
        raise Http404("That application has expired.")
```

### An idempotent write from a step view

```python
from gandalf.form_views import StepFormView


class RefereesStepView(StepFormView):
    form_class = RefereesForm
    template_name = "steps/referees.html"

    def form_valid(self, form):
        own = self.request.wizard.metadata.for_step("referees")
        if own.get("emailed") != form.cleaned_data["referee_email"]:
            send_referee_request(form.cleaned_data["referee_email"])
            own["emailed"] = form.cleaned_data["referee_email"]
        return super().form_valid(form)
```

The step is replayed on every later request; the guard makes the second
and every later dispatch a read.

### Several facts in one write

```python
def run_started(self, run):
    record = Application.objects.create()
    run.metadata.update(
        application_id=record.pk,
        status="pending",
    )
```

### Changing a nested value

```python
metadata = run.metadata
trustees = metadata.get("trustee_ids", [])
metadata["trustee_ids"] = [*trustees, trustee.pk]   # assign, do not append
```

---

## Troubleshooting

### I set `metadata["x"]["y"] = 1` and it did not stick

A read is a deep copy; mutating it changes nothing. Assign the whole value:
`metadata["x"] = {**metadata["x"], "y": 1}`.

### A record is created twice

The write is in a step view or `clean()`, which every walk re-runs. Guard
it on the bag, or move it to `run_started()`.

### `KeyError` in `run_unavailable()` for a completed run

The key was never written — usually because the run was started through a
door that does not fire `run_started()` (`reopen_at`, `resurrect`, `inspect`),
or because `run_started()` raised before the write. Use `.get()` when the
key is not guaranteed.

### `TypeError: Object of type ... is not JSON serializable`

Values must be JSON-safe. Store the primary key, not the model instance;
`isoformat()` a datetime.

### Two handles disagree

They cannot — nothing is cached. If a value looks stale, the write went to
another run (`for_step` bags and run keys are separate buckets) or
storage's `set_run_metadata` is not writing through. See [Storage](storage.md).

---

**Learn:** [Chapter 10 — Completion hooks and metadata](../learn/10-completion-hooks-and-metadata.md) · **Related:** [`Run`](run.md), [`WizardViewSet`](viewsets.md), [Storage](storage.md), [Stashing](stashing.md), [Journey store](journey-store.md)
