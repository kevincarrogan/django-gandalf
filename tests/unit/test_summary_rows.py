"""The rows a summary step puts in its context, and how each answer is
turned into display text."""

import datetime
from decimal import Decimal

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import TemplateDoesNotExist
from django.utils.safestring import SafeString

from gandalf.context import WizardContext
from gandalf.runtime import Run
from gandalf.storage import SessionStorage
from gandalf.form_views import StepFormView
from gandalf.summary import (
    Answer,
    Hide,
    Question,
    SummaryMixin,
    SummaryRow,
    format_value,
)
from gandalf.wizard import Wizard, condition
from tests.testapp.forms import (
    AccountTypeForm,
    AddressForm,
    BusinessDetailsForm,
    FirstStepForm,
    GeocodedAddressForm,
    SummaryRowsForm,
)
from tests.testapp.views import (
    FirstStepFromFormView,
    OpeningHoursStepView,
    SelfShapingAddressStepView,
)


def _bound_field(form, name):
    form.is_valid()
    return form[name]


@pytest.fixture
def preferences():
    return SummaryRowsForm(
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
        .step(SummaryRowsForm, name="preferences")
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
    run = Run(context, SessionStorage(context), wizard=wizard)
    run.retrieve("existing-run")
    run.urls = _StubUrls()
    # The view reads its own request, exactly as a dispatch hands it one.
    request.run = run
    return _SummaryView(request)


def test_context_carries_a_row_per_answer(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert [row.step.name for row in rows] == ["who"] + ["preferences"] * 5


def test_a_row_is_named_by_the_field_that_asked_it(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].label == "Name"


def test_a_row_links_to_the_step_that_changes_it(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].url == "/wizard/existing-run/who/"


def test_every_answer_reads_as_a_row_of_its_own(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert [(row.name, row.value) for row in rows[1:]] == [
        ("contact_method", "Email"),
        ("toppings", "Olives"),
        ("marketing", "No"),
        ("starts_on", "Oct. 12, 2025"),
        ("note", ""),
    ]


def test_a_row_carries_the_bound_field_it_came_from(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].bound_field is rows[0].step.form["name"]


def test_a_step_builds_its_form_once(summary_view):
    rows = summary_view.get_context_data()["summary"]

    assert rows[0].form is rows[0].step.form


def test_fields_can_be_left_off_the_page(summary_view):
    class _NoteFreeView(_SummaryView):
        def include_summary_field(self, step, bound_field):
            return bound_field.name != "note"

    view = _NoteFreeView(summary_view.request)

    rows = view.get_context_data()["summary"]

    assert "note" not in [row.name for row in rows]


def test_values_can_be_formatted_per_field(summary_view):
    class _ShoutingView(_SummaryView):
        def format_value(self, bound_field, value):
            return super().format_value(bound_field, value).upper()

    view = _ShoutingView(summary_view.request)

    rows = view.get_context_data()["summary"]

    assert rows[1].value == "EMAIL"


def test_the_steps_summarised_can_be_narrowed(summary_view):
    class _LastStepOnlyView(_SummaryView):
        def get_summary_steps(self):
            return super().get_summary_steps()[-1:]

    view = _LastStepOnlyView(summary_view.request)

    rows = view.get_context_data()["summary"]

    assert {row.step.name for row in rows} == {"preferences"}


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
        run = Run(context, SessionStorage(context), wizard=wizard)
        run.retrieve("existing-run")
        run.urls = _StubUrls()
        request.run = run
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


class _JoinedView(_SummaryView):
    summary_overrides = {
        "address": [Answer("line_1", "line_2", "town", "postcode")],
    }


def test_named_fields_read_as_one_row(address_rows):
    rows = address_rows(_JoinedView)

    assert rows[1].value == "12 High Street, Ely, CB7 4AA"


def test_an_answer_drops_the_pieces_that_were_left_empty(address_rows):
    """`line_2` is blank, and an address does not want ", , " for it."""
    rows = address_rows(_JoinedView)

    assert ", ," not in rows[1].value


def test_an_answer_that_nothing_named_takes_the_steps_own_name(address_rows):
    """A page that asked one thing has already named it, so an answer with
    no `Question` around it reads as the step."""
    rows = address_rows(_JoinedView)

    assert rows[1].label == "Address"


def test_a_step_with_no_label_names_its_row_after_itself(summary_view):
    """`capfirst` on the step's name, which is the fallback the summary has
    always had — now reached only by a row no field named."""

    class _View(_SummaryView):
        summary_overrides = {"preferences": [Answer()]}

    rows = _View(summary_view.request).get_context_data()["summary"]

    assert rows[1].label == "Preferences"


def test_an_answer_takes_the_place_of_its_first_field(address_rows):
    """The rows read in form order, with the joined answer where its first
    member was — not appended after the fields it did not swallow."""
    rows = address_rows(_JoinedView)

    assert [row.name for row in rows] == ["name", "line_1", "lookup_token"]


def test_fields_no_answer_names_keep_a_row_of_their_own(address_rows):
    rows = address_rows(_JoinedView)

    assert (rows[2].label, rows[2].value) == ("Lookup token", "tok-9")


def test_an_answer_keeps_the_pieces_it_joined(address_rows):
    """`parts` is what a value template renders as lines rather than a
    run-on."""
    rows = address_rows(_JoinedView)

    assert rows[1].parts == ("12 High Street", "Ely", "CB7 4AA")


def test_a_plain_field_keeps_its_own_text_as_its_only_part(address_rows):
    rows = address_rows(_JoinedView)

    assert rows[2].parts == ("tok-9",)


def test_an_unanswered_plain_field_keeps_no_parts(address_rows):
    class _View(_SummaryView):
        summary_overrides = {"address": [Answer("town", "postcode")]}

    rows = address_rows(_View)

    assert rows[2].parts == ()


def test_an_answer_joins_with_the_separator_it_was_given(address_rows):
    class _View(_SummaryView):
        summary_overrides = {
            "address": [Answer("town", "postcode", separator=" — ")],
        }

    rows = address_rows(_View)

    assert rows[3].value == "Ely — CB7 4AA"


def test_an_answer_carries_no_bound_field(address_rows):
    """One `BoundField` cannot stand for several answers, so the escape
    hatch is empty rather than misleading."""
    rows = address_rows(_JoinedView)

    assert rows[1].bound_field is None


def test_hidden_fields_get_no_row(address_rows):
    class _View(_SummaryView):
        summary_overrides = {"address": [Hide("lookup_token")]}

    rows = address_rows(_View)

    assert "lookup_token" not in [row.name for row in rows]


def test_an_answer_renders_its_pieces_through_the_pages_formatting(address_rows):
    """`format_value` stays the one place a value is turned into text, so a
    page that overrides it shapes what an answer joins."""

    class _View(_JoinedView):
        def format_value(self, bound_field, value):
            return super().format_value(bound_field, value).upper()

    rows = address_rows(_View)

    assert rows[1].value == "12 HIGH STREET, ELY, CB7 4AA"


def test_an_answer_skips_a_field_the_page_leaves_off(address_rows):
    class _View(_JoinedView):
        def include_summary_field(self, step, bound_field):
            return bound_field.name != "town"

    rows = address_rows(_View)

    assert rows[1].value == "12 High Street, CB7 4AA"


def test_an_answer_skips_a_field_the_step_does_not_ask(summary_view_for, address_state):
    """A dynamic `get_form_class()` need not offer every field an answer
    names. The declaration cannot say what such a step asks, so the names
    are taken on trust and the row survives asking for less."""

    class _Dynamic(StepFormView):
        template_name = "testapp/linear_wizard.html"

        def get_form_class(self):
            return AddressForm

    class _View(_SummaryView):
        summary_overrides = {"address": [Answer("town", "county", "postcode")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(_Dynamic, name="address", label="Address")
        .configure(template_name="testapp/linear_wizard.html")
    )

    rows = summary_view_for(wizard, address_state, _View).get_context_data()["summary"]

    assert rows[3].value == "Ely, CB7 4AA"


def test_an_answer_naming_fields_a_declared_step_has_not_got_is_refused(
    summary_view_for, address_state
):
    """Where the declaration knows what a step asks, a field it does not
    have is a typo, and a row built on one could never speak for it."""

    class _View(_SummaryView):
        summary_overrides = {"who": [Answer("line_1", "town")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(AddressForm, name="address", label="Address")
        .configure(template_name="testapp/linear_wizard.html")
    )

    with pytest.raises(ImproperlyConfigured, match="line_1, town"):
        summary_view_for(wizard, address_state, _View).get_context_data()


def test_a_formset_step_elsewhere_does_not_stop_the_check(
    summary_view_for, address_state
):
    """A formset declares no fields at step level, so it is taken on trust
    — rather than stopping the page shaping every other step."""

    class _View(_SummaryView):
        summary_overrides = {"address": [Answer("town", "postcode")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(AddressForm, name="address", label="Address")
        .step(OpeningHoursStepView, name="opening-hours")
        .configure(template_name="testapp/linear_wizard.html")
    )

    rows = summary_view_for(wizard, address_state, _View).get_context_data()["summary"]

    assert rows[3].value == "Ely, CB7 4AA"


HOURS = {
    "form-TOTAL_FORMS": "2",
    "form-INITIAL_FORMS": "0",
    "form-MIN_NUM_FORMS": "0",
    "form-MAX_NUM_FORMS": "7",
    "form-0-day": "Monday",
    "form-0-opens": "09:00",
    "form-1-day": "Tuesday",
    "form-1-opens": "10:00",
}


def test_a_formset_step_summarises_every_row(summary_view_for):
    """A check-your-answers page exists so the answers can be checked, so a
    step holding several rows shows all of them rather than none. Plain
    rather than pretty — the page can say more with `build_summary_rows()`,
    and what three organisers should read like is its decision — but an
    answer nobody can see on the page is the one thing this must not do."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(OpeningHoursStepView, name="opening-hours", label="Opening hours")
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, [{"step": {"name": "Ada"}}, {"step": HOURS}])
    rows = view.get_context_data()["summary"]

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Day", "Monday"),
        ("Opens", "09:00"),
        ("Day", "Tuesday"),
        ("Opens", "10:00"),
    ]


def test_a_step_with_a_plain_form_view_is_iterated_directly(summary_view_for):
    """A step declared with a bare Django `FormView` carries no
    `get_answer_fields`, so it has no say and the page iterates its form —
    which is right, because a `BaseForm` yields its own bound fields."""
    wizard = (
        Wizard()
        .step(FirstStepFromFormView, name="who", label="Who you are")
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, [{"step": {"name": "Ada"}}])
    rows = view.get_context_data()["summary"]

    assert [(row.label, row.value) for row in rows] == [("Name", "Ada")]


def test_a_page_can_say_how_a_formset_step_reads(summary_view_for):
    """The reference's worked override: the library shows every row plainly,
    and the page says what they mean. `step.answer` is the rows."""

    class _View(_SummaryView):
        def build_summary_rows(self, step):
            if step.name != "opening-hours":
                yield from super().build_summary_rows(step)
                return
            for row in step.answer:
                yield SummaryRow(step=step, label=row["day"], value=row["opens"])

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(OpeningHoursStepView, name="opening-hours", label="Opening hours")
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, [{"step": {"name": "Ada"}}, {"step": HOURS}], _View)
    rows = view.get_context_data()["summary"]

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Monday", "09:00"),
        ("Tuesday", "10:00"),
    ]


def test_specs_can_be_chosen_per_run(address_rows):
    class _View(_SummaryView):
        def get_row_specs(self, step):
            if step.name == "address":
                return [Answer("town", "postcode")]
            return super().get_row_specs(step)

    rows = address_rows(_View)

    assert rows[3].value == "Ely, CB7 4AA"


def test_a_key_that_names_no_step_is_refused(address_rows):
    """A renamed step would otherwise go back to one row per field, in
    production, silently."""

    class _View(_SummaryView):
        summary_overrides = {"postal_address": [Answer("town", "postcode")]}

    with pytest.raises(ImproperlyConfigured) as error:
        address_rows(_View)

    assert "postal_address" in str(error.value)


def test_a_key_naming_a_step_on_a_dormant_arm_is_kept(summary_view_for):
    """The check is against what the wizard declares, not what this run
    walked — the arm not taken is still a step the page may shape."""

    class _View(_SummaryView):
        summary_overrides = {"address": [Answer("town", "postcode")]}

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

    assert [row.step.name for row in rows] == ["account_type", "business_name"]


def test_names_are_not_checked_when_the_wizard_grows_mid_walk(summary_view_for):
    """An expansion's steps do not exist until the walk reaches them, so
    the declaration is not the whole set of names to check against."""

    class _View(_SummaryView):
        summary_overrides = {"address": [Answer("town", "postcode")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who")
        .expand(lambda context: Wizard().step(AddressForm, name="address"))
        .configure(template_name="testapp/linear_wizard.html")
    )
    state = [{"step": {"name": "Ada"}}, {"expand": [{"step": ADDRESS}]}]

    rows = summary_view_for(wizard, state, _View).get_context_data()["summary"]

    assert rows[3].value == "Ely, CB7 4AA"


def test_a_field_named_by_two_specs_is_refused(address_rows):
    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Answer("line_1", "town"),
                Answer("town", "postcode"),
            ],
        }

    with pytest.raises(ImproperlyConfigured) as error:
        address_rows(_View)

    assert "town" in str(error.value)


class ColourField(forms.Field):
    """A field whose cleaned value is not a string, and knows how to read."""

    def format_value(self, value):
        return value["hex"].upper()


def test_a_field_that_says_how_it_reads_is_believed():
    """Without this the page falls to `str(value)` and a person checking
    their answers is shown a Python repr."""
    form = forms.Form()
    form.fields["colour"] = ColourField(label="Colour")

    assert format_value(form["colour"], {"hex": "#ffffff"}) == "#FFFFFF"


def test_an_unanswered_field_is_still_empty_however_it_reads():
    """The empty guard is the page's rule, not the field's: an answer
    nobody gave is blank rather than whatever a formatter makes of None."""
    form = forms.Form()
    form.fields["colour"] = ColourField(label="Colour")

    assert format_value(form["colour"], None) == ""


class _TemplatedView(_SummaryView):
    summary_overrides = {
        "address": [
            Answer(
                "line_1",
                "line_2",
                "town",
                "postcode",
                template_name="testapp/summary/address.html",
            ),
            Hide("lookup_token"),
        ],
    }


def test_an_answer_renders_through_the_template_it_names(address_rows):
    """The shaping of an address belongs to the address, not to an
    `{% if %}` in the review template."""
    rows = address_rows(_TemplatedView)

    assert "<li>12 High Street</li>" in rows[1].value
    assert "<li>Ely</li>" in rows[1].value


def test_a_rendered_value_arrives_marked_safe(address_rows):
    """A page prints `{{ row.value }}` without knowing which kind of row it
    is holding, so the markup has to survive the print."""
    rows = address_rows(_TemplatedView)

    assert isinstance(rows[1].value, SafeString)


def test_a_value_nothing_rendered_is_escaped_like_any_other_string(address_rows):
    rows = address_rows(_JoinedView)

    assert not isinstance(rows[1].value, SafeString)


def test_a_value_template_is_given_the_row_it_renders(summary_view_for, address_state):
    """Through it the form: `cleaned_data` is where a value the form derived
    in `clean()` lives, and no field list can name one of those."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(GeocodedAddressForm, name="address", label="Address")
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, address_state, _TemplatedView)
    rows = view.get_context_data()["summary"]

    assert "Outcode: CB7" in rows[1].value


def test_a_value_template_sees_the_name_the_page_will_show(
    summary_view_for, address_wizard, address_state
):
    """The label goes down into the spec rather than being applied after, so
    a template rendering the row is not shown a name that is about to
    change."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Question(
                    "Where the work happens",
                    Answer(
                        "line_1", "town", template_name="testapp/summary/label.html"
                    ),
                ),
                Hide("line_2", "postcode", "lookup_token"),
            ],
        }

    view = summary_view_for(address_wizard, address_state, _View)
    rows = view.get_context_data()["summary"]

    assert "Where the work happens" in rows[1].value


def test_a_template_that_does_not_exist_fails_when_the_page_is_built(address_rows):
    """Rendered while the rows are built rather than lazily in the markup,
    so a name that resolves to nothing says so with a traceback."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [Answer("town", template_name="testapp/summary/nope.html")],
        }

    with pytest.raises(TemplateDoesNotExist):
        address_rows(_View)


def test_an_answer_carries_the_form_its_pieces_came_from(address_rows):
    """A joined answer has no `BoundField` to reach the form through, so it
    carries the form itself — which is where a derived answer lives."""
    rows = address_rows(_JoinedView)

    assert rows[1].form.cleaned_data["town"] == "Ely"


def test_a_plain_field_carries_its_own_form(address_rows):
    rows = address_rows(_SummaryView)

    assert rows[0].form.cleaned_data["name"] == "Ada"


class _WholeStepView(_SummaryView):
    summary_overrides = {
        "address": [
            Answer(template_name="testapp/summary/address.html"),
            Hide("lookup_token"),
        ],
    }


def test_an_answer_naming_no_fields_takes_the_whole_step(address_rows):
    rows = address_rows(_WholeStepView)

    assert [row.step.name for row in rows] == ["who", "address"]
    assert "<li>12 High Street</li>" in rows[1].value


def test_an_answer_naming_no_fields_is_named_by_its_step(address_rows):
    rows = address_rows(_WholeStepView)

    assert rows[1].label == "Address"


def test_it_still_carries_the_librarys_formatting(address_rows):
    """Rendering from `cleaned_data` gives up `format_value`, so the row
    carries the formatted answers too — a template chooses."""
    rows = address_rows(_WholeStepView)

    assert rows[1].parts == ("12 High Street", "Ely", "CB7 4AA")


def test_it_leaves_out_what_a_hide_names(address_rows):
    rows = address_rows(_WholeStepView)

    assert "tok" not in " ".join(rows[1].parts)


def test_it_consults_include_summary_field(address_rows):
    class _View(_WholeStepView):
        def include_summary_field(self, step, bound_field):
            return bound_field.name != "town"

    rows = address_rows(_View)

    assert rows[1].parts == ("12 High Street", "CB7 4AA")


def test_it_names_itself_after_the_first_answer_it_shows(address_rows):
    rows = address_rows(_WholeStepView)

    assert rows[1].name == "line_1"


def test_an_answer_beside_one_naming_no_fields_takes_its_own_fields(address_rows):
    """Not a conflict but a sentence that parses: these two on one row, the
    rest on another."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Answer(template_name="testapp/summary/address.html"),
                Question("Where", Answer("town", "postcode")),
            ],
        }

    rows = address_rows(_View)

    assert [row.label for row in rows] == ["Name", "Address", "Where"]
    assert rows[1].parts == ("12 High Street", "tok-9")
    assert rows[2].value == "Ely, CB7 4AA"


def test_two_specs_naming_no_fields_are_refused(address_rows):
    """What is left over cannot go to both."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Answer(template_name="testapp/summary/address.html"),
                Answer(template_name="testapp/summary/hours.html"),
            ],
        }

    with pytest.raises(ImproperlyConfigured) as excinfo:
        address_rows(_View)

    assert "names no fields" in str(excinfo.value)


def test_a_spec_left_with_nothing_still_speaks(address_rows):
    """Its template is the point, not the values it was handed."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Answer(template_name="testapp/summary/address.html"),
                Answer("line_1", "line_2", "town", "postcode", "lookup_token"),
            ],
        }

    rows = address_rows(_View)

    assert rows[-1].parts == ()
    assert rows[-1].name == "address"


def test_an_answer_naming_no_fields_and_no_template_joins_the_rest(address_rows):
    """The same rule read the other way round: the rest of this step, on one
    row."""

    class _View(_SummaryView):
        summary_overrides = {"address": [Answer(), Hide("lookup_token")]}

    rows = address_rows(_View)

    assert [(row.label, row.value) for row in rows] == [
        ("Name", "Ada"),
        ("Address", "12 High Street, Ely, CB7 4AA"),
    ]


class _Repeat:
    """A spec of nobody's but the page's: each row of a repeated step as its
    own row, which no spec Gandalf ships can do."""

    def __init__(self, label_field, value_field):
        self.label_field = label_field
        self.value_field = value_field

    @property
    def fields(self):
        return ()

    def build_rows(self, view, step, form, label=None):
        for row in step.answer:
            yield SummaryRow(
                step=step,
                label=row[self.label_field],
                value=row[self.value_field],
                form=form,
            )


def test_a_page_can_bring_a_spec_of_its_own(summary_view_for):
    """The protocol is the whole contract: name your fields, build your
    rows. This one names none and builds several."""

    class _View(_SummaryView):
        summary_overrides = {"opening-hours": [_Repeat("day", "opens")]}

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(OpeningHoursStepView, name="opening-hours", label="Opening hours")
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, [{"step": {"name": "Ada"}}, {"step": HOURS}], _View)
    rows = view.get_context_data()["summary"]

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Monday", "09:00"),
        ("Tuesday", "10:00"),
    ]


@pytest.fixture
def self_shaping_rows(summary_view_for, address_state):
    """The rows for a wizard whose address step shapes itself."""

    def build(view_class):
        wizard = (
            Wizard()
            .step(FirstStepForm, name="who", label="Who you are")
            .step(SelfShapingAddressStepView, name="address", label="Address")
            .configure(template_name="testapp/linear_wizard.html")
        )
        view = summary_view_for(wizard, address_state, view_class)
        return view.get_context_data()["summary"]

    return build


def test_a_step_can_say_how_its_own_answers_read(self_shaping_rows):
    """The review page names no steps at all, and the address still reads as
    an address."""
    rows = self_shaping_rows(_SummaryView)

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Address", "12 High Street, Ely, CB7 4AA"),
    ]


def test_the_page_has_the_last_word(self_shaping_rows):
    """A review page that disagrees with the step wins for that step."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [Question("Where", Answer("town", "postcode"))],
        }

    rows = self_shaping_rows(_View)

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Address line 1", "12 High Street"),
        ("Address line 2", ""),
        ("Where", "Ely, CB7 4AA"),
        ("Lookup token", "tok-9"),
    ]


def test_a_page_can_silence_a_step_that_shapes_itself(self_shaping_rows):
    """An empty sequence is an opinion; only a missing key defers."""

    class _View(_SummaryView):
        summary_overrides = {"address": []}

    rows = self_shaping_rows(_View)

    assert [row.label for row in rows[1:]] == [
        "Address line 1",
        "Address line 2",
        "Town or city",
        "Postcode",
        "Lookup token",
    ]


def test_a_step_shaping_a_field_it_has_not_got_is_refused(
    summary_view_for, address_state
):
    """The same check the page's own specs get: a misspelt `Hide` on a step
    hides nothing, and renders the answer it was meant to keep off."""

    class _TypoStepView(SelfShapingAddressStepView):
        summary_rows = [Hide("lookup_taken")]

    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(_TypoStepView, name="address", label="Address")
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, address_state, _SummaryView)

    with pytest.raises(ImproperlyConfigured) as excinfo:
        view.get_context_data()

    assert "lookup_taken" in str(excinfo.value)
    assert "own summary_rows" in str(excinfo.value)


def test_a_step_view_declaring_a_field_twice_is_refused_at_import():
    """The class body is where it is said, so the class body is where it
    fails: no run, no request and no summary page needed to know."""
    with pytest.raises(ImproperlyConfigured, match="more than once"):

        class _View(StepFormView):
            form_class = AddressForm
            template_name = "testapp/linear_wizard.html"
            summary_rows = [Answer("town"), Hide("town")]


def test_a_step_view_naming_no_fields_twice_is_refused_at_import():
    with pytest.raises(ImproperlyConfigured, match="names no fields"):

        class _View(StepFormView):
            form_class = AddressForm
            template_name = "testapp/linear_wizard.html"
            summary_rows = [
                Answer(template_name="testapp/summary/address.html"),
                Answer(template_name="testapp/summary/hours.html"),
            ]


def test_a_step_view_saying_nothing_is_not_checked():
    """The guard the whole thing rests on: every step view in a project runs
    this, `FormSetStepView` included, which is defined while `gandalf.summary`
    is still importing `gandalf.form_views`."""

    class _View(StepFormView):
        form_class = AddressForm
        template_name = "testapp/linear_wizard.html"

    assert _View().get_summary_row_specs() == ()


def test_specs_decided_per_run_are_still_checked_when_the_page_builds(
    address_rows,
):
    """Import time cannot see a list `get_row_specs()` invents per run, so
    the build checks too."""

    class _View(_SummaryView):
        def get_row_specs(self, step):
            if step.name == "address":
                return [Answer("town"), Hide("town")]
            return super().get_row_specs(step)

    with pytest.raises(ImproperlyConfigured, match="more than once"):
        address_rows(_View)


def test_a_bare_form_step_can_say_it_at_the_declaration(
    summary_view_for, address_state
):
    """A step with no view of its own says it where it is declared, beside
    the name and the label it already says there."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(
            AddressForm,
            name="address",
            label="Address",
            summary_rows=[
                Answer("line_1", "line_2", "town", "postcode"),
                Hide("lookup_token"),
            ],
        )
        .configure(template_name="testapp/linear_wizard.html")
    )

    view = summary_view_for(wizard, address_state, _SummaryView)
    rows = view.get_context_data()["summary"]

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Address", "12 High Street, Ely, CB7 4AA"),
    ]


def test_a_declaration_that_contradicts_itself_is_refused_where_it_is_written():
    """Checked at `.step()`, the way a step view's list is checked when its
    class body runs."""
    with pytest.raises(ImproperlyConfigured, match="more than once"):
        Wizard().step(
            AddressForm,
            name="address",
            summary_rows=[Answer("town"), Hide("town")],
        )


def test_a_step_saying_it_twice_is_refused():
    """The view says it and the declaration says it: two answers to one
    question."""
    with pytest.raises(ImproperlyConfigured, match="in one place"):
        Wizard().step(
            SelfShapingAddressStepView,
            name="address",
            summary_rows=[Answer("town", "postcode")],
        )


def test_a_form_still_carrying_the_attribute_is_refused():
    """A form is shared with everything else that asks it, so a summary
    page's shaping on one is a silence rather than a declaration."""

    class _LeftoverForm(AddressForm):
        summary_rows = [Answer("town", "postcode")]

    with pytest.raises(ImproperlyConfigured, match="which nothing reads"):
        Wizard().step(_LeftoverForm, name="address")


class _QuestionedView(_SummaryView):
    summary_overrides = {
        "address": [
            Question("Address", Answer("line_1", "line_2", "town")),
            Question("Postcode", Answer("postcode")),
            Hide("lookup_token"),
        ],
    }


def test_a_step_that_asked_twice_reads_as_two_rows(address_rows):
    rows = address_rows(_QuestionedView)

    assert [(row.label, row.value) for row in rows] == [
        ("Name", "Ada"),
        ("Address", "12 High Street, Ely"),
        ("Postcode", "CB7 4AA"),
    ]


def test_both_rows_change_the_step_that_asked_them(address_rows):
    """One page asked both, so both send the user back to it."""
    rows = address_rows(_QuestionedView)

    assert rows[1].url == rows[2].url
    assert rows[1].step.name == rows[2].step.name == "address"


def test_a_question_names_a_row_that_names_no_fields(address_rows):
    """The shape a `Render` could not take: a row whose value comes from a
    template and whose name comes from the page that asked it."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Question(
                    "Where the work happens",
                    Answer(template_name="testapp/summary/address.html"),
                ),
            ],
        }

    rows = address_rows(_View)

    assert rows[1].label == "Where the work happens"
    assert "<li>12 High Street</li>" in rows[1].value


def test_an_answer_beside_a_question_keeps_its_steps_name(address_rows):
    """Not a refusal: one row named by the page that asked it, one named by
    the step, and both are rows."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [
                Question("Where", Answer("line_1", "town")),
                Answer("postcode", "lookup_token"),
                Hide("line_2"),
            ],
        }

    rows = address_rows(_View)

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Where", "12 High Street, Ely"),
        ("Address", "CB7 4AA, tok-9"),
    ]


def test_a_field_no_question_names_keeps_a_row_of_its_own(address_rows):
    """Nothing to refuse and nothing to vanish: a field added to the form
    appears on the page whatever else the step says about itself."""

    class _View(_SummaryView):
        summary_overrides = {
            "address": [Question("Address", Answer("line_1", "line_2", "town"))],
        }

    rows = address_rows(_View)

    assert [(row.label, row.value) for row in rows[1:]] == [
        ("Address", "12 High Street, Ely"),
        ("Postcode", "CB7 4AA"),
        ("Lookup token", "tok-9"),
    ]


def test_a_question_inside_a_question_is_refused():
    with pytest.raises(ImproperlyConfigured, match="inside a Question"):
        Wizard().step(
            AddressForm,
            name="address",
            summary_rows=[
                Question("Address", Question("Postcode", Answer("postcode")))
            ],
        )


def test_a_hide_inside_a_question_is_refused():
    """A row named and then not shown."""
    with pytest.raises(ImproperlyConfigured, match="Hide inside a Question"):
        Wizard().step(
            AddressForm,
            name="address",
            summary_rows=[Question("Address", Hide("postcode"))],
        )
