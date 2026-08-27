"""The rows a summary step puts in its context, and how each answer in
one is turned into display text."""

import datetime
from decimal import Decimal

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile

from gandalf.context import WizardContext
from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.summary import Group, Hide, SummaryMixin, format_value
from gandalf.wizard import Wizard, condition
from tests.testapp.forms import (
    AccountTypeForm,
    AddressForm,
    BusinessDetailsForm,
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
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context), wizard=wizard)
    bound_wizard.retrieve("existing-run")
    bound_wizard.urls = _StubUrls()
    # The view reads its own request, exactly as a dispatch hands it one.
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


def _is_business_account(context):
    step = context.run.path.find_step(name="account_type")
    return step.form.cleaned_data["account_type"] == "business"


ADDRESS = {
    "line_1": "12 High Street",
    "line_2": "",
    "town": "Ely",
    "postcode": "CB7 4AA",
    "lookup_token": "tok-9",
}


@pytest.fixture
def summary_view_for(rf):
    """A summary view over any wizard, with `state` already stored."""

    def build(wizard, state, view_class=_SummaryView):
        request = rf.get("/wizard/")
        request.session = _Session(
            {"gandalf_runs": {"existing-run": {"state": state}}},
        )
        context = WizardContext.from_request(request)
        bound_wizard = BoundWizard(context, SessionStorage(context), wizard=wizard)
        bound_wizard.retrieve("existing-run")
        bound_wizard.urls = _StubUrls()
        request.wizard = bound_wizard
        return view_class(request)

    return build


@pytest.fixture
def address_wizard():
    return (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(AddressForm, name="address", label="Address")
        .configure(template_name="testapp/linear_wizard.html")
    )


@pytest.fixture
def address_state():
    return [{"step": {"name": "Ada"}}, {"step": ADDRESS}]


@pytest.fixture
def address_rows(summary_view_for, address_wizard, address_state):
    """The rows a summary page shows for `view_class`'s address run."""

    def build(view_class):
        view = summary_view_for(address_wizard, address_state, view_class)
        return view.get_context_data()["summary"]

    return build


class _GroupedView(_SummaryView):
    summary_fields = {
        "address": [
            Group("line_1", "line_2", "town", "postcode", label="Address"),
        ],
    }


def test_grouped_fields_read_as_one_answer(address_rows):
    rows = address_rows(_GroupedView)

    assert rows[1].fields[0].value == "12 High Street, Ely, CB7 4AA"


def test_a_group_drops_the_answers_that_were_left_empty(address_rows):
    """`line_2` is blank, and an address does not want ", , " for it."""
    rows = address_rows(_GroupedView)

    assert ", ," not in rows[1].fields[0].value


def test_a_group_carries_the_label_it_was_given(address_rows):
    rows = address_rows(_GroupedView)

    assert rows[1].fields[0].label == "Address"


def test_a_group_takes_the_place_of_its_first_field(address_rows):
    """The row reads in form order, with the group where its first member
    was — not appended after the fields it did not swallow."""
    rows = address_rows(_GroupedView)

    assert [field.name for field in rows[1].fields] == ["line_1", "lookup_token"]


def test_fields_no_group_names_keep_their_own_line(address_rows):
    rows = address_rows(_GroupedView)

    assert rows[1].fields[1].value == "tok-9"


def test_a_group_keeps_the_pieces_it_joined(address_rows):
    """`parts` is what a template renders as lines rather than a run-on."""
    rows = address_rows(_GroupedView)

    assert rows[1].fields[0].parts == ("12 High Street", "Ely", "CB7 4AA")


def test_a_plain_field_keeps_its_own_text_as_its_only_part(address_rows):
    rows = address_rows(_GroupedView)

    assert rows[1].fields[1].parts == ("tok-9",)


def test_an_unanswered_plain_field_keeps_no_parts(address_rows):
    class _View(_SummaryView):
        summary_fields = {"address": [Group("town", "postcode")]}

    rows = address_rows(_View)

    assert rows[1].fields[1].parts == ()


def test_a_group_can_carry_no_label_of_its_own(address_rows):
    """A step whose every field is grouped is already labelled by its row,
    so the group repeating it would say the same thing twice."""

    class _View(_SummaryView):
        summary_fields = {
            "address": [
                Group("line_1", "line_2", "town", "postcode"),
                Hide("lookup_token"),
            ],
        }

    rows = address_rows(_View)

    assert rows[1].label == "Address"
    assert rows[1].fields[0].label is None


def test_a_group_joins_with_the_separator_it_was_given(address_rows):
    class _View(_SummaryView):
        summary_fields = {
            "address": [Group("town", "postcode", separator=" — ")],
        }

    rows = address_rows(_View)

    assert rows[1].fields[2].value == "Ely — CB7 4AA"


def test_a_group_carries_no_bound_field(address_rows):
    """One `BoundField` cannot stand for several answers, so the escape
    hatch is empty rather than misleading."""
    rows = address_rows(_GroupedView)

    assert rows[1].fields[0].bound_field is None


def test_hidden_fields_are_left_off_the_row(address_rows):
    class _View(_SummaryView):
        summary_fields = {"address": [Hide("lookup_token")]}

    rows = address_rows(_View)

    assert "lookup_token" not in [field.name for field in rows[1].fields]


def test_a_group_renders_its_pieces_through_the_pages_formatting(address_rows):
    """`format_value` stays the one place a value is turned into text, so a
    page that overrides it shapes what a group joins."""

    class _View(_GroupedView):
        def format_value(self, bound_field, value):
            return super().format_value(bound_field, value).upper()

    rows = address_rows(_View)

    assert rows[1].fields[0].value == "12 HIGH STREET, ELY, CB7 4AA"


def test_a_group_skips_a_field_the_page_leaves_off(address_rows):
    class _View(_GroupedView):
        def include_summary_field(self, step, bound_field):
            return bound_field.name != "town"

    rows = address_rows(_View)

    assert rows[1].fields[0].value == "12 High Street, CB7 4AA"


def test_a_group_skips_a_field_the_step_does_not_ask(address_rows):
    """A dynamic `get_form_class()` need not offer every field a group
    names, so a group has to survive asking for less."""

    class _View(_SummaryView):
        summary_fields = {"address": [Group("town", "county", "postcode")]}

    rows = address_rows(_View)

    assert rows[1].fields[2].value == "Ely, CB7 4AA"


def test_a_group_naming_nothing_the_step_asks_leaves_the_row_alone(
    summary_view_for, address_state
):
    """A group is reached through its own fields, so one that names none of
    a step's fields never speaks for it."""

    class _View(_SummaryView):
        summary_fields = {"who": [Group("line_1", "town")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(AddressForm, name="address", label="Address")
        .configure(template_name="testapp/linear_wizard.html")
    )

    rows = summary_view_for(wizard, address_state, _View).get_context_data()["summary"]

    assert [field.name for field in rows[0].fields] == ["name"]


def test_specs_can_be_chosen_per_run(address_rows):
    class _View(_SummaryView):
        def get_field_specs(self, step):
            if step.name == "address":
                return [Group("town", "postcode")]
            return super().get_field_specs(step)

    rows = address_rows(_View)

    assert rows[1].fields[2].value == "Ely, CB7 4AA"


def test_a_key_that_names_no_step_is_refused(address_rows):
    """A renamed step would otherwise go back to one line per field, in
    production, silently."""

    class _View(_SummaryView):
        summary_fields = {"postal_address": [Group("town", "postcode")]}

    with pytest.raises(ImproperlyConfigured) as error:
        address_rows(_View)

    assert "postal_address" in str(error.value)


def test_a_key_naming_a_step_on_a_dormant_arm_is_kept(summary_view_for):
    """The check is against what the wizard declares, not what this run
    walked — the arm not taken is still a step the page may shape."""

    class _View(_SummaryView):
        summary_fields = {"address": [Group("town", "postcode")]}

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type", label="Account type")
        .branch(
            condition(
                _is_business_account,
                Wizard().step(AddressForm, name="address"),
            ),
            default=Wizard().step(BusinessDetailsForm, name="business_name"),
        )
        .configure(template_name="testapp/linear_wizard.html")
    )
    state = [
        {"step": {"account_type": "personal"}},
        {"branch": {"default": [{"step": {"business_name": "Acme Ltd"}}]}},
    ]

    rows = summary_view_for(wizard, state, _View).get_context_data()["summary"]

    assert [row.name for row in rows] == ["account_type", "business_name"]


def test_names_are_not_checked_when_the_wizard_grows_mid_walk(summary_view_for):
    """An expansion's steps do not exist until the walk reaches them, so
    the declaration is not the whole set of names to check against."""

    class _View(_SummaryView):
        summary_fields = {"address": [Group("town", "postcode")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who")
        .expand(lambda context: Wizard().step(AddressForm, name="address"))
        .configure(template_name="testapp/linear_wizard.html")
    )
    state = [{"step": {"name": "Ada"}}, {"expand": [{"step": ADDRESS}]}]

    rows = summary_view_for(wizard, state, _View).get_context_data()["summary"]

    assert rows[1].fields[2].value == "Ely, CB7 4AA"


def test_a_field_named_by_two_specs_is_refused(address_rows):
    class _View(_SummaryView):
        summary_fields = {
            "address": [
                Group("line_1", "town"),
                Group("town", "postcode"),
            ],
        }

    with pytest.raises(ImproperlyConfigured) as error:
        address_rows(_View)

    assert "town" in str(error.value)
