"""Storage that outlives a session — the worked example the README shows.

Gandalf ships `SessionStorage` and nothing else, because a durable backend
means models, migrations and a retention policy, and those belong to the
project rather than to the library. What the library owes you instead is a
seam small enough to swap, and this module is the proof: `BoundWizard` calls
exactly the nine methods below, and nothing in the runtime, the walker or the
viewset reaches past them.

Three contracts are easy to miss and matter more than the rest:

* `retrieve_run` raises `RunNotFound` for a run this owner cannot serve. That
  is the whole authorisation model — scoping the queryset by owner is what
  stops one user resuming another's run.
* `complete_run` is idempotent, discards the state, and leaves the run
  *addressable*, so a revisit is answerable as finished rather than unknown.
* `get_state` returns `[]` for a completed run.

A durable hub needs **both** stores swapped: `storage_class` on every section
viewset, and `section_store_class` on the hub and on each `SectionMixin`. A
durable *collection* needs the same two, with `ModelCollectionStore` in place
of `ModelSectionStore` — it is the section store plus an ordered registry, so
one swap covers both halves. Swapping only one gives you durable answers
nobody can find, or a durable index into runs that have expired.
"""

import uuid

from django.core.exceptions import ValidationError

from gandalf.storage import RunNotFound, StashNotFound

from .models import (
    CollectionItemRecord,
    CollectionRecord,
    SectionRecord,
    WizardRun,
)


class ModelStorage:
    """`SessionStorage`'s protocol, against a table scoped to the user."""

    def __init__(self, request):
        self.request = request

    def _runs(self):
        return WizardRun.objects.filter(owner=self.request.user)

    def _get(self, run_id):
        try:
            return self._runs().get(pk=run_id)
        except (WizardRun.DoesNotExist, ValidationError, ValueError):
            # A malformed id is "no such run", not a 500 — the same answer
            # `SessionStorage` gives for a key it does not hold.
            raise RunNotFound(str(run_id))

    def initialise_run(self):
        run = WizardRun.objects.create(id=uuid.uuid4(), owner=self.request.user)
        return str(run.pk)

    def retrieve_run(self, run_id):
        self._get(run_id)
        return str(run_id)

    def get_run_data(self, run_id):
        run = self._get(run_id)
        if run.completed:
            return {"completed": True}
        return {"state": run.state}

    def get_state(self, run_id):
        return self.get_run_data(run_id).get("state", [])

    def set_state(self, run_id, state):
        run = self._get(run_id)
        run.state = state
        run.save(update_fields=["state", "updated_at"])

    def delete_run(self, run_id):
        self._runs().filter(pk=run_id).delete()

    def complete_run(self, run_id):
        self._runs().filter(pk=run_id).update(completed=True, state=[])

    def is_run_complete(self, run_id):
        return self._runs().filter(pk=run_id, completed=True).exists()


class ModelSectionStore:
    """`SessionSectionStore`'s protocol, against a table scoped to the user.

    The run id and the stash live on one row per section because they are two
    facts about the same thing, but they still outlive each other: finishing a
    section clears its run and leaves the stash, which is what lets a completed
    section survive its run being deleted.
    """

    def __init__(self, request):
        self.request = request

    def _records(self):
        return SectionRecord.objects.filter(owner=self.request.user)

    def _record(self, key):
        return self._records().filter(key=key).first()

    def get_run(self, key):
        record = self._record(key)
        if record is None or record.run_id is None:
            return None
        return str(record.run_id)

    def set_run(self, key, run_id):
        SectionRecord.objects.update_or_create(
            owner=self.request.user, key=key, defaults={"run_id": run_id}
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
            owner=self.request.user, key=key, defaults={"stash": payload}
        )

    def delete_stash(self, key):
        self._records().filter(key=key).update(stash=None)

    def keys(self):
        return list(
            self._records().filter(stash__isnull=False).values_list("key", flat=True)
        )


class ModelCollectionStore(ModelSectionStore):
    """`SessionCollectionStore`'s protocol, against tables scoped to the user.

    Everything `ModelSectionStore` does — an item's run and stash live under
    the composite key the view builds — plus the registry the session store
    keeps as a list. Two things the list could not give you: `position` makes
    the order explicit rather than incidental, and the unique constraint
    settles the race where two tabs adding at once would lose an item outright.
    """

    def _items(self, key):
        return CollectionItemRecord.objects.filter(
            owner=self.request.user, collection_key=key
        )

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
            owner=self.request.user,
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
            owner=self.request.user, key=key, declared_done=True
        ).exists()

    def set_declared_done(self, key, declared_done):
        CollectionRecord.objects.update_or_create(
            owner=self.request.user, key=key, defaults={"declared_done": declared_done}
        )
