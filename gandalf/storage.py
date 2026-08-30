from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, cast

from gandalf.context import WizardContext
from gandalf.metadata import MetadataBag
from gandalf.types import (
    ItemRegistry,
    Item,
    JourneyRecord,
    Metadata,
    RunData,
    Stash,
    State,
)


class RunNotFound(LookupError):
    """Raised when a run id names no run this session can serve — never
    started, already forgotten, or lost with an expired session."""


class StashNotFound(LookupError):
    """Raised when a stash key names no stored payload — never stashed,
    already popped, or lost with an expired session."""


class SessionStorage:
    SESSION_KEY = "gandalf_runs"
    # A completed run leaves a tombstone behind so a revisit can be answered
    # as finished rather than mistaken for one that never existed. Tombstones
    # are tiny, but a session is not unbounded (the cookie backend caps at
    # 4KB), so only the most recently completed are kept.
    max_completed_runs = 25

    def __init__(self, context: WizardContext) -> None:
        self.context = context

    def _runs(self) -> dict[str, RunData]:
        # The session is an untyped JSON store; what Gandalf keeps under its
        # own key is this shape by construction.
        return cast(dict[str, RunData], self.context.session.get(self.SESSION_KEY, {}))

    def initialise_run(self) -> str:
        run_id = str(uuid.uuid4())
        gandalf_runs = self.context.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[run_id] = {}
        self.context.session_changed()
        return run_id

    def retrieve_run(self, run_id: str) -> str:
        """Return the run id as given, raising `RunNotFound` when this
        session holds no such run."""
        self.get_run_data(run_id)
        self.context.session_changed()
        return run_id

    def get_run_data(self, run_id: str) -> RunData:
        run_data = self._runs().get(str(run_id))
        if run_data is None:
            raise RunNotFound(str(run_id))
        return run_data

    def get_state(self, run_id: str) -> State:
        run_data = self.get_run_data(run_id)
        return cast(State, run_data.get("state", []))

    def set_state(self, run_id: str, state: State) -> None:
        run_data = self.get_run_data(run_id)
        run_data["state"] = state
        self.context.session_changed()

    def get_run_metadata(self, run_id: str) -> Metadata:
        """The run's metadata bag, kept beside its state rather than in it.

        Readable on a tombstoned run too — `complete_run` discards the
        answers and keeps this — so a completion page can still say which
        record the run created.
        """
        run_data = self.get_run_data(run_id)
        return cast(Metadata, run_data.get("meta", {}))

    def set_run_metadata(self, run_id: str, metadata: Metadata) -> None:
        """Store the run's metadata bag, now.

        Written through on every change rather than at the end of a walk,
        because a walk may never persist: a GET replays stored answers
        without storing anything, and a `Park` declines to write at all.
        See `RunMetadata` for what that buys.
        """
        run_data = self.get_run_data(run_id)
        run_data["meta"] = metadata
        self.context.session_changed()

    def delete_run(self, run_id: str) -> None:
        """Forget the run entirely. Idempotent: deleting an unknown run is
        not an error, so callers need not check first."""
        gandalf_runs = self._runs()
        gandalf_runs.pop(str(run_id), None)
        self.context.session_changed()

    def complete_run(self, run_id: str) -> None:
        """Replace the run's answers with a completion tombstone.

        The run stays addressable so a revisit is answerable — "this one is
        finished" rather than "no such run" — but its state is gone, so a
        completed run can neither be edited nor keep growing the session.
        Its metadata bag survives, because that describes what the run did
        elsewhere and not what anyone answered.
        Re-inserting the entry orders the mapping by completion, which is
        what lets pruning drop the oldest. Idempotent.
        """
        gandalf_runs = self._runs()
        run_id = str(run_id)
        previous = gandalf_runs.pop(run_id, None) or {}
        tombstone: RunData = {"completed": True}
        # The answers go; the metadata stays. It is the run's record of what
        # it did *outside* itself — the invoice it raised, the case it
        # opened — and that outlives the answers by definition. Small enough
        # to keep in a tombstone the way answers never were.
        metadata = previous.get("meta")
        if metadata:
            tombstone["meta"] = metadata
        gandalf_runs[run_id] = tombstone
        self._prune_completed(gandalf_runs)
        self.context.session_changed()

    def is_run_complete(self, run_id: str) -> bool:
        run_data = self._runs().get(str(run_id))
        return bool(run_data and run_data.get("completed"))

    def _prune_completed(self, gandalf_runs: dict[str, RunData]) -> None:
        """Drop all but the `max_completed_runs` most recently completed
        tombstones. Runs still in progress are never pruned."""
        completed = [
            run_id for run_id, data in gandalf_runs.items() if data.get("completed")
        ]
        excess = max(0, len(completed) - self.max_completed_runs)
        for run_id in completed[:excess]:
            del gandalf_runs[run_id]


class SessionStashStore:
    """Keyed stash payloads in the session — where a journey keeps its
    sections' finished answers, and the shipped home for a stash a caller
    keeps by hand.

    A stash is caller-owned — `Run.stash()` hands back a payload and
    the application decides where it lives. Built with nothing but a context,
    this store keeps payloads under its own session key, server-side so they
    cannot be tampered with in transit: the arrangement for one wizard that
    wants to be re-openable and has no task list above it.

    Built with a `home`, it keeps them wherever it is told. `SessionJourneyStore`
    hands it the stash mapping inside a journey's record, so a task list's stashes
    are this class too — scoped to the journey, torn down with it — and the
    two arrangements share one implementation and one `StashNotFound`.

    `home` is two callables rather than a mapping, because a mapping that
    does not exist yet must not be created by a read: a render is all reads,
    and a session marked modified on every GET is a session written back on
    every GET. `read()` returns the mapping or an empty one; `write()` returns
    it, creating it on the way.
    """

    SESSION_KEY = "gandalf_stashes"

    def __init__(
        self,
        context: WizardContext,
        home: tuple[Callable[[], dict[str, Stash]], Callable[[], dict[str, Stash]]]
        | None = None,
    ) -> None:
        self.context = context
        self._read, self._write = home or (
            self._own_mapping,
            self._own_mapping_for_writing,
        )

    def _own_mapping(self) -> dict[str, Stash]:
        return cast(dict[str, Stash], self.context.session.get(self.SESSION_KEY, {}))

    def _own_mapping_for_writing(self) -> dict[str, Stash]:
        return cast(
            dict[str, Stash], self.context.session.setdefault(self.SESSION_KEY, {})
        )

    def put(self, key: str, payload: Stash) -> None:
        """Store `payload` under `key`, replacing any existing stash."""
        self._write()[key] = payload
        self.context.session_changed()

    def get(self, key: str) -> Stash:
        """Return the stash under `key`, raising `StashNotFound` without one."""
        payload = self._read().get(key)
        if payload is None:
            raise StashNotFound(key)
        return payload

    def has(self, key: str) -> bool:
        """Whether a stash is held under `key` — answered without an
        exception to catch, which is what a task list row asks."""
        return key in self._read()

    def pop(self, key: str) -> Stash:
        """Remove and return the stash under `key`, raising `StashNotFound`
        without one."""
        payload = self.get(key)
        del self._read()[key]
        self.context.session_changed()
        return payload

    def delete(self, key: str) -> None:
        """Forget the stash under `key`. Idempotent: deleting an unknown key
        is not an error, so callers need not check first."""
        self._read().pop(key, None)
        self.context.session_changed()

    def keys(self) -> list[str]:
        """The stored stash keys, in insertion order."""
        return list(self._read())


#: The two buckets a journey's data is kept in — see `JourneyData`.
JOURNEY_BUCKET = "journey"
SECTION_BUCKET = "sections"


class JourneyData(MetadataBag):
    """A journey's record of what its sections decided — the facts a task list and
    its doors read without walking anything.

    A section's answers live in its stash, and a stash's state is positional
    against a tree whose shape may depend on a branch predicate nobody has
    evaluated — so no task list, and no other section, can read an answer out of
    one without paying a walk. This is where the *decided* version goes:
    `run_done()` reads its own answers, once, inside the window where
    the run is still readable, and writes what the rest of the journey needs
    to know. `blocked()` and `hidden()` read it back for free.

        # in a section's run_done()
        store.data["employment_status"] = step.form.cleaned_data["status"]

        # in another section's blocked()
        return store.data.get("employment_status") != "employed"

    Two buckets, as a run's metadata has: the journey's own keys, and one
    sub-bag per member under `for_section(key)`, so a member can keep its
    own notes without treading on the journey or on another section. The
    mapping itself is `MetadataBag`'s — JSON-safe values, deep-copied reads,
    one write per assignment, `update()` for several at once.

    Kept when the journey completes, exactly as a run's metadata survives its
    tombstone: the answers go, but what they decided is what a done page
    still has to say.
    """

    def __init__(
        self,
        read: Callable[[], Metadata | None],
        write: Callable[[Metadata], None],
        path: tuple[str, ...] = (JOURNEY_BUCKET,),
    ) -> None:
        super().__init__(read, write, path)

    def for_section(self, key: str) -> JourneyData:
        """This journey's data for the section `key` names. Addressed from
        the root whichever bag it is called on."""
        return type(self)(self._read, self._write_envelope, (SECTION_BUCKET, key))


class SessionJourneyStore:
    """Session-backed home for one journey's bookkeeping: which run each
    section is currently being answered in, the stash a finished one left
    behind, and what the sections decided between them.

    A *journey* is the whole thing the sections add up to — an application,
    a profile, a claim — and the store is scoped to one. Every mapping here
    sits under the journey's record, so two applications in two tabs are two
    records in one session, and a section key means the same thing in each.
    The journey's identity is the caller's: a task list reads it off a URL kwarg or
    declares one, and hands it here.

    Two mappings for a section, because they answer different questions and
    outlive each other. A run id says where an unfinished section can be
    picked up, and is forgotten the moment the section finishes. A payload is
    `Run.stash()` output and *is* the section's completion — a task list
    reads it and needs no run at all, which is what lets a completed section
    survive its run being pruned by `max_completed_runs`. The payload half is
    a `SessionStashStore` pointed at the journey's record, so a task list's stashes
    and a hand-kept one are the same thing in two homes.

    Then `data`, the journey's decided facts (see `JourneyData`), and the
    journey's own completion: `complete()` discards the runs and the stashes,
    keeps the data, and leaves a tombstone so a revisit reads as submitted
    rather than as a journey nobody has started.

    The session layout, one record per journey under one key::

        session["gandalf_journeys"][journey] = {
            "runs": {key: run_id},
            "stashes": {key: payload},
            "data": {...},
            "completed": True,        # tombstone only
        }

    `SessionItemStore` adds a `"lists"` mapping to the record.
    """

    SESSION_KEY = "gandalf_journeys"
    stash_store_class = SessionStashStore
    # A completed journey leaves a tombstone behind so a revisit can be
    # answered as submitted rather than mistaken for one that never existed.
    # A tombstone keeps the journey's data, which is bigger than a run's, so
    # fewer are kept than `SessionStorage.max_completed_runs`.
    max_completed_journeys = 10

    def __init__(self, context: WizardContext, journey: str) -> None:
        self.context = context
        self.journey = str(journey)
        self.stashes = self.stash_store_class(
            context,
            home=(
                lambda: self._read().get("stashes", {}),
                lambda: self._mapping("stashes"),
            ),
        )

    # --- the journey's record ----------------------------------------------

    def _journeys(self) -> dict[str, JourneyRecord]:
        return cast(
            dict[str, JourneyRecord], self.context.session.get(self.SESSION_KEY, {})
        )

    def _read(self) -> JourneyRecord:
        """The journey's record, or an empty one for a journey never written.
        Read-only callers come through here so a render cannot dirty the
        session."""
        return self._journeys().get(self.journey, {})

    def _record(self) -> JourneyRecord:
        """The journey's record, created on first write."""
        journeys = self.context.session.setdefault(self.SESSION_KEY, {})
        return cast(JourneyRecord, journeys.setdefault(self.journey, {}))

    def _mapping(self, name: str) -> dict[str, Any]:
        """One of the record's mappings, for writing — created on demand."""
        return cast(dict[str, Any], self._record().setdefault(name, {}))

    # --- the run registry --------------------------------------------------

    def get_run(self, key: str) -> str | None:
        """The run this section is being answered in, or None when it is not
        being answered at all."""
        return cast("str | None", self._read().get("runs", {}).get(key))

    def set_run(self, key: str, run_id: str) -> None:
        """Record `run_id` as where this section is answered, replacing any
        run already recorded for it."""
        self._mapping("runs")[key] = str(run_id)
        self.context.session_changed()

    def clear_run(self, key: str) -> None:
        """Forget where this section was being answered. Idempotent: clearing
        a section with no run is not an error, so callers need not check
        first."""
        self._read().get("runs", {}).pop(key, None)
        self.context.session_changed()

    # --- the completion record ---------------------------------------------

    def get_stash(self, key: str) -> Stash:
        """The finished section's stash, raising `StashNotFound` without
        one."""
        return self.stashes.get(key)

    def has_stash(self, key: str) -> bool:
        """Whether this section has finished — what a task list row asks, answered
        without an exception to catch."""
        return self.stashes.has(key)

    def put_stash(self, key: str, payload: Stash) -> None:
        """Record this section as finished, replacing any earlier answers."""
        self.stashes.put(key, payload)

    def delete_stash(self, key: str) -> None:
        """Forget that this section ever finished. Idempotent."""
        self.stashes.delete(key)

    def keys(self) -> list[str]:
        """The sections holding a stash, in insertion order.

        Note that a collection's items stash under composed keys of their own
        (`"guests:<id>"`), so a task list sharing its store with one will see them
        here alongside the sections it declared.
        """
        return self.stashes.keys()

    # --- what the sections decided -----------------------------------------

    @property
    def data(self) -> JourneyData:
        """The journey's decided facts — see `JourneyData`. Built fresh per
        access and holding nothing, so a handle taken at the top of a request
        still sees a write made further down it."""
        return JourneyData(read=self._read_data, write=self._write_data)

    def _read_data(self) -> Metadata | None:
        return cast("Metadata | None", self._read().get("data"))

    def _write_data(self, envelope: Metadata) -> None:
        self._record()["data"] = envelope
        self.context.session_changed()

    # --- the journey's own completion --------------------------------------

    def complete(self) -> None:
        """Replace the journey's bookkeeping with a completion tombstone.

        The runs and the stashes go — a submitted journey can neither be
        edited nor keep growing the session — and the data stays, because it
        is what a done page still has to say. Re-inserting the record orders
        the mapping by completion, which is what lets pruning drop the
        oldest. Idempotent.
        """
        journeys = self.context.session.setdefault(self.SESSION_KEY, {})
        previous = journeys.pop(self.journey, None) or {}
        tombstone: JourneyRecord = {"completed": True}
        data = previous.get("data")
        if data:
            tombstone["data"] = data
        journeys[self.journey] = tombstone
        self._prune_completed(journeys)
        self.context.session_changed()

    def is_complete(self) -> bool:
        """Whether this journey has been submitted."""
        return bool(self._read().get("completed"))

    def _prune_completed(self, journeys: dict[str, JourneyRecord]) -> None:
        """Drop all but the `max_completed_journeys` most recently completed
        tombstones. Journeys still in progress are never pruned."""
        completed = [
            journey for journey, record in journeys.items() if record.get("completed")
        ]
        excess = max(0, len(completed) - self.max_completed_journeys)
        for journey in completed[:excess]:
            del journeys[journey]


class SessionItemStore(SessionJourneyStore):
    """A collection's registry, on top of a journey's bookkeeping.

    A task list's sections are declared, so the store never has to enumerate them. A
    collection's items are not: the user grows them, and there is no reading of
    runs or stashes that can hand back the list — `keys()` is the stash key
    space, which holds only the items that have *finished*, in the order they
    finished rather than the order the user made them. So the registry is
    explicit, ordered, and separate: an item exists from the moment it is
    added, which is what lets a half-finished one still have a row.

    Three facts per collection, in one mapping under the journey's record:
    the item ids in order, the title each cached when it last finished, and
    whether the user has said there is nothing more to add. Titles ride
    inside the item entry rather than a parallel mapping, so removing an item
    cannot orphan one.

    Nothing here touches the methods above it. An item's run and stash live
    under an ordinary section key the *view* composes — the store never
    learns the scheme — so a task list store and a collection store share one key
    space and one contract.
    """

    def _lists(self) -> dict[str, ItemRegistry]:
        return cast(dict[str, ItemRegistry], self._read().get("lists", {}))

    def _list_record(self, key: str) -> ItemRegistry:
        """The collection's record, created on first write. Read-only callers
        go through `_lists()` so a render cannot dirty the session."""
        record = self._mapping("lists").setdefault(key, {})
        record.setdefault("items", [])
        return cast(ItemRegistry, record)

    def _items(self, key: str) -> list[Item]:
        record = self._lists().get(key)
        if record is None:
            return []
        return cast("list[Item]", record.get("items", []))

    def item_ids(self, key: str) -> list[str]:
        """The collection's items in the order the user added them; empty for
        a collection never started."""
        return [item["id"] for item in self._items(key)]

    def has_item(self, key: str, item_id: str) -> bool:
        """Whether the registry lists this item — what a door asks, answered
        without an exception to catch."""
        return item_id in self.item_ids(key)

    def add_item(self, key: str, item_id: str) -> None:
        """Append an item to the collection. Adding an id already listed is a
        no-op rather than a duplicate, so a task list's uniqueness rule holds by
        construction."""
        if self.has_item(key, item_id):
            return
        self._list_record(key)["items"].append({"id": item_id, "title": None})
        self.context.session_changed()

    def remove_item(self, key: str, item_id: str) -> None:
        """Forget an item and the title cached for it, keeping the order of
        the rest. Idempotent: removing an unlisted item is not an error, so
        callers need not check first."""
        record = self._list_record(key)
        record["items"] = [item for item in record["items"] if item["id"] != item_id]
        self.context.session_changed()

    def get_item_title(self, key: str, item_id: str) -> str | None:
        """The title cached at this item's last completion, or None for one
        that has not finished."""
        for item in self._items(key):
            if item["id"] == item_id:
                return cast("str | None", item["title"])
        return None

    def set_item_title(self, key: str, item_id: str, title: str | None) -> None:
        """Replace an item's cached title. `None` clears it, for an item whose
        stash was discarded and whose name would otherwise outlive its
        answers. Titling an item the registry does not list does nothing."""
        for item in self._list_record(key)["items"]:
            if item["id"] == item_id:
                item["title"] = title
                self.context.session_changed()
                return

    def is_declared_done(self, key: str) -> bool:
        """Whether the user answered "no" to *add another*. Not "are all the
        items finished" — a different question, with a different answer."""
        record = self._lists().get(key)
        if record is None:
            return False
        return bool(record.get("declared_done"))

    def set_declared_done(self, key: str, declared_done: bool) -> None:
        """Record or withdraw the user's answer to *add another*."""
        self._list_record(key)["declared_done"] = declared_done
        self.context.session_changed()
