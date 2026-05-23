import uuid

from gandalf.storage import SessionStorage


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
