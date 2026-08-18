import uuid

import pytest

from gandalf.storage import (
    RunNotFound,
    SessionStashStore,
    SessionStorage,
    StashNotFound,
)


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


def test_session_storage_initialise_creates_session_run():
    context = _Context()
    storage = SessionStorage(context)

    run_id = storage.initialise_run()

    assert uuid.UUID(run_id)
    assert context.session["gandalf_runs"] == {
        run_id: {},
    }


def test_session_storage_initialise_marks_session_modified():
    context = _Context()
    storage = SessionStorage(context)

    storage.initialise_run()

    assert context.session.modified is True


def test_session_storage_retrieve_run_preserves_url_run_id():
    context = _Context(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(context)

    run_id = storage.retrieve_run("existing-run")

    assert run_id == "existing-run"


def test_session_storage_retrieve_marks_session_modified():
    context = _Context(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(context)

    storage.retrieve_run("existing-run")

    assert context.session.modified is True


def test_session_storage_get_run_data_uses_url_run_id():
    context = _Context(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    storage = SessionStorage(context)

    run_data = storage.get_run_data("existing-run")

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_session_storage_get_run_data_accepts_uuid_run_id():
    run_id = uuid.uuid4()
    context = _Context(
        session={
            "gandalf_runs": {
                str(run_id): {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    storage = SessionStorage(context)

    run_data = storage.get_run_data(run_id)

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_session_storage_get_state_defaults_to_empty_list():
    context = _Context(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(context)

    state = storage.get_state("existing-run")

    assert state == []


def test_session_storage_set_state_persists_by_url_run_id():
    context = _Context(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(context)

    storage.set_state("existing-run", [{"step": {"name": "Ada"}}])

    assert context.session["gandalf_runs"] == {
        "existing-run": {
            "state": [{"step": {"name": "Ada"}}],
        },
    }


def test_session_storage_set_state_marks_session_modified():
    context = _Context(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(context)

    storage.set_state("existing-run", [{"step": {"name": "Ada"}}])

    assert context.session.modified is True


def test_session_storage_delete_run_removes_the_run():
    context = _Context({"gandalf_runs": {"first": {"state": []}, "second": {}}})
    storage = SessionStorage(context)

    storage.delete_run("first")

    assert context.session["gandalf_runs"] == {"second": {}}


def test_session_storage_delete_run_ignores_an_unknown_run():
    context = _Context({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(context)

    storage.delete_run("missing")

    assert context.session["gandalf_runs"] == {"first": {}}


def test_session_storage_delete_run_marks_session_modified():
    context = _Context({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(context)

    storage.delete_run("first")

    assert context.session.modified is True


def test_session_storage_retrieve_run_raises_for_an_unknown_run():
    context = _Context({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(context)

    with pytest.raises(RunNotFound):
        storage.retrieve_run("missing")


def test_session_storage_retrieve_run_raises_when_the_session_holds_no_runs():
    context = _Context()
    storage = SessionStorage(context)

    with pytest.raises(RunNotFound):
        storage.retrieve_run("first")


def test_session_storage_get_run_data_raises_for_an_unknown_run():
    context = _Context({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(context)

    with pytest.raises(RunNotFound):
        storage.get_run_data("missing")


def test_session_storage_complete_run_replaces_state_with_a_tombstone():
    context = _Context({"gandalf_runs": {"first": {"state": [{"step": {"a": "1"}}]}}})
    storage = SessionStorage(context)

    storage.complete_run("first")

    assert context.session["gandalf_runs"] == {"first": {"completed": True}}


def test_session_storage_complete_run_leaves_other_runs_alone():
    context = _Context({"gandalf_runs": {"first": {}, "second": {"state": []}}})
    storage = SessionStorage(context)

    storage.complete_run("first")

    assert context.session["gandalf_runs"]["second"] == {"state": []}


def test_session_storage_complete_run_accepts_uuid_run_id():
    run_id = uuid.uuid4()
    context = _Context({"gandalf_runs": {str(run_id): {"state": []}}})
    storage = SessionStorage(context)

    storage.complete_run(run_id)

    assert context.session["gandalf_runs"] == {str(run_id): {"completed": True}}


def test_session_storage_complete_run_is_idempotent():
    context = _Context({"gandalf_runs": {"first": {"state": []}}})
    storage = SessionStorage(context)

    storage.complete_run("first")
    storage.complete_run("first")

    assert context.session["gandalf_runs"] == {"first": {"completed": True}}


def test_session_storage_complete_run_marks_session_modified():
    context = _Context({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(context)

    storage.complete_run("first")

    assert context.session.modified is True


def test_session_storage_is_run_complete_reports_the_tombstone():
    context = _Context({"gandalf_runs": {"first": {"state": []}}})
    storage = SessionStorage(context)

    assert storage.is_run_complete("first") is False

    storage.complete_run("first")

    assert storage.is_run_complete("first") is True


def test_session_storage_is_run_complete_is_false_for_an_unknown_run():
    context = _Context({"gandalf_runs": {}})
    storage = SessionStorage(context)

    assert storage.is_run_complete("missing") is False


def test_session_storage_complete_run_prunes_the_oldest_tombstones():
    context = _Context({"gandalf_runs": {}})
    storage = SessionStorage(context)
    storage.max_completed_runs = 2

    for run_id in ("first", "second", "third"):
        context.session["gandalf_runs"][run_id] = {"state": []}
        storage.complete_run(run_id)

    assert list(context.session["gandalf_runs"]) == ["second", "third"]


def test_session_storage_pruning_never_drops_a_run_in_progress():
    context = _Context({"gandalf_runs": {"live": {"state": [{"step": {"a": "1"}}]}}})
    storage = SessionStorage(context)
    storage.max_completed_runs = 1

    storage.complete_run("first")
    storage.complete_run("second")

    assert context.session["gandalf_runs"] == {
        "live": {"state": [{"step": {"a": "1"}}]},
        "second": {"completed": True},
    }


_PAYLOAD = {"version": 1, "state": [{"step": {"name": "Ada"}}]}


def test_session_stash_store_put_and_get_round_trip():
    context = _Context()
    store = SessionStashStore(context)

    store.put("contact", _PAYLOAD)

    assert store.get("contact") == _PAYLOAD
    assert context.session["gandalf_stashes"] == {"contact": _PAYLOAD}


def test_session_stash_store_put_overwrites_an_existing_stash():
    context = _Context({"gandalf_stashes": {"contact": {"version": 1, "state": []}}})
    store = SessionStashStore(context)

    store.put("contact", _PAYLOAD)

    assert store.get("contact") == _PAYLOAD


def test_session_stash_store_put_marks_session_modified():
    context = _Context()

    SessionStashStore(context).put("contact", _PAYLOAD)

    assert context.session.modified is True


def test_session_stash_store_get_raises_for_an_unknown_key():
    store = SessionStashStore(_Context())

    with pytest.raises(StashNotFound):
        store.get("missing")


def test_session_stash_store_pop_removes_and_returns_the_stash():
    context = _Context({"gandalf_stashes": {"contact": _PAYLOAD}})
    store = SessionStashStore(context)

    payload = store.pop("contact")

    assert payload == _PAYLOAD
    assert context.session["gandalf_stashes"] == {}
    assert context.session.modified is True


def test_session_stash_store_pop_raises_for_an_unknown_key():
    store = SessionStashStore(_Context())

    with pytest.raises(StashNotFound):
        store.pop("missing")


def test_session_stash_store_delete_is_idempotent():
    context = _Context({"gandalf_stashes": {"contact": _PAYLOAD}})
    store = SessionStashStore(context)

    store.delete("contact")
    store.delete("contact")

    assert context.session["gandalf_stashes"] == {}
    assert context.session.modified is True


def test_session_stash_store_keys_lists_stored_stashes_in_order():
    context = _Context({"gandalf_stashes": {"contact": _PAYLOAD, "billing": _PAYLOAD}})
    store = SessionStashStore(context)

    assert store.keys() == ["contact", "billing"]


def test_session_stash_store_keys_is_empty_without_stashes():
    assert SessionStashStore(_Context()).keys() == []
