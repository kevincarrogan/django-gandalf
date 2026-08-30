# Journey store

`gandalf.storage` — where a journey keeps its sections' runs, their finished
answers, what they decided, and whether the journey has been submitted; and
`gandalf.types` — the protocols a replacement store has to satisfy.

```python
from gandalf.storage import (
    JourneyData,
    SessionCollectionStore,
    SessionJourneyStore,
    StashNotFound,
)
from gandalf.types import CollectionStore, JourneyStore
```

A *journey* is what a task list's sections add up to — one application,
one claim. The root viewset's `journey_store_class` is handed to every
section, add-another page and item wizard it builds; each builds a store
from it with the journey's identity and reads the same record. Groups and
add-another lists are a key namespace over that record, not a second
store.

---

## Reference

### `SessionJourneyStore(context, journey)`

The shipped store, keeping one record per journey in the session.

**Parameters**

- `context` — a `WizardContext` (`WizardContext.from_request(request)`).
- `journey` — the journey's identity, stored as `str(journey)`.

**Attributes**

- `SESSION_KEY = "gandalf_journeys"`.
- `max_completed_journeys = 10` — how many completion tombstones are kept
  per session; the oldest go first. Fewer than `SessionStorage`'s 25,
  because a journey's tombstone keeps its data.
- `stash_store_class = SessionStashStore` — the class behind `stashes`,
  pointed at the record's `"stashes"` mapping.
- `journey` — the identity as given. `stashes` — the stash store.

**Session layout**

```python
session["gandalf_journeys"][journey] = {
    "runs": {key: run_id},        # sections being answered right now
    "stashes": {key: payload},    # sections that have finished
    "data": {...},                # what the sections decided (JourneyData's envelope)
    "collections": {...},         # SessionCollectionStore only
    "completed": True,            # tombstone only
}
```

Reads never create the record, so rendering a task list cannot mark the session
modified; the first write does.

**The run registry** — which run a section is being answered in.

| Method | Returns / effect |
| --- | --- |
| `get_run(key)` | The recorded run id, or `None` |
| `set_run(key, run_id)` | Records `str(run_id)`, replacing any earlier one |
| `clear_run(key)` | Forgets it; idempotent |

**The completion record** — a section is complete when it holds a stash.

| Method | Returns / effect |
| --- | --- |
| `get_stash(key)` | The payload; raises `StashNotFound` |
| `has_stash(key)` | `bool`, no exception — what a row asks |
| `put_stash(key, payload)` | Records the section as finished, replacing earlier answers |
| `delete_stash(key)` | Forgets it; idempotent |
| `keys()` | Keys holding a stash, in insertion order. An add-another list's items appear here under their composed keys (`"budget:<id>"`) beside the declared sections |

A payload is `Run.stash()` output — see [Stashing](stashing.md).
The run id and the stash outlive each other: `SectionViewSet.done()`
writes the stash and then clears the run, so a completed section survives
its run being pruned.

**What the sections decided**

- `data` — property; a fresh `JourneyData` on every access, so a handle
  taken at the top of a request sees a write made further down it.

**The journey's own completion**

- `complete()` — replaces the record with `{"completed": True}`, keeping
  `"data"` when there is any. Runs, stashes and add-another registries go. Re-inserts
  the record so the mapping is ordered by completion, then prunes to
  `max_completed_journeys`. Idempotent. Journeys in progress are never
  pruned.
- `is_complete()` — whether the record is a tombstone.

### `JourneyData(read, write, path=("journey",))`

The journey's record of what its sections decided: the facts a page, a
`blocked()` and a `hidden()` read without walking anything. A
`MetadataBag` — the same class as a run's `run.metadata`, kept for
the journey rather than one run; the bag semantics are in
[Run metadata](run-metadata.md).

**Semantics**

- A `MutableMapping`: `data["amount"] = 25_000`, `data.get("amount")`,
  `"amount" in data`, `del data["amount"]`, iteration, `len()`.
- Values must be JSON-safe.
- Written through on every assignment; `update({...})` sets several keys in
  one write.
- Reads hand back a deep copy. Mutating a nested value in place changes the
  copy and nothing else; assign the whole value back.
- Two buckets in one envelope: the journey's own keys under `"journey"`,
  and one sub-bag per section under `"members"`.

**Methods**

- `for_member(key)` — this journey's data for section `key`, addressed
  from the root whichever bag it is called on: a section can keep its own
  notes without treading on the journey or on another section.

Write here from a section's `run_done()` (the run is still readable) and
read back from `blocked()` / `hidden()`, `journey_done()` and
`submitted()`. The tombstone keeps it.

### `SessionCollectionStore(context, journey)`

`SessionJourneyStore` plus an ordered registry of items per add-another
list, under a `"collections"` mapping in the same record. Nothing above
it changes: an item's run and stash live under the composed key the view
builds (`"budget:<id>"`), so a task list's store and an add-another page's
store share one key space.

| Method | Returns / effect |
| --- | --- |
| `item_ids(key)` | Item ids in the order the user added them; `[]` for a list never started |
| `has_item(key, item_id)` | `bool` |
| `add_item(key, item_id)` | Appends with `title=None`; adding a listed id is a no-op |
| `remove_item(key, item_id)` | Removes the item and its cached title, keeping the order of the rest; idempotent |
| `get_item_title(key, item_id)` | The title cached at its last completion, or `None` |
| `set_item_title(key, item_id, title)` | Replaces the cached title; `None` clears it; an unlisted item is ignored |
| `is_declared_done(key)` | Whether the user answered "no" to *add another*; `False` for a list never started |
| `set_declared_done(key, declared_done)` | Records or withdraws that answer |

Registry and stash are separate on purpose: an item exists from the moment
it is added, which is what lets a half-finished one have a row, and
`keys()` only holds the items that have finished.

### `StashNotFound`

`LookupError` raised by `get_stash()` (and `SessionStashStore.get()` /
`pop()`) when the key holds no payload — never stashed, already deleted,
or lost with the session.

### `gandalf.types.JourneyStore`

The protocol a `TaskListViewSet`'s `journey_store_class` has to satisfy.
Structural: `SessionJourneyStore` inherits nothing to meet it.

```python
class JourneyStore(Protocol):
    def __init__(self, context: WizardContext, journey: str) -> None: ...
    def get_run(self, key: str) -> str | None: ...
    def set_run(self, key: str, run_id: str) -> None: ...
    def clear_run(self, key: str) -> None: ...
    def get_stash(self, key: str) -> Stash: ...
    def has_stash(self, key: str) -> bool: ...
    def put_stash(self, key: str, payload: Stash) -> None: ...
    def delete_stash(self, key: str) -> None: ...
    def keys(self) -> list[str]: ...
    @property
    def data(self) -> JourneyData: ...
    def complete(self) -> None: ...
    def is_complete(self) -> bool: ...
```

Contracts a backend must keep:

- `get_stash()` raises `StashNotFound`; `clear_run()` and `delete_stash()`
  are idempotent.
- `data` returns a `JourneyData` whose `write` callable persists *now*, not
  at the end of a walk — it is written from places that never persist
  state.
- `complete()` discards runs and stashes, keeps `data`, and leaves the
  journey addressable so `is_complete()` answers `True` afterwards.
- Scope by `context.actor` and `journey`: the journey names *which*, the
  actor *whose*.

### `gandalf.types.CollectionStore`

`JourneyStore` plus the eight registry methods of `SessionCollectionStore`
above. What the `journey_store_class` of a tree with an add-another list in
it has to satisfy — which is why `TaskListViewSet`'s default is
`SessionCollectionStore` rather than `SessionJourneyStore`: one class
serves a list with no add-another just as well, and one class means every
entry of the tree reads the same record.

### The default journey

`TaskListViewSet.journey = "default"` and `journey_url_kwarg = "journey"`.
A page mounted under a `<slug:journey>` segment reads its journey off the
URL; one mounted under none uses `"default"` — one journey per session,
which is what a profile task list is. Every entry is mounted beneath the
page and built with the same pair, so all of them read the same segment.

### The durable swap

A store that keeps the same things in tables drops in by
`journey_store_class` alone. [`tests/testapp/durable.py`](../../tests/testapp/durable.py)
is a worked example: `ModelJourneyStore` keeps run id and stash on one row
per section (they outlive each other), and the journey's data and completion
on a row of their own that survives `complete()` deleting the sections;
`ModelCollectionStore` adds the registry with an explicit `position` and a
uniqueness constraint. Both are scoped by `context.actor` and `journey`.

A durable task list needs **both** seams swapped, once, on the root
viewset: `storage_class` for the runs ([Storage](storage.md)) and
`journey_store_class` for the bookkeeping, and every entry the page builds
gets the same two. Swapping only one gives durable answers nobody can find,
or a durable index into runs that have expired.

---

## Usage

### Writing a decided fact at completion and reading it back

```python
class ContactSection(SectionViewSet):
    wizard = contact

    def run_done(self, run):
        email = run.path.find_step(name="email")
        self.get_journey_store().data["email"] = email.form.cleaned_data["email"]
        return super().run_done(run)


class RefereesSection(SectionViewSet):
    wizard = referees

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("contact")


class GrantApplication(TaskList):
    contact = Section(ContactSection, title="Contact details")
    referees = Section(RefereesSection, title="Referees")
```

### Beginning a journey from a wizard that has none yet

```python
from django.shortcuts import redirect

from gandalf.viewsets import WizardViewSet


class ApplicationStartViewSet(WizardViewSet):
    url_name = "grant-start"
    wizard = setup

    def done(self, run):
        journey = GrantApplication.begin(self.request)
        journey.finish("setup", run)
        return redirect(journey.url)
```

`begin()` builds the list's store under a new id; `finish()` records the
run as the `setup` section — stashed, its `run_done()` run — and `url` is
the page under that id. See [`Journey`](tasklists.md).

### Keeping per-section notes apart

```python
store = self.get_journey_store()
store.data.for_member("budget").update({"lines": 3, "total": 420})
store.data.for_member("budget")["total"]     # 420
store.data.get("total")                       # None — a different bucket
```

### Swapping in a durable store

```python
from gandalf.tasklists import TaskListViewSet

from myapp.durable import ModelJourneyStore, ModelStorage


class GrantApplicationViewSet(TaskListViewSet):
    storage_class = ModelStorage
    journey_store_class = ModelJourneyStore
    ...
```

Every entry the page builds — section, add-another page, item, group —
gets both.

---

## Troubleshooting

### `StashNotFound: contact`

`get_stash()` on a section that has not finished, or whose stash was
deleted or lost with the session. Ask `has_stash()` first where "not
finished" is an ordinary answer.

### I set a nested value in `store.data` and it did not persist

Reads are deep copies: `store.data["budget"]["total"] = 1` changes the copy.
Assign the whole value back — `store.data["budget"] = {**budget, "total": 1}`
— or use `for_member()` / `update()`.

### An older submitted application's done page now 404s

Only the `max_completed_journeys` (10) most recent tombstones are kept per
session; the oldest are pruned when a newer journey completes. Keep the
reference somewhere durable at `journey_done()` if the done page must
outlive that.

### A section's title (or run) is missing after swapping only `storage_class`

Swap `journey_store_class` too. The journey store holds the index — run ids
and stashes — and the storage holds the runs; one durable half and one
session half do not agree across sessions.

---

**Learn:** [Chapter 15 — Journeys](../learn/15-journeys.md) · **Related:** [Task lists](tasklists.md), [Add another](add-another.md), [Stashing](stashing.md), [Run metadata](run-metadata.md), [Storage](storage.md)
