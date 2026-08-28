"""Unit coverage for `SessionSectionStore` — one journey's bookkeeping.

Two mappings per section, because they answer different questions and outlive
each other: a run id says where an unfinished section can be picked up and is
forgotten the moment it finishes; a stash payload *is* the section's
completion, and a hub reads it with no run involved at all. Then what the
journey itself keeps: the facts its sections decided, and its own completion.
Everything sits under the journey's key, so two journeys in one session never
see each other.
"""

import pytest

from gandalf.storage import SessionSectionStore, StashNotFound


class _Session(dict):
    modified = False


class _Context:
    """As much of a `WizardContext` as a session-backed storage reads.

    A storage is built from the walk's environment rather than from a
    request: it reads the session through the context, and says when it
    has changed one.
    """

    def __init__(self, session=None):
        self.session = _Session()
        if session:
            self.session.update(session)

    def session_changed(self):
        # `WizardContext` marks the session and then writes it back when
        # nothing else will. A dict has nowhere to write it back to, so
        # what a storage's caller sees of the call is the mark.
        self.session.modified = True


_PAYLOAD = {"version": 1, "label": "contact", "state": [{"step": {"name": "Ada"}}]}


def _seeded(record, journey="default"):
    return _Context({"gandalf_journeys": {journey: record}})


# --- the run registry ------------------------------------------------------


def test_section_store_remembers_the_run_a_section_is_answered_in():
    context = _Context()
    store = SessionSectionStore(context, "default")

    store.set_run("contact", "run-1")

    assert store.get_run("contact") == "run-1"
    assert context.session["gandalf_journeys"] == {
        "default": {"runs": {"contact": "run-1"}}
    }
    assert context.session.modified is True


def test_section_store_has_no_run_for_a_section_never_entered():
    store = SessionSectionStore(_Context(), "default")

    assert store.get_run("contact") is None


def test_section_store_set_run_replaces_the_recorded_run():
    store = SessionSectionStore(_seeded({"runs": {"c": "run-1"}}), "default")

    store.set_run("c", "run-2")

    assert store.get_run("c") == "run-2"


def test_section_store_clear_run_forgets_an_unknown_section_without_error():
    """Idempotent, like `delete_run`: callers need not check first."""
    context = _seeded({"runs": {"contact": "run-1"}})
    store = SessionSectionStore(context, "default")

    store.clear_run("contact")
    store.clear_run("contact")

    assert store.get_run("contact") is None
    assert context.session.modified is True


# --- the completion record -------------------------------------------------


def test_section_store_keeps_a_finished_sections_stash():
    context = _Context()
    store = SessionSectionStore(context, "default")

    store.put_stash("contact", _PAYLOAD)

    assert store.get_stash("contact") == _PAYLOAD
    assert store.has_stash("contact") is True


def test_section_store_has_stash_answers_without_raising():
    """What a hub row asks — the raising `get_stash` is for the entry path."""
    store = SessionSectionStore(_Context(), "default")

    assert store.has_stash("contact") is False
    with pytest.raises(StashNotFound):
        store.get_stash("contact")


def test_section_store_delete_stash_forgets_an_unknown_key_without_error():
    store = SessionSectionStore(_seeded({"stashes": {"contact": _PAYLOAD}}), "default")

    store.delete_stash("contact")
    store.delete_stash("contact")

    assert store.has_stash("contact") is False


def test_section_store_keys_are_the_sections_holding_a_stash():
    store = SessionSectionStore(_Context(), "default")
    store.put_stash("contact", _PAYLOAD)
    store.put_stash("address", _PAYLOAD)
    store.set_run("employment", "run-1")

    assert store.keys() == ["contact", "address"]


def test_a_journeys_stashes_are_a_stash_store_kept_in_its_record():
    """The same class a caller uses by hand, pointed at the journey: one
    implementation, two homes, and nothing under the top-level key."""
    from gandalf.storage import SessionStashStore

    context = _Context()
    store = SessionSectionStore(context, "app-1")

    store.stashes.put("contact", _PAYLOAD)

    assert isinstance(store.stashes, SessionStashStore)
    assert store.get_stash("contact") == _PAYLOAD
    assert store.stashes.pop("contact") == _PAYLOAD
    assert store.has_stash("contact") is False
    assert "gandalf_stashes" not in context.session


def test_a_run_and_a_stash_under_one_key_are_independent():
    """Re-opening a completed section gives it a live run again, and the
    stash it was re-opened from stays put until the section completes anew."""
    store = SessionSectionStore(_Context(), "default")
    store.put_stash("contact", _PAYLOAD)

    store.set_run("contact", "run-2")

    assert store.get_run("contact") == "run-2"
    assert store.has_stash("contact") is True


def test_reading_a_journey_never_written_does_not_dirty_the_session():
    """A render is all reads, and a session marked modified on every GET is
    a session written back on every GET."""
    context = _Context()
    store = SessionSectionStore(context, "default")

    store.get_run("contact")
    store.has_stash("contact")
    store.keys()
    store.is_complete()
    store.data.get("anything")

    assert context.session.modified is False
    assert "gandalf_journeys" not in context.session


# --- two journeys in one session -------------------------------------------


def test_journeys_keep_their_own_bookkeeping():
    """Two applications in two tabs are two records: a section key means the
    same thing in each and nothing leaks between them."""
    context = _Context()
    first = SessionSectionStore(context, "app-1")
    second = SessionSectionStore(context, "app-2")

    first.set_run("contact", "run-1")
    first.put_stash("address", _PAYLOAD)
    first.data["applicant_type"] = "business"

    assert second.get_run("contact") is None
    assert second.has_stash("address") is False
    assert second.keys() == []
    assert "applicant_type" not in second.data
    assert set(context.session["gandalf_journeys"]) == {"app-1"}


def test_a_journeys_identity_is_a_string_whatever_it_was_given():
    """A UUID from a URL kwarg and its string form name one journey."""
    import uuid

    context = _Context()
    journey = uuid.uuid4()
    SessionSectionStore(context, journey).set_run("contact", "run-1")

    assert SessionSectionStore(context, str(journey)).get_run("contact") == "run-1"


# --- what the sections decided ---------------------------------------------


def test_journey_data_is_written_through_to_the_session():
    context = _Context()
    store = SessionSectionStore(context, "default")

    store.data["employment_status"] = "employed"

    assert store.data["employment_status"] == "employed"
    assert context.session["gandalf_journeys"]["default"]["data"] == {
        "journey": {"employment_status": "employed"}
    }
    assert context.session.modified is True


def test_journey_data_is_read_back_by_a_fresh_handle():
    """The bag holds nothing: a handle taken at the top of a request sees a
    write made further down it."""
    context = _Context()
    SessionSectionStore(context, "default").data["a"] = 1

    assert SessionSectionStore(context, "default").data["a"] == 1


def test_a_sections_own_data_cannot_tread_on_the_journeys():
    store = SessionSectionStore(_Context(), "default")

    store.data["status"] = "journey"
    store.data.for_section("employment")["status"] = "section"
    store.data.for_section("contact")["status"] = "other"

    assert store.data["status"] == "journey"
    assert store.data.for_section("employment")["status"] == "section"
    assert store.data.for_section("contact")["status"] == "other"


def test_for_section_addresses_from_the_root():
    """`for_section(a).for_section(b)` is `for_section(b)`, not a nesting
    nobody asked for."""
    store = SessionSectionStore(_Context(), "default")

    store.data.for_section("a").for_section("b")["x"] = 1

    assert store.data.for_section("b")["x"] == 1
    assert "x" not in store.data.for_section("a")


def test_journey_data_hands_back_a_copy():
    """Mutating what was read must not reach into the session unmarked."""
    context = _Context()
    store = SessionSectionStore(context, "default")
    store.data["nested"] = {"a": 1}
    context.session.modified = False

    store.data["nested"]["a"] = 2

    assert store.data["nested"] == {"a": 1}
    assert context.session.modified is False


# --- the journey's own completion ------------------------------------------


def test_completing_a_journey_discards_its_sections_and_keeps_its_data():
    """The counterpart of `complete_run`: the answers go, what they decided
    stays, and the tombstone makes a revisit answerable."""
    context = _Context()
    store = SessionSectionStore(context, "default")
    store.set_run("contact", "run-1")
    store.put_stash("address", _PAYLOAD)
    store.data["reference"] = "APP-1"

    store.complete()

    assert store.is_complete() is True
    assert store.get_run("contact") is None
    assert store.has_stash("address") is False
    assert store.keys() == []
    assert store.data["reference"] == "APP-1"
    assert context.session["gandalf_journeys"]["default"] == {
        "completed": True,
        "data": {"journey": {"reference": "APP-1"}},
    }


def test_a_journey_nobody_has_submitted_is_not_complete():
    assert SessionSectionStore(_Context(), "default").is_complete() is False


def test_completing_a_journey_is_idempotent():
    context = _Context()
    store = SessionSectionStore(context, "default")
    store.data["reference"] = "APP-1"

    store.complete()
    store.complete()

    assert store.is_complete() is True
    assert store.data["reference"] == "APP-1"


def test_only_the_most_recently_completed_journeys_are_kept():
    """A tombstone keeps the journey's data, so a session cannot hold them
    without bound; the oldest go first, and a journey still in progress is
    never pruned."""
    context = _Context()
    SessionSectionStore(context, "live").set_run("contact", "run-1")
    for number in range(SessionSectionStore.max_completed_journeys + 2):
        SessionSectionStore(context, f"done-{number}").complete()

    journeys = context.session["gandalf_journeys"]
    assert "live" in journeys
    assert "done-0" not in journeys
    assert "done-1" not in journeys
    assert "done-2" in journeys
    assert f"done-{SessionSectionStore.max_completed_journeys + 1}" in journeys


def test_completing_a_journey_again_moves_it_to_the_back_of_the_queue():
    context = _Context()
    SessionSectionStore(context, "a").complete()
    SessionSectionStore(context, "b").complete()

    SessionSectionStore(context, "a").complete()

    assert list(context.session["gandalf_journeys"]) == ["b", "a"]
