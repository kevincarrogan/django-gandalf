"""The rows a summary step puts in its context, and how each answer in
one is turned into display text."""

import datetime
from decimal import Decimal

import pytest
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile

from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.summary import SummaryMixin, format_value
from gandalf.wizard import Wizard
from tests.testapp.forms import (
    FirstStepForm,
    SummaryFieldsForm,
)


def _bound_field(form, name):
    form.is_valid()
    return form[name]


@pytest.fixture
def preferences():
    return SummaryFieldsForm(
        data={
            "contact_method": "post",
            "toppings": ["cheese", "basil"],
            "marketing": "on",
            "starts_on": "2025-10-12",
            "note": "",
        }
    )


def test_choice_value_renders_its_label(preferences):
    bound_field = _bound_field(preferences, "contact_method")

    assert format_value(bound_field, "post") == "Post"


def test_choice_value_outside_the_choices_renders_itself(preferences):
    """A stored answer whose choice has since been withdrawn still shows."""
    bound_field = _bound_field(preferences, "contact_method")

    assert format_value(bound_field, "carrier-pigeon") == "carrier-pigeon"


def test_grouped_choice_value_renders_its_label():
    form = forms.Form()
    form.fields["method"] = forms.ChoiceField(
        choices=[
            ("Digital", [("email", "Email"), ("sms", "SMS")]),
            ("Physical", [("post", "Post")]),
        ],
    )

    assert format_value(form["method"], "sms") == "SMS"


def test_multiple_choice_value_renders_joined_labels(preferences):
    bound_field = _bound_field(preferences, "toppings")

    assert format_value(bound_field, ["cheese", "basil"]) == "Cheese, Basil"


def test_true_renders_as_yes(preferences):
    bound_field = _bound_field(preferences, "marketing")

    assert format_value(bound_field, True) == "Yes"


def test_false_renders_as_no(preferences):
    bound_field = _bound_field(preferences, "marketing")

    assert format_value(bound_field, False) == "No"


def test_date_renders_in_the_active_date_format(preferences):
    bound_field = _bound_field(preferences, "starts_on")

    assert format_value(bound_field, datetime.date(2025, 10, 12)) == "Oct. 12, 2025"


def test_datetime_renders_in_the_active_datetime_format():
    form = forms.Form()
    form.fields["seen_at"] = forms.DateTimeField()

    formatted = format_value(form["seen_at"], datetime.datetime(2025, 10, 12, 9, 30))

    assert formatted == "Oct. 12, 2025, 9:30 a.m."


def test_time_renders_in_the_active_time_format():
    form = forms.Form()
    form.fields["opens_at"] = forms.TimeField()

    assert format_value(form["opens_at"], datetime.time(9, 30)) == "9:30 a.m."


def test_uploaded_file_renders_its_name():
    form = forms.Form()
    form.fields["photo"] = forms.FileField()
    upload = SimpleUploadedFile("passport.png", b"bytes")

    assert format_value(form["photo"], upload) == "passport.png"


def test_unanswered_optional_field_renders_as_empty_text(preferences):
    bound_field = _bound_field(preferences, "note")

    assert format_value(bound_field, "") == ""
    assert format_value(bound_field, None) == ""


def test_empty_multiple_choice_renders_as_empty_text(preferences):
    bound_field = _bound_field(preferences, "toppings")

    assert format_value(bound_field, []) == ""


def test_other_values_render_as_their_string(preferences):
    bound_field = _bound_field(preferences, "note")

    assert format_value(bound_field, Decimal("12.50")) == "12.50"
    assert format_value(bound_field, 3) == "3"


class _StubUrls:
    def get_step_url(self, run_id, step_segment):
        return f"/wizard/{run_id}/{step_segment}/"


class _StubView:
    """Stands in for the `FormView` the mixin is normally mixed into."""

    def __init__(self, request):
        self.request = request

    def get_context_data(self, **kwargs):
        return dict(kwargs)


class _SummaryView(SummaryMixin, _StubView):
    pass


class _Session(dict):
    modified = False


@pytest.fixture
def summary_view(rf):
    """A summary view over a two-step run with both answers stored."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(SummaryFieldsForm, name="preferences")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = rf.get("/wizard/")
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {
                            "step": {
                                "contact_method": "email",
                                "toppings": ["olives"],
                                "marketing": "",
                                "starts_on": "2025-10-12",
                                "note": "",
                            }
                        },
                    ],
                },
            },
        }
    )
    bound_wizard = BoundWizard(request, SessionStorage(request), wizard=wizard)
    bound_wizard.retrieve("existing-run")
    bound_wizard.urls = _StubUrls()
    request.wizard = bound_wizard
    return _SummaryView(request)


def test_context_carries_a_row_per_answered_step(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert [row.name for row in rows] == ["who", "preferences"]


def test_a_row_is_labelled_by_its_step_context(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].label == "Who you are"


def test_a_row_without_a_declared_label_falls_back_to_its_step_name(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[1].label == "Preferences"


def test_a_row_links_to_the_step_that_changes_it(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].url == "/wizard/existing-run/who/"


def test_a_row_renders_each_of_its_answers(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert [(field.name, field.value) for field in rows[1].fields] == [
        ("contact_method", "Email"),
        ("toppings", "Olives"),
        ("marketing", "No"),
        ("starts_on", "Oct. 12, 2025"),
        ("note", ""),
    ]


def test_a_field_carries_the_bound_field_it_came_from(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].fields[0].bound_field is rows[0].form["name"]


def test_a_row_builds_its_form_once(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].form is rows[0].step.form


def test_fields_can_be_left_off_a_row(rf, summary_view):
    class _NoteFreeView(_SummaryView):
        def include_summary_field(self, step, bound_field):
            return bound_field.name != "note"

    view = _NoteFreeView(summary_view.request)

    rows = view.get_context_data()["summary"]

    assert "note" not in [field.name for field in rows[1].fields]


def test_values_can_be_formatted_per_field(summary_view):
    class _ShoutingView(_SummaryView):
        def format_value(self, bound_field, value):
            return super().format_value(bound_field, value).upper()

    view = _ShoutingView(summary_view.request)

    rows = view.get_context_data()["summary"]

    assert rows[1].fields[0].value == "EMAIL"


def test_the_steps_summarised_can_be_narrowed(summary_view):
    class _LastStepOnlyView(_SummaryView):
        def get_summary_steps(self):
            return super().get_summary_steps()[-1:]

    view = _LastStepOnlyView(summary_view.request)

    rows = view.get_context_data()["summary"]

    assert [row.name for row in rows] == ["preferences"]


def test_the_context_name_is_configurable(summary_view):
    class _AnswersView(_SummaryView):
        summary_context_name = "answers"

    view = _AnswersView(summary_view.request)

    assert "answers" in view.get_context_data()
