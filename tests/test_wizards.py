from django.views.generic.edit import FormView

from gandalf.wizards import Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


def test_get_current_form_view_returns_first_declared_form_view():
    wizard = Wizard().step(FirstStepForm)

    current_form_view = wizard.get_current_form_view()

    assert issubclass(current_form_view, FormView)
    assert current_form_view.form_class is FirstStepForm


def test_completing_current_step_updates_current_form_view():
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )

    wizard.complete_current_step()
    current_form_view = wizard.get_current_form_view()

    assert current_form_view.form_class is SecondStepForm
