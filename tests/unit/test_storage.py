import uuid

import pytest

from gandalf.storage import RunNotFound, SessionStorage


class _Session(dict):
    modified = False


class _Request:
    def __init__(self, session=None):
        self.session = _Session()
        if session:
            self.session.update(session)


def test_session_storage_initialise_creates_session_run():
    request = _Request()
    storage = SessionStorage(request)

    run_id = storage.initialise_run()

    assert uuid.UUID(run_id)
    assert request.session["gandalf_runs"] == {
        run_id: {},
    }


def test_session_storage_initialise_marks_session_modified():
    request = _Request()
    storage = SessionStorage(request)

    storage.initialise_run()

    assert request.session.modified is True


def test_session_storage_retrieve_run_preserves_url_run_id():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    run_id = storage.retrieve_run("existing-run")

    assert run_id == "existing-run"


def test_session_storage_retrieve_marks_session_modified():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    storage.retrieve_run("existing-run")

    assert request.session.modified is True


def test_session_storage_get_run_data_uses_url_run_id():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    storage = SessionStorage(request)

    run_data = storage.get_run_data("existing-run")

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_session_storage_get_run_data_accepts_uuid_run_id():
    run_id = uuid.uuid4()
    request = _Request(
        session={
            "gandalf_runs": {
                str(run_id): {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    storage = SessionStorage(request)

    run_data = storage.get_run_data(run_id)

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_session_storage_get_state_defaults_to_empty_list():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    state = storage.get_state("existing-run")

    assert state == []


def test_session_storage_set_state_persists_by_url_run_id():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    storage.set_state("existing-run", [{"step": {"name": "Ada"}}])

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "state": [{"step": {"name": "Ada"}}],
        },
    }


def test_session_storage_set_state_marks_session_modified():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    storage.set_state("existing-run", [{"step": {"name": "Ada"}}])

    assert request.session.modified is True


def test_session_storage_delete_run_removes_the_run():
    request = _Request({"gandalf_runs": {"first": {"state": []}, "second": {}}})
    storage = SessionStorage(request)

    storage.delete_run("first")

    assert request.session["gandalf_runs"] == {"second": {}}


def test_session_storage_delete_run_ignores_an_unknown_run():
    request = _Request({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(request)

    storage.delete_run("missing")

    assert request.session["gandalf_runs"] == {"first": {}}


def test_session_storage_delete_run_marks_session_modified():
    request = _Request({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(request)

    storage.delete_run("first")

    assert request.session.modified is True


def test_session_storage_retrieve_run_raises_for_an_unknown_run():
    request = _Request({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(request)

    with pytest.raises(RunNotFound):
        storage.retrieve_run("missing")


def test_session_storage_retrieve_run_raises_when_the_session_holds_no_runs():
    request = _Request()
    storage = SessionStorage(request)

    with pytest.raises(RunNotFound):
        storage.retrieve_run("first")


def test_session_storage_get_run_data_raises_for_an_unknown_run():
    request = _Request({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(request)

    with pytest.raises(RunNotFound):
        storage.get_run_data("missing")


def test_session_storage_complete_run_replaces_state_with_a_tombstone():
    request = _Request({"gandalf_runs": {"first": {"state": [{"step": {"a": "1"}}]}}})
    storage = SessionStorage(request)

    storage.complete_run("first")

    assert request.session["gandalf_runs"] == {"first": {"completed": True}}


def test_session_storage_complete_run_leaves_other_runs_alone():
    request = _Request({"gandalf_runs": {"first": {}, "second": {"state": []}}})
    storage = SessionStorage(request)

    storage.complete_run("first")

    assert request.session["gandalf_runs"]["second"] == {"state": []}


def test_session_storage_complete_run_accepts_uuid_run_id():
    run_id = uuid.uuid4()
    request = _Request({"gandalf_runs": {str(run_id): {"state": []}}})
    storage = SessionStorage(request)

    storage.complete_run(run_id)

    assert request.session["gandalf_runs"] == {str(run_id): {"completed": True}}


def test_session_storage_complete_run_is_idempotent():
    request = _Request({"gandalf_runs": {"first": {"state": []}}})
    storage = SessionStorage(request)

    storage.complete_run("first")
    storage.complete_run("first")

    assert request.session["gandalf_runs"] == {"first": {"completed": True}}


def test_session_storage_complete_run_marks_session_modified():
    request = _Request({"gandalf_runs": {"first": {}}})
    storage = SessionStorage(request)

    storage.complete_run("first")

    assert request.session.modified is True


def test_session_storage_is_run_complete_reports_the_tombstone():
    request = _Request({"gandalf_runs": {"first": {"state": []}}})
    storage = SessionStorage(request)

    assert storage.is_run_complete("first") is False

    storage.complete_run("first")

    assert storage.is_run_complete("first") is True


def test_session_storage_is_run_complete_is_false_for_an_unknown_run():
    request = _Request({"gandalf_runs": {}})
    storage = SessionStorage(request)

    assert storage.is_run_complete("missing") is False


def test_session_storage_complete_run_prunes_the_oldest_tombstones():
    request = _Request({"gandalf_runs": {}})
    storage = SessionStorage(request)
    storage.max_completed_runs = 2

    for run_id in ("first", "second", "third"):
        request.session["gandalf_runs"][run_id] = {"state": []}
        storage.complete_run(run_id)

    assert list(request.session["gandalf_runs"]) == ["second", "third"]


def test_session_storage_pruning_never_drops_a_run_in_progress():
    request = _Request({"gandalf_runs": {"live": {"state": [{"step": {"a": "1"}}]}}})
    storage = SessionStorage(request)
    storage.max_completed_runs = 1

    storage.complete_run("first")
    storage.complete_run("second")

    assert request.session["gandalf_runs"] == {
        "live": {"state": [{"step": {"a": "1"}}]},
        "second": {"completed": True},
    }
