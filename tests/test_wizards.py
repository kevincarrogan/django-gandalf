from django.views.generic.edit import FormView

from gandalf.wizards import Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


def test_get_current_form_view_returns_first_declared_form_view():
    wizard = Wizard().step(FirstStepForm)

    current_form_view = wizard.get_current_form_view()

    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_starts_with_first_declared_form_view(rf):
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )

    bound_wizard = wizard.bind(rf.get("/wizard/"))
    current_form_view = bound_wizard.get_current_form_view()

    assert current_form_view.form_class is FirstStepForm


def test_bound_wizard_completing_current_step_updates_current_form_view(rf):
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )
    bound_wizard = wizard.bind(rf.get("/wizard/"))

    bound_wizard.complete_current_step()
    current_form_view = bound_wizard.get_current_form_view()

    assert current_form_view.form_class is SecondStepForm


def test_bound_wizard_progress_is_isolated_between_bindings(rf):
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )
    first_bound_wizard = wizard.bind(rf.get("/wizard/"))
    second_bound_wizard = wizard.bind(rf.get("/wizard/"))

    first_bound_wizard.complete_current_step()

    assert first_bound_wizard.get_current_form_view().form_class is SecondStepForm
    assert second_bound_wizard.get_current_form_view().form_class is FirstStepForm
