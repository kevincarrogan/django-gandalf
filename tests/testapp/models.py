"""Models backing the durable-storage example.

Gandalf ships no models and no migrations — `SessionStorage` is the only
backend it carries, and `storage_class` is the seam a project swaps. These
two models exist to *prove* that seam is sufficient: `tests/testapp/durable.py`
implements the full storage protocol against them, and
`tests/functional/test_durable_storage.py` drives a whole hub through it.

They are the code the README shows, checked in so it is compiled and tested
rather than left to rot in prose.
"""

from django.conf import settings
from django.db import models


class WizardRun(models.Model):
    """One run of one wizard, owned by a user rather than by a session."""

    id = models.UUIDField(primary_key=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wizard_runs"
    )
    # The positional state list `BoundWizard` reads and writes, verbatim.
    state = models.JSONField(default=list)
    # Completion is a flag rather than a deletion: a finished run stays
    # addressable so a revisit answers "this one is done" rather than "no
    # such run" — the same tombstone `SessionStorage` leaves behind.
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "updated_at"])]


class SectionRecord(models.Model):
    """A hub's bookkeeping for one section of one user's journey.

    The unique constraint is what a session-backed store cannot offer: two
    tabs entering the same section race to register a run, and the database
    settles it rather than last-write-wins.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wizard_sections",
    )
    key = models.CharField(max_length=100)
    # Where an unfinished section is picked up; cleared when it finishes.
    run = models.ForeignKey(WizardRun, on_delete=models.SET_NULL, null=True, blank=True)
    # `BoundWizard.stash()` output, and the section's completion record.
    stash = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="unique_section"),
        ]


class CollectionRecord(models.Model):
    """One collection of one user's journey: whether they have said there is
    nothing more to add.

    Its own row rather than a flag denormalised onto every item, because it is
    a fact about the collection and survives having no items at all — which is
    exactly the state "any other income? no" leaves behind.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wizard_collections",
    )
    key = models.CharField(max_length=100)
    declared_done = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="unique_collection"),
        ]


class CollectionItemRecord(models.Model):
    """One item of one collection, and the title it cached when it last
    finished.

    `position` is what the session store gets for free from list order and a
    table does not. The unique constraint is what the session store cannot
    offer at all: two tabs adding at once both read the same list, both append
    one, and the session loses an item outright — not overwritten with an
    equivalent value, gone. Here the database settles it.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wizard_collection_items",
    )
    collection_key = models.CharField(max_length=100)
    item_id = models.CharField(max_length=64)
    # Worked out once, when the item finished; None until then.
    title = models.CharField(max_length=255, null=True, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "collection_key", "item_id"],
                name="unique_collection_item",
            ),
        ]
