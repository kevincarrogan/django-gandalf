"""Storage that outlives a session — the worked example the README shows.

Gandalf ships `SessionStorage` and nothing else, because a durable backend
means models, migrations and a retention policy, and those belong to the
project rather than to the library. What the library owes you instead is a
seam small enough to swap, and this module is the proof: `BoundWizard` calls
exactly the eleven methods below, and nothing in the runtime, the walker or
the viewset reaches past them.

Four contracts are easy to miss and matter more than the rest:

* `retrieve_run` raises `RunNotFound` for a run this owner cannot serve. That
  is the whole authorisation model — scoping the queryset by owner is what
  stops one user resuming another's run.
* `complete_run` is idempotent, discards the state, and leaves the run
  *addressable*, so a revisit is answerable as finished rather than unknown.
* `get_state` returns `[]` for a completed run.
* `set_run_metadata` writes *now*, not at the end of a walk. It is the one
  seam a run uses to remember what it did elsewhere, and it is called from
  places that never persist state — `run_started()`, a GET that only
  replays. A backend that batched it would lose the record it names.

A durable hub needs **both** stores swapped, once, on the root viewset:
`storage_class` for the runs and `journey_store_class` for the bookkeeping,
and every member the hub builds gets the same two. A journey store is built
with the journey as well as the context, and its `data` and `complete()`
are the journey's own — kept on a row that survives the members being
deleted at submission. A durable *collection* needs `ModelCollectionStore`
in place of `ModelJourneyStore` — it is the journey store plus an ordered
registry, so one swap covers both halves. Swapping only one gives you
durable answers nobody can find, or a durable index into runs that have
expired.
"""

import uuid

from django.core.exceptions import ValidationError

from gandalf.storage import JourneyData, RunNotFound, StashNotFound

from .models import (
    CollectionItemRecord,
    CollectionRecord,
    JourneyRecord,
    SectionRecord,
    WizardRun,
)


class ModelStorage:
    """`SessionStorage`'s protocol, against a table scoped to the user."""

    def __init__(self, context):
        self.context = context

    def _runs(self):
        return WizardRun.objects.filter(owner=self.context.actor)

    def _get(self, run_id):
        try:
            return self._runs().get(pk=run_id)
        except (WizardRun.DoesNotExist, ValidationError, ValueError):
            # A malformed id is "no such run", not a 500 — the same answer
            # `SessionStorage` gives for a key it does not hold.
            raise RunNotFound(str(run_id))

    def initialise_run(self):
        run = WizardRun.objects.create(id=uuid.uuid4(), owner=self.context.actor)
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
        run = self._get(run_id)
        run.state = state
        run.save(update_fields=["state", "updated_at"])

    def get_run_metadata(self, run_id):
        return self._get(run_id).meta

    def set_run_metadata(self, run_id, metadata):
        run = self._get(run_id)
        run.meta = metadata
        run.save(update_fields=["meta", "updated_at"])

    def delete_run(self, run_id):
        self._runs().filter(pk=run_id).delete()

    def complete_run(self, run_id):
        # State goes, metadata stays — the same tombstone `SessionStorage`
        # leaves. The run's record of what it created elsewhere is the one
        # thing a completion page can still honestly show.
        self._runs().filter(pk=run_id).update(completed=True, state=[])

    def is_run_complete(self, run_id):
        return self._runs().filter(pk=run_id, completed=True).exists()


class ModelJourneyStore:
    """`SessionJourneyStore`'s protocol, against tables scoped to the user
    and the journey.

    The run id and the stash live on one row per member because they are two
    facts about the same thing, but they still outlive each other: finishing a
    member clears its run and leaves the stash, which is what lets a completed
    member survive its run being deleted.

    The journey's own facts — its data and its completion — live on a row of
    their own, because they are the one part of a journey that survives
    submission: `complete()` deletes the members and keeps that row.
    """

    def __init__(self, context, journey):
        self.context = context
        self.journey = str(journey)

    def _scope(self):
        return {"owner": self.context.actor, "journey": self.journey}

    def _records(self):
        return SectionRecord.objects.filter(**self._scope())

    def _record(self, key):
        return self._records().filter(key=key).first()

    def get_run(self, key):
        record = self._record(key)
        if record is None or record.run_id is None:
            return None
        return str(record.run_id)

    def set_run(self, key, run_id):
        SectionRecord.objects.update_or_create(
            **self._scope(), key=key, defaults={"run_id": run_id}
        )

    def clear_run(self, key):
        self._records().filter(key=key).update(run=None)

    def get_stash(self, key):
        record = self._record(key)
        if record is None or record.stash is None:
            raise StashNotFound(key)
        return record.stash

    def has_stash(self, key):
        return self._records().filter(key=key, stash__isnull=False).exists()

    def put_stash(self, key, payload):
        SectionRecord.objects.update_or_create(
            **self._scope(), key=key, defaults={"stash": payload}
        )

    def delete_stash(self, key):
        self._records().filter(key=key).update(stash=None)

    def keys(self):
        return list(
            self._records().filter(stash__isnull=False).values_list("key", flat=True)
        )

    # --- the journey itself ---

    def _journey(self):
        return JourneyRecord.objects.filter(**self._scope()).first()

    @property
    def data(self):
        return JourneyData(read=self._read_data, write=self._write_data)

    def _read_data(self):
        record = self._journey()
        return None if record is None else record.data

    def _write_data(self, envelope):
        # Written now, not at the end of a walk — the same contract as
        # `set_run_metadata`, for the same reason.
        JourneyRecord.objects.update_or_create(
            **self._scope(), defaults={"data": envelope}
        )

    def complete(self):
        # The members go, the journey's row stays: what its members decided
        # is what a done page still has to say.
        self._records().delete()
        JourneyRecord.objects.update_or_create(
            **self._scope(), defaults={"completed": True}
        )

    def is_complete(self):
        return JourneyRecord.objects.filter(**self._scope(), completed=True).exists()


class ModelCollectionStore(ModelJourneyStore):
    """`SessionCollectionStore`'s protocol, against tables scoped to the user
    and the journey.

    Everything `ModelJourneyStore` does — an item's run and stash live under
    the composite key the view builds — plus the registry the session store
    keeps as a list. Two things the list could not give you: `position` makes
    the order explicit rather than incidental, and the unique constraint
    settles the race where two tabs adding at once would lose an item outright.
    """

    def _items(self, key):
        return CollectionItemRecord.objects.filter(**self._scope(), collection_key=key)

    def item_ids(self, key):
        return list(self._items(key).values_list("item_id", flat=True))

    def has_item(self, key, item_id):
        return self._items(key).filter(item_id=item_id).exists()

    def add_item(self, key, item_id):
        # `position` is the count rather than max+1: removal renumbers
        # nothing, so a gap is possible and the order is what matters, not
        # the values. `get_or_create` makes adding an id already listed a
        # no-op, as the session store's early return does.
        CollectionItemRecord.objects.get_or_create(
            **self._scope(),
            collection_key=key,
            item_id=item_id,
            defaults={"position": self._items(key).count()},
        )

    def remove_item(self, key, item_id):
        self._items(key).filter(item_id=item_id).delete()

    def get_item_title(self, key, item_id):
        record = self._items(key).filter(item_id=item_id).first()
        return None if record is None else record.title

    def set_item_title(self, key, item_id, title):
        self._items(key).filter(item_id=item_id).update(title=title)

    def is_declared_done(self, key):
        return CollectionRecord.objects.filter(
            **self._scope(), key=key, declared_done=True
        ).exists()

    def set_declared_done(self, key, declared_done):
        CollectionRecord.objects.update_or_create(
            **self._scope(), key=key, defaults={"declared_done": declared_done}
        )

    def complete(self):
        CollectionItemRecord.objects.filter(**self._scope()).delete()
        CollectionRecord.objects.filter(**self._scope()).delete()
        super().complete()
