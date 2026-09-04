"""The base class a step's own `FormView` starts from."""

import datetime

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.views.generic.edit import FormView

from gandalf.form_views import FormSetStepView, StepFormView, form_view_factory
from tests.testapp.forms import FirstStepForm, ProjectStartForm


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


class _ShoutingWidget(forms.TextInput):
    """A widget that names its own POST key, to prove the seam exists for a
    widget whose layout Django cannot state for it."""

    def value_from_datadict(self, data, files, name):
        return data.get(f"{name}!")

    def value_to_datadict(self, name, value):
        return {f"{name}!": value}


class _ShoutingForm(forms.Form):
    motto = forms.CharField(widget=_ShoutingWidget)


class _DateStepView(StepFormView):
    form_class = ProjectStartForm
    template_name = "testapp/linear_wizard.html"


class _PrefixedDateStepView(_DateStepView):
    prefix = "project"


class _ShoutingStepView(StepFormView):
    form_class = _ShoutingForm
    template_name = "testapp/linear_wizard.html"


def _submission(view_class, answer, rf):
    view = view_class()
    view.setup(rf.get("/wizard/run/step/"))
    return view.get_submission(answer)


def test_a_multi_widget_answer_posts_under_the_widgets_own_keys(rf):
    """One answered date, three boxes. `start_date` names no input, so an
    answer keyed by the field name binds to nothing when it goes back."""
    submission = _submission(
        _DateStepView, {"start_date": datetime.date(2026, 9, 3)}, rf
    )

    assert submission == {
        "start_date_0": 3,
        "start_date_1": 9,
        "start_date_2": 2026,
    }


def test_a_prefixed_multi_widget_answer_keeps_the_prefix_and_the_suffixes(rf):
    """Both renamings at once, in the order a browser sends them: the
    prefix goes on the field, the widget's suffix goes on the prefixed
    name."""
    submission = _submission(
        _PrefixedDateStepView, {"start_date": datetime.date(2026, 9, 3)}, rf
    )

    assert sorted(submission) == [
        "project-start_date_0",
        "project-start_date_1",
        "project-start_date_2",
    ]


def test_a_widget_may_say_how_its_value_goes_back_out(rf):
    """The seam for a widget Django cannot describe: `MultiWidget` is the
    default, and a widget that names its keys another way says so itself."""
    submission = _submission(_ShoutingStepView, {"motto": "onwards"}, rf)

    assert submission == {"motto!": "onwards"}


def test_a_plain_field_still_posts_under_its_own_name(rf):
    """The control: nothing changes for the shape that always worked."""
    view = form_view_factory(FirstStepForm, template_name="testapp/linear_wizard.html")

    assert _submission(view, {"name": "Ada"}, rf) == {"name": "Ada"}


def test_a_formset_row_expands_its_composite_widgets_too(rf):
    """A row repeats a form, so a composite widget inside one is renamed
    twice — by the row index and by the widget — and both have to happen."""

    class _ShiftsStepView(FormSetStepView):
        form_class = forms.formset_factory(ProjectStartForm, extra=1)
        template_name = "testapp/formset_step.html"

    submission = _submission(
        _ShiftsStepView, [{"start_date": datetime.date(2026, 9, 3)}], rf
    )

    assert submission["form-0-start_date_0"] == 3
    assert submission["form-0-start_date_2"] == 2026


class _DocumentForm(forms.Form):
    title = forms.CharField()
    document = forms.FileField()


class _DocumentStepView(StepFormView):
    form_class = _DocumentForm
    template_name = "testapp/linear_wizard.html"


def test_a_file_contributes_no_keys_to_a_submission(rf):
    """A browser never re-sends a file input, so the POST that produced the
    answer did not carry the upload either — it arrived beside it. An
    answer read back from a file step can be submitted straight back
    precisely because the file is not part of it, and the fields around it
    still are."""
    submission = _submission(
        _DocumentStepView,
        {"title": "Passport", "document": SimpleUploadedFile("p.png", b"bytes")},
        rf,
    )

    assert submission == {"title": "Passport"}
