import uuid

import pytest
from django.views.generic.edit import FormView

from gandalf.wizards import ConfiguredWizard, Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


class _Session(dict):
    modified = False


@pytest.fixture
def request_with_session_factory(rf):
    def build_request(path="/wizard/", data=None, method="get", session=None):
        request_factory_method = getattr(rf, method)
        request = request_factory_method(path, data=data or {})
        request.session = _Session()
        if session:
            request.session.update(session)
        return request

    return build_request


@pytest.fixture
def linear_wizard():
    return (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
        .configure()
    )


def test_declared_form_step_creates_generated_form_view():
    wizard = Wizard()

    returned_wizard = wizard.step(FirstStepForm)

    current_form_view = wizard.steps[0]

    assert returned_wizard is wizard
    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_wizard_does_not_proxy_bound_wizard_lifecycle_methods():
    wizard = Wizard()

    assert not hasattr(wizard, "initialise")
    assert not hasattr(wizard, "bind")


def test_get_bound_wizard_uses_configured_storage_class(request_with_session_factory):
    class FakeStorage:
        def __init__(self, request):
            self.request = request

    request = request_with_session_factory()
    wizard = Wizard().configure(storage_class=FakeStorage)

    bound_wizard = wizard.get_bound_wizard(request)

    assert isinstance(bound_wizard.storage, FakeStorage)
    assert bound_wizard.storage.request is request


def test_wizard_configure_returns_configured_wizard():
    wizard = Wizard().step(FirstStepForm)

    configured_wizard = wizard.configure()

    assert isinstance(configured_wizard, ConfiguredWizard)
    assert configured_wizard.steps == wizard.steps
    assert configured_wizard.configuration == {}


def test_bound_wizard_initialise_creates_session_run(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()
    bound_wizard = linear_wizard.get_bound_wizard(request)

    bound_wizard.initialise()

    assert uuid.UUID(bound_wizard.run_id)
    assert request.session["gandalf_runs"] == {
        bound_wizard.run_id: {},
    }


def test_bound_wizard_initialise_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()
    bound_wizard = linear_wizard.get_bound_wizard(request)

    bound_wizard.initialise()

    assert request.session.modified is True


def test_bound_wizard_replays_submissions_from_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [{"name": "Ada"}],
                },
            },
        },
    )

    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")
    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert bound_wizard.run_id == "existing-run"
    assert response.context_data["form"].__class__ is SecondStepForm


def test_bound_wizard_replays_submissions_from_uuid_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    run_id = uuid.uuid4()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                str(run_id): {
                    "submissions": [{"name": "Ada"}],
                },
            },
        },
    )

    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve(run_id)
    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert bound_wizard.run_id == run_id
    assert response.context_data["form"].__class__ is SecondStepForm


def test_bound_wizard_retrieve_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )

    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    assert request.session.modified is True


def test_bound_wizard_get_run_data_returns_current_run_data(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [{"name": "Ada"}],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    run_data = bound_wizard.get_run_data()

    assert run_data == {
        "submissions": [{"name": "Ada"}],
    }


def test_bound_wizard_replays_submissions_to_render_next_form_view(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"}, "testapp/linear_wizard.html")
    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert response.context_data["form"].__class__ is SecondStepForm


def test_bound_wizard_replay_returns_invalid_stored_step_response(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [{"name": ""}],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is FirstStepForm
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }


def test_bound_wizard_persists_submissions_by_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"}, "testapp/linear_wizard.html")

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "submissions": [{"name": "Ada"}],
        },
    }


def test_bound_wizard_submissions_are_isolated_between_url_run_ids(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "first-run": {},
                "second-run": {},
            },
        },
    )
    first_bound_wizard = linear_wizard.get_bound_wizard(request)
    first_bound_wizard.retrieve("first-run")

    first_bound_wizard.submit(
        {"name": "Ada"},
        "testapp/linear_wizard.html",
    )
    second_bound_wizard = linear_wizard.get_bound_wizard(request)
    second_bound_wizard.retrieve("second-run")
    first_response = first_bound_wizard.replay("testapp/linear_wizard.html")
    second_response = second_bound_wizard.replay("testapp/linear_wizard.html")

    assert first_response.context_data["form"].__class__ is SecondStepForm
    assert second_response.context_data["form"].__class__ is FirstStepForm


def test_bound_wizard_preserves_valid_previous_submissions_when_updating_next_step(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [{"name": "Ada"}],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit(
        {"email": "ada@example.com"},
        "testapp/linear_wizard.html",
    )

    assert request.session["gandalf_runs"]["existing-run"] == {
        "submissions": [
            {"name": "Ada"},
            {"email": "ada@example.com"},
        ],
    }


def test_bound_wizard_replaces_invalid_stored_submission(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [{"name": ""}],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit(
        {"name": "Ada"},
        "testapp/linear_wizard.html",
    )

    assert request.session["gandalf_runs"]["existing-run"] == {
        "submissions": [
            {"name": "Ada"},
        ],
    }


def test_bound_wizard_does_not_append_submission_after_complete_path(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [
                        {"name": "Ada"},
                        {"email": "ada@example.com"},
                    ],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit(
        {"email": "grace@example.com"},
        "testapp/linear_wizard.html",
    )

    assert request.session["gandalf_runs"]["existing-run"] == {
        "submissions": [
            {"name": "Ada"},
            {"email": "ada@example.com"},
        ],
    }


def test_bound_wizard_replay_returns_none_after_complete_path(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [
                        {"name": "Ada"},
                        {"email": "ada@example.com"},
                    ],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert response is None


def test_bound_wizard_replays_submissions_through_form_view_form_valid(
    request_with_session_factory,
    linear_wizard,
):
    class TrackingFirstStepFormView(FormView):
        form_class = FirstStepForm
        form_valid_call_count = 0

        def get_success_url(self):
            return self.request.path

        def form_valid(self, form):
            self.__class__.form_valid_call_count += 1
            return super().form_valid(form)

    linear_wizard.steps[0] = TrackingFirstStepFormView
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "submissions": [{"name": "Ada"}],
                },
            },
        },
    )
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is SecondStepForm
    assert TrackingFirstStepFormView.form_valid_call_count == 1
