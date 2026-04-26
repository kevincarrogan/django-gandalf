import pytest
from django.views.generic.edit import FormView

from gandalf.wizards import Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


@pytest.fixture
def request_with_session_factory(rf):
    def build_request(path="/wizard/"):
        request = rf.get(path)
        request.session = {}
        return request

    return build_request


def test_get_current_form_view_returns_first_declared_form_view():
    wizard = Wizard().step(FirstStepForm)

    current_form_view = wizard.get_current_form_view()

    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_starts_with_first_declared_form_view(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )

    bound_wizard = wizard.bind(request_with_session_factory())
    current_form_view = bound_wizard.get_current_form_view()

    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_completing_current_step_updates_current_form_view(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )
    bound_wizard = wizard.bind(request_with_session_factory())

    bound_wizard.complete_current_step()
    current_form_view = bound_wizard.get_current_form_view()

    assert current_form_view.form_class is SecondStepForm


def test_bound_wizard_progress_is_isolated_between_bindings(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )
    first_bound_wizard = wizard.bind(request_with_session_factory())
    second_bound_wizard = wizard.bind(request_with_session_factory())

    first_bound_wizard.complete_current_step()

    assert first_bound_wizard.get_current_form_view().form_class is SecondStepForm
    assert second_bound_wizard.get_current_form_view().form_class is FirstStepForm
