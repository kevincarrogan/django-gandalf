"""The base class a step's own `FormView` starts from."""

from django.views.generic.edit import FormView

from gandalf.form_views import StepFormView, form_view_factory
from tests.testapp.forms import FirstStepForm


def test_a_step_view_is_an_ordinary_form_view():
    assert issubclass(StepFormView, FormView)


def test_a_step_view_succeeds_back_onto_itself(rf):
    """The wizard reads only the status code of a step's response and
    discards it, so the success URL is never followed. Redirecting to the
    step's own URL is the no-op that says "this answer stands"."""
    view = StepFormView()
    view.setup(rf.post("/wizard/existing-run/first/"))

    assert view.get_success_url() == "/wizard/existing-run/first/"


def test_generated_step_views_are_built_on_the_same_base():
    """A view Gandalf generates and a view you write are the same kind of
    thing, so they answer a submission the same way."""
    generated = form_view_factory(
        FirstStepForm, template_name="testapp/linear_wizard.html"
    )

    assert issubclass(generated, StepFormView)
