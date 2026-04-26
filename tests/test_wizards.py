import uuid

import pytest
from django.forms import HiddenInput
from django.views.generic.edit import FormView

from gandalf.wizards import Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


@pytest.fixture
def request_with_session_factory(rf):
    def build_request(path="/wizard/", data=None, method="get", session=None):
        request_factory_method = getattr(rf, method)
        request = request_factory_method(path, data=data or {})
        request.session = {}
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


def test_get_current_form_view_returns_first_declared_form_view():
    wizard = Wizard().step(FirstStepForm)

    current_form_view = wizard.get_current_form_view()

    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_starts_with_first_declared_form_view(
    request_with_session_factory,
    linear_wizard,
):
    bound_wizard = linear_wizard.bind(request_with_session_factory())
    current_form_view = bound_wizard.get_current_form_view()

    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_completing_current_step_updates_current_form_view(
    request_with_session_factory,
    linear_wizard,
):
    bound_wizard = linear_wizard.bind(request_with_session_factory())

    bound_wizard.complete_current_step()
    current_form_view = bound_wizard.get_current_form_view()

    assert current_form_view.form_class is SecondStepForm


def test_bound_wizard_progress_is_isolated_between_bindings(
    request_with_session_factory,
    linear_wizard,
):
    first_bound_wizard = linear_wizard.bind(request_with_session_factory())
    second_bound_wizard = linear_wizard.bind(request_with_session_factory())

    first_bound_wizard.complete_current_step()

    assert first_bound_wizard.get_current_form_view().form_class is SecondStepForm
    assert second_bound_wizard.get_current_form_view().form_class is FirstStepForm


def test_bound_wizard_generates_run_id_without_management_form(
    request_with_session_factory,
    linear_wizard,
):
    bound_wizard = linear_wizard.bind(request_with_session_factory())

    assert uuid.UUID(bound_wizard.run_id)


def test_bound_wizard_uses_submitted_management_form_run_id(
    request_with_session_factory,
    linear_wizard,
):
    bound_wizard = linear_wizard.bind(
        request_with_session_factory(
            method="post",
            data={"run_id": "existing-run"},
        )
    )

    assert bound_wizard.run_id == "existing-run"


def test_bound_wizard_restores_current_step_from_session(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        data={"run_id": "existing-run"},
        session={
            "gandalf_runs": {
                "existing-run": {
                    "current_step_index": 1,
                },
            },
        },
    )

    bound_wizard = linear_wizard.bind(request)

    assert bound_wizard.get_current_form_view().form_class is SecondStepForm


def test_bound_wizard_persists_current_step_by_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        method="post",
        data={"run_id": "existing-run"},
    )
    bound_wizard = linear_wizard.bind(request)

    bound_wizard.complete_current_step()

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "current_step_index": 1,
        },
    }


def test_bound_wizard_management_form_contains_current_run_id(
    request_with_session_factory,
    linear_wizard,
):
    bound_wizard = linear_wizard.bind(request_with_session_factory())

    management_form = bound_wizard.get_management_form()

    assert management_form.initial["run_id"] == bound_wizard.run_id
    assert isinstance(management_form.fields["run_id"].widget, HiddenInput)
