"""Unit coverage for `SessionSectionStore` — a hub's bookkeeping.

Two mappings, because they answer different questions and outlive each other:
a run id says where an unfinished section can be picked up and is forgotten the
moment it finishes; a stash payload *is* the section's completion, and a hub
reads it with no run involved at all.
"""

import pytest

from gandalf.storage import SessionSectionStore, StashNotFound


class _Session(dict):
    modified = False


class _Request:
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


# --- the run registry ------------------------------------------------------


def test_section_store_remembers_the_run_a_section_is_answered_in():
    request = _Request()
    store = SessionSectionStore(request)

    store.set_run("contact", "run-1")

    assert store.get_run("contact") == "run-1"
    assert request.session["gandalf_section_runs"] == {"contact": "run-1"}
    assert request.session.modified is True


def test_section_store_has_no_run_for_a_section_never_entered():
    store = SessionSectionStore(_Request())

    assert store.get_run("contact") is None


def test_section_store_set_run_replaces_the_recorded_run():
    store = SessionSectionStore(_Request({"gandalf_section_runs": {"c": "run-1"}}))

    store.set_run("c", "run-2")

    assert store.get_run("c") == "run-2"


def test_section_store_clear_run_forgets_an_unknown_section_without_error():
    """Idempotent, like `delete_run`: callers need not check first."""
    request = _Request({"gandalf_section_runs": {"contact": "run-1"}})
    store = SessionSectionStore(request)

    store.clear_run("contact")
    store.clear_run("contact")

    assert store.get_run("contact") is None
    assert request.session.modified is True


# --- the completion record -------------------------------------------------


def test_section_store_keeps_a_finished_sections_stash():
    request = _Request()
    store = SessionSectionStore(request)

    store.put_stash("contact", _PAYLOAD)

    assert store.get_stash("contact") == _PAYLOAD
    assert store.has_stash("contact") is True


def test_section_store_has_stash_answers_without_raising():
    """What a hub row asks — the raising `get_stash` is for the entry path."""
    store = SessionSectionStore(_Request())

    assert store.has_stash("contact") is False
    with pytest.raises(StashNotFound):
        store.get_stash("contact")


def test_section_store_delete_stash_forgets_an_unknown_key_without_error():
    store = SessionSectionStore(_Request({"gandalf_stashes": {"contact": _PAYLOAD}}))

    store.delete_stash("contact")
    store.delete_stash("contact")

    assert store.has_stash("contact") is False


def test_section_store_keys_are_the_sections_holding_a_stash():
    store = SessionSectionStore(_Request())
    store.put_stash("contact", _PAYLOAD)
    store.put_stash("address", _PAYLOAD)
    store.set_run("employment", "run-1")

    assert store.keys() == ["contact", "address"]


def test_section_store_shares_the_stash_stores_key_space():
    """A project already stashing into the session keeps the same keys."""
    request = _Request()
    SessionSectionStore(request).put_stash("contact", _PAYLOAD)

    assert request.session["gandalf_stashes"] == {"contact": _PAYLOAD}


def test_a_run_and_a_stash_under_one_key_are_independent():
    """Re-opening a completed section gives it a live run again, and the
    stash it was re-opened from stays put until the section completes anew."""
    store = SessionSectionStore(_Request())
    store.put_stash("contact", _PAYLOAD)

    store.set_run("contact", "run-2")

    assert store.get_run("contact") == "run-2"
    assert store.has_stash("contact") is True
