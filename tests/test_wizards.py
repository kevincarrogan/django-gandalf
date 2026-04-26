import uuid

import pytest
from django.views.generic.edit import FormView

from gandalf.wizards import Wizard
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
    )


def test_declared_form_step_creates_generated_form_view():
    wizard = Wizard().step(FirstStepForm)

    current_form_view = wizard.start

    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_initialise_creates_session_run(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()

    bound_wizard = linear_wizard.initialise(request)

    assert uuid.UUID(bound_wizard.run_id)
    assert request.session["gandalf_runs"] == {
        bound_wizard.run_id: {
            "current_step_index": 0,
        },
    }


def test_bound_wizard_initialise_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()

    linear_wizard.initialise(request)

    assert request.session.modified is True


def test_bound_wizard_retrieves_current_step_from_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "current_step_index": 1,
                },
            },
        },
    )

    bound_wizard = linear_wizard.bind(request, "existing-run")

    assert bound_wizard.run_id == "existing-run"
    assert bound_wizard.get_current_form_view().form_class is SecondStepForm


def test_bound_wizard_retrieves_current_step_from_uuid_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    run_id = uuid.uuid4()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                str(run_id): {
                    "current_step_index": 1,
                },
            },
        },
    )

    bound_wizard = linear_wizard.bind(request, run_id)

    assert bound_wizard.run_id == run_id
    assert bound_wizard.get_current_form_view().form_class is SecondStepForm


def test_bound_wizard_retrieve_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "current_step_index": 0,
                },
            },
        },
    )

    linear_wizard.bind(request, "existing-run")

    assert request.session.modified is True


def test_bound_wizard_completing_current_step_updates_current_form_view(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "current_step_index": 0,
                },
            },
        },
    )
    bound_wizard = linear_wizard.bind(request, "existing-run")

    bound_wizard.complete_current_step()

    assert bound_wizard.get_current_form_view().form_class is SecondStepForm


def test_bound_wizard_completing_current_step_persists_by_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "current_step_index": 0,
                },
            },
        },
    )
    bound_wizard = linear_wizard.bind(request, "existing-run")

    bound_wizard.complete_current_step()

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "current_step_index": 1,
        },
    }


def test_bound_wizard_progress_is_isolated_between_url_run_ids(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "first-run": {
                    "current_step_index": 0,
                },
                "second-run": {
                    "current_step_index": 0,
                },
            },
        },
    )
    first_bound_wizard = linear_wizard.bind(request, "first-run")

    first_bound_wizard.complete_current_step()
    second_bound_wizard = linear_wizard.bind(request, "second-run")

    assert first_bound_wizard.get_current_form_view().form_class is SecondStepForm
    assert second_bound_wizard.get_current_form_view().form_class is FirstStepForm
