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
    # What the run did outside itself — the record it created, the call it
    # made. Kept when `completed` is set and the state is cleared, because
    # it describes something that outlives the answers.
    meta = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "updated_at"])]


class JourneyRecord(models.Model):
    """One journey of one user: what its sections decided between them, and
    whether it has been submitted.

    The session store keeps this on the journey's record beside the runs
    and the stashes; a table keeps it on its own row, because it is the one
    part of a journey that outlives submission. `data` is the envelope
    `store.data` reads — both buckets, verbatim.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wizard_journeys",
    )
    journey = models.CharField(max_length=100)
    data = models.JSONField(default=dict)
    completed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "journey"], name="unique_journey"),
        ]


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
    journey = models.CharField(max_length=100, default="default")
    key = models.CharField(max_length=100)
    # Where an unfinished section is picked up; cleared when it finishes.
    run = models.ForeignKey(WizardRun, on_delete=models.SET_NULL, null=True, blank=True)
    # `BoundWizard.stash()` output, and the section's completion record.
    stash = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "journey", "key"], name="unique_section"
            ),
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
    journey = models.CharField(max_length=100, default="default")
    key = models.CharField(max_length=100)
    declared_done = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "journey", "key"], name="unique_collection"
            ),
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
    journey = models.CharField(max_length=100, default="default")
    collection_key = models.CharField(max_length=100)
    item_id = models.CharField(max_length=64)
    # Worked out once, when the item finished; None until then.
    title = models.CharField(max_length=255, null=True, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "journey", "collection_key", "item_id"],
                name="unique_collection_item",
            ),
        ]


class Application(models.Model):
    """The README's grant application: the record a run opens when it starts
    and submits when it finishes. Nobody typed the reference, no form
    validates it, and allocating it twice is the bug — which is why it lives
    in the run's metadata bag and not in its answers."""

    reference = models.CharField(max_length=16, unique=True)
    email = models.EmailField(blank=True)
    submitted = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"GF-{Application.objects.count() + 1:05d}"
        super().save(*args, **kwargs)

    def submit(self, email):
        self.email = email
        self.submitted = True
        self.save(update_fields=["email", "submitted"])
