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

    current_form_view = wizard.start

    assert returned_wizard is wizard
    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_wizard_configure_returns_configured_wizard():
    wizard = Wizard().step(FirstStepForm)

    configured_wizard = wizard.configure()

    assert isinstance(configured_wizard, ConfiguredWizard)
    assert configured_wizard.start is wizard.start
    assert configured_wizard.steps == wizard.steps
    assert configured_wizard.configuration == {}


def test_wizard_does_not_expose_runtime_binding_without_configure():
    wizard = Wizard().step(FirstStepForm)

    assert not hasattr(wizard, "initialise")
    assert not hasattr(wizard, "bind")


def test_bound_wizard_initialise_creates_session_run(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()

    bound_wizard = linear_wizard.initialise(request)

    assert uuid.UUID(bound_wizard.run_id)
    assert request.session["gandalf_runs"] == {
        bound_wizard.run_id: {},
    }


def test_bound_wizard_initialise_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()

    linear_wizard.initialise(request)

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

    bound_wizard = linear_wizard.bind(request, "existing-run")
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

    bound_wizard = linear_wizard.bind(request, run_id)
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

    linear_wizard.bind(request, "existing-run")

    assert request.session.modified is True


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
    bound_wizard = linear_wizard.bind(request, "existing-run")

    bound_wizard.submit({"name": "Ada"}, "testapp/linear_wizard.html")
    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert response.context_data["form"].__class__ is SecondStepForm


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
    bound_wizard = linear_wizard.bind(request, "existing-run")

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
    first_bound_wizard = linear_wizard.bind(request, "first-run")

    first_bound_wizard.submit(
        {"name": "Ada"},
        "testapp/linear_wizard.html",
    )
    second_bound_wizard = linear_wizard.bind(request, "second-run")
    first_response = first_bound_wizard.replay("testapp/linear_wizard.html")
    second_response = second_bound_wizard.replay("testapp/linear_wizard.html")

    assert first_response.context_data["form"].__class__ is SecondStepForm
    assert second_response.context_data["form"].__class__ is FirstStepForm


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
    bound_wizard = linear_wizard.bind(request, "existing-run")

    response = bound_wizard.replay("testapp/linear_wizard.html")

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is SecondStepForm
    assert TrackingFirstStepFormView.form_valid_call_count == 1
