"""The agent driver: wizards driven as data rather than as rendered forms.

`form_json_schema` is the vocabulary half — a Django form described as a
JSON Schema object an agent can read. `RunDriver` is the mechanics half,
exercised further down this file.
"""

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.contrib.sessions.backends.cache import SessionStore
from django.http import HttpResponse
from django.test import override_settings

from gandalf.context import WizardContext
from gandalf.driver import (
    ConfirmationRequired,
    RunDriver,
    RunComplete,
    RunIncomplete,
    field_json_schema,
    form_json_schema,
    outline_steps,
)
from gandalf.escapes import Advance, Escape, Obliterate, Park
from gandalf.form_views import StepFormView
from gandalf.runtime import StepNotFound
from gandalf.storage import RunNotFound, SessionStorage
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard, condition, on_field
from tests.testapp.forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
    ItemCountForm,
    ItemForm,
    PersonalDetailsForm,
    ProfilePhotoForm,
    ReviewForm,
    SecondStepForm,
    SummaryDisplayForm,
    SummaryFieldsForm,
    ToppingsForm,
)
from tests.testapp.models import WizardRun


class SignupForm(forms.Form):
    name = forms.CharField()
    email = forms.EmailField()
    nickname = forms.CharField(required=False)


def test_form_schema_is_an_object_of_field_properties():
    schema = form_json_schema(SignupForm())

    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"name", "email", "nickname"}
    assert schema["required"] == ["name", "email"]
    assert schema["additionalProperties"] is False


def test_form_schema_without_required_fields_has_no_required_list():
    class OptionalForm(forms.Form):
        note = forms.CharField(required=False)

    schema = form_json_schema(OptionalForm())

    assert "required" not in schema


def test_char_field_maps_to_string_with_length_bounds():
    field = forms.CharField(max_length=40, min_length=2)

    assert field_json_schema(field) == {
        "type": "string",
        "maxLength": 40,
        "minLength": 2,
    }


def test_char_field_without_bounds_is_a_bare_string():
    assert field_json_schema(forms.CharField()) == {"type": "string"}


def test_a_regex_validator_becomes_the_schema_pattern():
    """Without this the format lives only in the help text, which makes a
    sentence load-bearing: reword it and the field becomes unanswerable
    without the schema having changed at all."""
    field = forms.CharField(
        validators=[RegexValidator(r"^[A-Z]{2}\d{2} \d[A-Z]{2}$")],
        help_text="Enter as AB12 3CD.",
    )

    schema = field_json_schema(field)

    assert schema["pattern"] == r"^[A-Z]{2}\d{2} \d[A-Z]{2}$"


def test_a_format_is_preferred_over_the_pattern_behind_it():
    """`URLField` carries `URLValidator`, a `RegexValidator` whose pattern is
    a kilobyte of alternation. `format` says the same thing, shorter, and in
    the vocabulary a reader already knows."""
    schema = field_json_schema(forms.URLField())

    assert schema == {"type": "string", "format": "uri"}


def test_email_field_carries_the_email_format():
    schema = field_json_schema(forms.EmailField(max_length=100))

    assert schema["type"] == "string"
    assert schema["format"] == "email"
    assert schema["maxLength"] == 100


def test_integer_field_carries_value_bounds():
    schema = field_json_schema(ItemCountForm().fields["count"])

    assert schema == {"type": "integer", "minimum": 1, "maximum": 5}


def test_integer_field_without_bounds_is_a_bare_integer():
    assert field_json_schema(forms.IntegerField()) == {"type": "integer"}


def test_value_validators_bound_a_number_like_the_keywords_do():
    """`min_value=` is sugar for a `MinValueValidator`, so a field given the
    validator directly is bounded exactly as tightly — and was being
    described as though it were not bounded at all."""
    field = forms.IntegerField(validators=[MinValueValidator(5), MaxValueValidator(10)])

    assert field_json_schema(field) == {
        "type": "integer",
        "minimum": 5,
        "maximum": 10,
    }


def test_the_tightest_of_two_bounds_is_the_one_that_holds():
    """Django runs both, so the answer has to satisfy both."""
    field = forms.IntegerField(min_value=1, validators=[MinValueValidator(5)])

    assert field_json_schema(field)["minimum"] == 5


def test_a_bound_that_is_computed_is_left_out():
    """`limit_value` may be a callable, which has no value to state until it
    is called — and calling it here would be evaluating somebody's code to
    describe a form."""
    field = forms.IntegerField(validators=[MinValueValidator(lambda: 5)])

    assert "minimum" not in field_json_schema(field)


def test_fractional_number_fields_map_to_number():
    """`FloatField` and `DecimalField` subclass `IntegerField`, so they have
    to be told apart from it rather than inheriting its schema."""
    assert field_json_schema(forms.FloatField(min_value=0)) == {
        "type": "number",
        "minimum": 0,
    }
    assert field_json_schema(forms.DecimalField(max_value=10)) == {
        "type": "number",
        "maximum": 10,
    }


def test_optional_boolean_field_maps_to_boolean():
    field = SummaryFieldsForm().fields["marketing"]

    assert field_json_schema(field) == {
        "type": "boolean",
        "title": "Marketing emails",
    }


def test_required_boolean_field_must_be_true():
    """A required `BooleanField` is Django's "you must tick this" — the only
    submittable value is true, and the schema says so."""
    schema = field_json_schema(forms.BooleanField())

    assert schema["type"] == "boolean"
    assert schema["const"] is True


def test_null_boolean_field_admits_the_third_answer():
    """`NullBooleanField` subclasses `BooleanField` but its `validate()` is a
    no-op, so it never rejects: True, False and None are all answers, and
    `required` decides nothing. The `const: true` its parent earns would say
    the only submittable value is true, which is the opposite of the truth."""
    schema = field_json_schema(forms.NullBooleanField())

    assert schema == {"type": ["boolean", "null"]}


def test_choice_field_enumerates_values_and_explains_labels():
    schema = field_json_schema(AccountTypeForm().fields["account_type"])

    assert schema["type"] == "string"
    assert schema["enum"] == ["personal", "business"]
    assert schema["x-note"] == "Choices: personal (Personal), business (Business)."


def test_a_required_choice_field_does_not_offer_its_empty_choice():
    """A "Select..." placeholder is a prompt, not an answer — submitting it
    fails validation. Advertising it in the enum invites a caller to send the
    one value the field is certain to reject."""
    field = forms.ChoiceField(choices=[("", "Select..."), ("a", "Alpha")])

    schema = field_json_schema(field)

    assert schema["enum"] == ["a"]
    assert schema["x-note"] == "Choices: a (Alpha)."


def test_an_optional_choice_field_keeps_its_empty_choice():
    """Where the field is optional the empty value really is submittable —
    it is how the person says nothing."""
    field = forms.ChoiceField(
        choices=[("", "Select..."), ("a", "Alpha")], required=False
    )

    assert field_json_schema(field)["enum"] == ["", "a"]


def test_grouped_choices_flatten_into_one_enum():
    schema = field_json_schema(SummaryDisplayForm().fields["delivery"])

    assert schema["enum"] == ["email", "sms", "post"]


def test_multiple_choice_field_maps_to_an_array_of_choices():
    schema = field_json_schema(ToppingsForm().fields["toppings"])

    assert schema["type"] == "array"
    assert schema["items"] == {"type": "string", "enum": ["cheese", "olives", "basil"]}
    assert schema["x-note"] == (
        "Choices: cheese (Cheese), olives (Olives), basil (Basil)."
    )


def test_a_required_multiple_choice_field_wants_at_least_one():
    """`type: array` says a list is allowed, not that anything has to be in
    it. "Choose as many as apply" is a floor, and only the prose said so."""
    field = forms.MultipleChoiceField(choices=[("a", "Alpha"), ("b", "Beta")])

    assert field_json_schema(field)["minItems"] == 1


def test_an_optional_multiple_choice_field_has_no_floor():
    field = forms.MultipleChoiceField(choices=[("a", "Alpha")], required=False)

    assert "minItems" not in field_json_schema(field)


def test_a_model_multiple_choice_field_maps_to_an_array():
    """`ModelMultipleChoiceField` subclasses `ModelChoiceField`, not
    `MultipleChoiceField`, so it slips past the array branch on the way to
    the single-choice one and gets described as a string. It takes a list."""
    field = forms.ModelMultipleChoiceField(queryset=WizardRun.objects.none())

    schema = field_json_schema(field)

    assert schema["type"] == "array"
    assert schema["items"]["type"] == "string"


def test_temporal_fields_carry_their_formats():
    fields = SummaryDisplayForm().fields

    assert field_json_schema(SummaryFieldsForm().fields["starts_on"]) == {
        "type": "string",
        "format": "date",
        "title": "Start date",
    }
    assert field_json_schema(fields["collect_at"]) == {
        "type": "string",
        "format": "date-time",
        "title": "Collect at",
    }
    assert field_json_schema(fields["opens_at"]) == {
        "type": "string",
        "format": "time",
        "title": "Opens at",
    }


def test_label_and_help_text_map_to_title_and_description():
    field = forms.CharField(label="Your name", help_text="As it appears on the card.")

    schema = field_json_schema(field)

    assert schema["title"] == "Your name"
    assert schema["description"] == "As it appears on the card."


def test_the_authors_words_and_the_librarys_stay_apart():
    """`description` is what the wizard's author wrote and nothing else.

    They were joined into one sentence, which left no way to tell a step's
    own guidance from a remark this module generated — and only one of the
    two is ever a candidate for being shown to a person.
    """
    field = forms.ChoiceField(choices=[("a", "Alpha")], help_text="Pick your tier.")

    schema = field_json_schema(field)

    assert schema["description"] == "Pick your tier."
    assert schema["x-note"] == "Choices: a (Alpha)."


def test_a_field_with_no_help_text_has_no_description():
    """An author who said nothing is not quoted as having said something."""
    schema = field_json_schema(forms.ChoiceField(choices=[("a", "Alpha")]))

    assert "description" not in schema
    assert schema["x-note"] == "Choices: a (Alpha)."


def test_unsupported_field_falls_back_to_string_with_a_note():
    schema = field_json_schema(forms.SplitDateTimeField(label="When"))

    assert schema["type"] == "string"
    assert schema["title"] == "When"
    assert "SplitDateTimeField" in schema["x-note"]
    assert "not supported" in schema["x-note"]


def test_a_file_field_is_marked_binary():
    """`format: binary` is how a JSON Schema says "this is a file".

    It matters that this is a field rather than a phrase: anything
    deciding *because* a step takes a file — an agent adapter working out
    whether to offer a way to attach one — should branch on this and not
    on the sentence beside it, which is prose and may be reworded.
    """
    schema = field_json_schema(forms.FileField(label="Photo"))

    assert schema["type"] == "string"
    assert schema["format"] == "binary"
    assert schema["title"] == "Photo"


def test_a_file_field_also_says_in_words_where_the_file_goes():
    """The generic note would be worse than nothing here.

    A file is the one answer that cannot travel in `data` — `submit()`
    raises on it — so "submit its raw form value" points whatever is
    reading this at the single door that refuses it.
    """
    schema = field_json_schema(forms.FileField(label="Photo"))

    assert "uploaded file" in schema["x-note"]
    assert "cannot be sent" in schema["x-note"]
    assert "not supported" not in schema["x-note"]


def test_an_image_field_is_described_as_a_file_too():
    """`ImageField` subclasses `FileField`, and a caller needs the same
    answer for both."""
    schema = field_json_schema(forms.ImageField())

    assert schema["format"] == "binary"
    assert "uploaded file" in schema["x-note"]


def test_a_file_fields_own_help_text_is_not_crowded_out_by_the_note():
    """The note sits beside what the field says about itself rather than
    being joined to it — the help text is where a wizard explains which
    document it wants, and that sentence is the author's."""
    field = forms.FileField(help_text="The front of the card.")

    schema = field_json_schema(field)

    assert schema["description"] == "The front of the card."
    assert "uploaded file" in schema["x-note"]


# --- The driver --------------------------------------------------------------


class _SignupViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second")
    )

    def done(self, run):
        return HttpResponse(b"agent done")


def _is_business(context):
    """The customer asked for a business account."""
    account_step = context.run.path.find_step(name="account_type")
    return account_step.form.cleaned_data["account_type"] == "business"


class _BranchingViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                _is_business,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .step(ReviewForm, name="review")
    )

    def done(self, run):
        return HttpResponse(b"branch done")


def _build_items(context):
    count_step = context.run.path.find_step(name="count")
    steps = Wizard()
    for index in range(int(count_step.form.cleaned_data["count"])):
        steps = steps.step(ItemForm, name=f"item-{index}")
    return steps


class _ExpandViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(_build_items)
        .step(ReviewForm, name="review")
    )

    def done(self, run):
        return HttpResponse(b"expand done")


class _PrefixedNameStepView(StepFormView):
    form_class = FirstStepForm
    template_name = "testapp/linear_wizard.html"

    def get_prefix(self):
        return "acct"


class _PrefixedViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(_PrefixedNameStepView, name="first")
        .step(SecondStepForm, name="second")
    )

    def done(self, run):
        return HttpResponse(b"prefixed done")


class _ParkingForm(forms.Form):
    email = forms.EmailField()

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("email") == "existing@example.com":
            raise Park("/login/")
        return cleaned_data


class _AdvancingForm(forms.Form):
    email = forms.EmailField()
    subscribe = forms.BooleanField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("subscribe"):
            raise Advance("/confirmed/")
        return cleaned_data


class _ObliteratingForm(forms.Form):
    cancel = forms.BooleanField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("cancel"):
            raise Obliterate("/cancelled/")
        return cleaned_data


class _BareEscapeForm(forms.Form):
    name = forms.CharField()

    def clean(self):
        super().clean()
        raise Escape("/nowhere/")


def _escaping_viewset(form_class):
    class _EscapingViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        wizard = (
            Wizard().step(form_class, name="escaping").step(FirstStepForm, name="after")
        )

        def done(self, run):
            return HttpResponse(b"escape done")

    return _EscapingViewSet


def test_a_context_with_no_request_still_has_somewhere_to_keep_a_run():
    context = WizardContext()

    context.session["probe"] = True

    assert context.session["probe"] is True
    # Nothing is pretending to be a browser: a predicate reaching for one
    # finds nothing rather than a plausible fake.
    assert context.request is None


def test_a_context_takes_the_session_and_actor_it_is_given():
    session = {"existing": True}
    user = object()

    context = WizardContext(actor=user, session=session)

    assert context.session is session
    assert context.actor is user


class _RecordingSession(dict):
    """A session that counts the times it was asked to write itself back."""

    modified = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saves = 0

    def save(self):
        self.saves += 1


def test_a_context_with_no_request_writes_the_session_back_itself():
    """Nobody else is going to. `SessionMiddleware` saves a session as a
    response goes past, and the callers that build a context by hand have
    no response — or, for the AG-UI endpoint, one that went out before the
    first tool wrote anything into the run."""
    session = _RecordingSession()
    context = WizardContext(session=session)

    context.session_changed()

    assert session.modified is True
    assert session.saves == 1


def test_a_context_from_a_request_leaves_the_saving_to_the_middleware(rf):
    """The other half, and the reason absence of a request is the signal:
    on the HTTP path the middleware is still to come, and saving per write
    would turn one save per submission into several."""
    request = rf.get("/wizard/")
    request.session = _RecordingSession()
    context = WizardContext.from_request(request)

    context.session_changed()

    assert request.session.modified is True
    assert request.session.saves == 0


def test_a_driven_run_lands_in_the_session_store_it_was_given():
    """End to end through a real Django session backend: a run driven with
    somebody's session is one their next request can find. Before this, the
    answers sat in an unsaved store and went out with the process."""
    session = SessionStore()
    session.create()

    driver = RunDriver.begin(_SignupViewSet, session=session)
    driver.submit({"name": "Ada"})

    reopened = SessionStore(session_key=session.session_key)
    assert driver.run_id in reopened[SessionStorage.SESSION_KEY]


def test_a_driven_context_hands_a_step_view_a_usable_request():
    """The one place a request is still built. It carries the session and
    the actor, because a step's view is entitled to read either."""
    user = object()
    context = WizardContext(actor=user)

    request = context.http_request()

    assert request.session is context.session
    assert request.user is user
    assert request.method == "GET"


def test_a_context_from_a_request_answers_with_the_browsers_user(rf):
    """The HTTP path's half of `actor`. A durable storage scopes runs by it
    either way, so the person browsing and the person an agent is working
    for reach the same answer through the same attribute."""
    request = rf.get("/wizard/")
    request.user = object()

    context = WizardContext.from_request(request)

    assert context.actor is request.user


def test_agent_driver_begins_a_run_and_describes_the_first_step():
    driver = RunDriver.begin(_SignupViewSet)

    description = driver.describe()

    assert driver.run_id
    assert description.step == "first"
    assert set(description.schema["properties"]) == {"name"}
    assert description.answers == {}
    assert description.errors == {}
    assert not description.complete


def test_agent_driver_advances_on_a_valid_submission():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.submit({"name": "Ada"})

    assert result.status == "advanced"
    assert result.next_step == "second"
    assert result.errors == {}
    description = driver.describe()
    assert description.step == "second"
    assert description.answers == {"first": {"name": "Ada"}}


def test_agent_driver_reports_validation_errors_as_data():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})

    result = driver.submit({"email": "not-an-email"})

    assert result.status == "invalid"
    assert result.next_step == "second"
    assert result.errors["email"][0]["code"] == "invalid"
    description = driver.describe()
    assert description.step == "second"
    assert description.errors == result.errors


def test_agent_driver_clears_errors_after_a_valid_submission():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "not-an-email"})

    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    assert driver.describe().errors == {}


def test_agent_driver_completes_the_run():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})

    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    assert result.next_step is None
    description = driver.describe()
    assert description.complete
    assert description.step is None
    assert description.schema is None
    assert description.answers == {
        "first": {"name": "Ada"},
        "second": {"email": "ada@example.com"},
    }


def test_agent_driver_refuses_a_submission_to_a_completed_run():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    with pytest.raises(RunComplete):
        driver.submit({"name": "again"})


class _BookingForm(forms.Form):
    """One of each value `cleaned_data` hands back as an object rather than
    as the string it was posted as."""

    starts_on = forms.DateField()
    collect_at = forms.DateTimeField()
    opens_at = forms.TimeField()
    price = forms.DecimalField()
    reference = forms.UUIDField()
    note = forms.CharField(required=False)


class _BookingViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(_BookingForm, name="booking")

    def done(self, run):
        return HttpResponse(b"booked")


_DATE = date(2025, 10, 12)

_BOOKING = {
    "starts_on": "2025-10-12",
    "collect_at": "2025-10-12 09:30",
    "opens_at": "08:15",
    "price": "12.50",
    "reference": "8ba6b1ea-3ee0-4c2a-9a1a-2c9de6c3f1b1",
    "note": "leave at the door",
}


def test_answers_can_be_submitted_straight_back():
    """The obvious edit: read a step's answers, change one field, submit."""
    driver = RunDriver.begin(_BookingViewSet)
    driver.submit(_BOOKING)
    answers = driver.answers()["booking"]

    result = driver.submit({**answers, "note": "ring the bell"}, step="booking")

    assert result.status == "complete"
    assert driver.answers()["booking"] == {**answers, "note": "ring the bell"}


def test_a_resubmitted_answer_is_stored_as_json():
    """A cleaned value going back in must not leave state that cannot be
    written — the failure would otherwise surface at the session or the
    column, with nothing left to say which answer caused it."""
    driver = RunDriver.begin(_BookingViewSet)
    driver.submit(_BOOKING)

    driver.submit(driver.answers()["booking"], step="booking")

    state = driver.run.get_state()
    assert json.loads(json.dumps(state)) == state


def test_answers_can_be_asked_for_as_json():
    """The same answers, rendered as JSON holds them — for the callers the
    driver mostly has, which speak JSON and cannot hold a `date`."""
    driver = RunDriver.begin(_BookingViewSet)
    driver.submit(_BOOKING)

    answers = driver.answers(json_safe=True)["booking"]

    assert json.loads(json.dumps(answers)) == answers
    assert answers["starts_on"] == "2025-10-12"
    assert answers["price"] == "12.50"


def test_json_safe_answers_are_the_cleaned_ones_not_the_raw_submission():
    """A ticked checkbox is `True`, not the `"on"` a browser posted. The
    stored submission would be the wrong thing to hand anybody: `"on"` is
    an artefact of HTML, and means nothing to a reader of the answers."""

    class _TickForm(forms.Form):
        agreed = forms.BooleanField()
        count = forms.IntegerField()

    class _TickViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        wizard = Wizard().step(_TickForm, name="tick")

        def done(self, run):
            return HttpResponse(b"ticked")

    driver = RunDriver.begin(_TickViewSet)
    driver.submit({"agreed": "on", "count": "12"})

    assert driver.answers(json_safe=True)["tick"] == {"agreed": True, "count": 12}


def test_json_safe_answers_still_feed_back_into_submit():
    driver = RunDriver.begin(_BookingViewSet)
    driver.submit(_BOOKING)

    answers = driver.answers(json_safe=True)["booking"]
    result = driver.submit({**answers, "note": "ring the bell"}, step="booking")

    assert result.status == "complete"
    assert driver.answers()["booking"]["starts_on"] == _DATE


def test_describe_can_carry_json_safe_answers_without_reading_them_twice():
    driver = RunDriver.begin(_BookingViewSet)
    driver.submit(_BOOKING)

    description = driver.describe(json_safe=True)

    assert json.loads(json.dumps(description.answers)) == description.answers


def test_a_value_no_encoder_can_render_is_refused_where_it_was_passed():
    driver = RunDriver.begin(_BookingViewSet)

    with pytest.raises(TypeError, match="not JSON serializable"):
        driver.submit({**_BOOKING, "note": object()})


# --- walking an outline ------------------------------------------------


def test_outline_steps_finds_every_step_a_branch_buries():
    """An outline is a tree, and both sides of a branch are in it.

    A caller asking anything of every step — how many, does one take a
    file, is one called this — should not have to know that arms nest.
    """
    outline = RunDriver.outline_for(_BranchingViewSet)

    names = [entry["step"] for entry in outline_steps(outline)]

    assert names == ["account_type", "business", "personal", "review"]


def test_outline_steps_yields_entries_not_names():
    """The interesting question is usually about the schema beside the
    name, so the entry is what comes back."""
    outline = RunDriver.outline_for(_SignupViewSet)

    first = next(outline_steps(outline))

    assert first["step"] == "first"
    assert "properties" in first["schema"]


def test_outline_steps_finds_every_case_of_a_switch():
    """A switch spells its arms `cases` where a branch spells them `arms`,
    and carries a `default` besides. Both shapes are the caller's problem
    until something walks them."""
    from tests.testapp.views import SwitchEntryWizardViewSet

    outline = RunDriver.outline_for(SwitchEntryWizardViewSet)

    names = [entry["step"] for entry in outline_steps(outline)]

    assert sorted(names) == ["first", "neither", "second"]


def test_outline_steps_yields_nothing_for_an_expansion():
    """The steps an expansion grows do not exist until an answer makes
    them, so describing them before that would be inventing them."""
    outline = RunDriver.outline_for(_ExpandViewSet)

    names = [entry["step"] for entry in outline_steps(outline)]

    assert names == ["count", "review"]


def test_outline_steps_of_a_flat_wizard_is_the_wizard():
    outline = RunDriver.outline_for(_SignupViewSet)

    assert [entry["step"] for entry in outline_steps(outline)] == ["first", "second"]


def test_outline_steps_walks_plain_data():
    """It takes the outline, not the driver that made it — by the time
    most callers see one it has been through a tool call or a log."""
    outline = json.loads(json.dumps(RunDriver.outline_for(_BranchingViewSet)))

    assert len(list(outline_steps(outline))) == 4


# --- Files -------------------------------------------------------------


class _PhotoViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(ProfilePhotoForm, name="photo").step(FirstStepForm, name="first")
    )

    def done(self, run):
        return HttpResponse(b"photo done")


def test_a_driver_places_a_file_as_its_own_answer():
    """The way in, which used to be shut.

    A file goes in `files` rather than in `data` because `data` is stored
    as state and state is JSON. What comes back is an ordinary placement:
    the reference in `files`, and metadata saying the driver put it there,
    so a rule about whose answers may be changed governs an uploaded
    document with no special case for it.
    """
    driver = RunDriver.begin(_PhotoViewSet)

    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            result = driver.submit(
                {}, files={"photo": SimpleUploadedFile("licence.png", b"bytes")}
            )
            placement = driver.placements()["photo"]
            content = driver.open_file(placement.files["photo"]).read()

    assert result.status == "advanced"
    assert placement.files["photo"]["name"] == "licence.png"
    assert content == b"bytes"
    assert placement.metadata == {"unattended": True}


def test_re_answering_a_step_without_files_keeps_the_file_it_has():
    """Omitting `files` says nothing about files rather than clearing them.

    The read-change-write loop reads answers, changes one and submits the
    result — and `answers()` cannot hand a file back, so without this every
    edit of a step would silently drop its upload.
    """
    driver = RunDriver.begin(_PhotoViewSet)

    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            driver.submit(
                {}, files={"photo": SimpleUploadedFile("licence.png", b"bytes")}
            )

            driver.submit({}, step="photo")

            placement = driver.placements()["photo"]

    assert placement.files["photo"]["name"] == "licence.png"


def test_a_file_sent_to_a_step_the_run_cannot_reach_is_not_left_behind():
    """Uploads are saved before the walk can say whether the step exists,
    so a submission that goes nowhere has to take its bytes with it."""
    driver = RunDriver.begin(_PhotoViewSet)

    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            with pytest.raises(StepNotFound):
                driver.submit(
                    {},
                    files={"photo": SimpleUploadedFile("licence.png", b"bytes")},
                    step="no-such-step",
                )

            left_behind = [path for path in Path(tmpdir).rglob("*") if path.is_file()]

    assert left_behind == []


def test_a_driver_opens_a_file_stored_against_the_run():
    """The bytes behind a reference.

    A driver hands its caller the reference because that is what state
    holds and what serialises; this is how the caller gets from the
    reference to what was actually uploaded. The bytes are fetched where
    they are read rather than where the file is opened, so the read
    belongs inside the life of the storage holding them.
    """
    driver = RunDriver.begin(_SignupViewSet)

    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            ref = driver.run.file_storage.save(
                driver.run_id, SimpleUploadedFile("proof.txt", b"hello")
            )

            opened = driver.open_file(ref)

            assert opened.read() == b"hello"
            assert opened.name == "proof.txt"


# --- Step metadata -----------------------------------------------------


def test_a_placement_carries_metadata_that_can_be_read_back():
    """What the answers alone cannot say: who put this here, and how."""
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    assert driver.placements()["first"].metadata == {"placed_by": "person"}


def test_the_driver_reads_and_writes_the_runs_own_metadata():
    """The other metadata, and a different question.

    A placement's says who put *this answer* here. The run's says what the
    run did outside itself — so a driver picking up a run somebody else
    started can see the record that run created, and one starting a run
    sees what `run_started()` put there."""
    driver = RunDriver.begin(_SignupViewSet)

    driver.metadata["reviewed_by"] = "ops"
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    # A placement rewrites the state list whole and does not touch the bag,
    # which is the point of keeping them apart.
    assert dict(driver.metadata) == {"reviewed_by": "ops"}
    assert driver.placements()["first"].metadata == {"placed_by": "person"}


def test_the_driver_marks_its_own_placements_unattended():
    """It knows it is not a person, so it says so without being asked."""
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"})

    assert driver.placements()["first"].metadata == {"unattended": True}


def test_metadata_survives_the_steps_that_come_after_it():
    """The property that makes it worth storing. Every later request
    re-proves this answer, and a re-proof must not lose what was recorded
    about the placement it is re-proving."""
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    driver.submit({"email": "ada@example.com"})

    assert driver.placements()["first"].metadata == {"placed_by": "person"}


def test_metadata_records_a_placement_inside_a_branch_arm():
    """A branch arm is walked by a nested walk, and a placement made in one
    is still a placement. Losing the metadata there would leave it recorded
    for the steps that happen to sit at the top of the tree and nowhere
    else — and most wizards worth the metadata have a branch in them."""
    driver = RunDriver.begin(_BranchingViewSet)
    driver.submit({"account_type": "business"})

    driver.submit({"business_name": "Ada Ltd"}, metadata={"placed_by": "person"})

    assert driver.placements()["business"].metadata == {"placed_by": "person"}


def test_metadata_inside_a_branch_arm_survives_the_steps_after_it():
    """The re-proof property, one level down: a later walk carries the arm's
    stored entry back through the nested walk it came from."""
    driver = RunDriver.begin(_BranchingViewSet)
    driver.submit({"account_type": "business"})
    driver.submit({"business_name": "Ada Ltd"}, metadata={"placed_by": "person"})

    driver.submit({"confirmed": "on"})

    assert driver.placements()["business"].metadata == {"placed_by": "person"}


def test_metadata_records_a_placement_inside_an_expansion():
    """An expansion is walked the same way an arm is, so an answer to a
    grown step records what it claimed about itself too."""
    driver = RunDriver.begin(_ExpandViewSet)
    driver.submit({"count": "1"})

    driver.submit({"name": "Hat"}, metadata={"placed_by": "person"})

    assert driver.placements()["item-0"].metadata == {"placed_by": "person"}


def test_re_answering_a_step_replaces_its_metadata():
    """Metadata describes the placement that is there now, not the history
    of the ones that were."""
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    driver.submit({"name": "Grace"}, step="first")

    assert driver.placements()["first"].metadata == {"unattended": True}


def test_a_step_answered_recording_nothing_is_still_a_placement():
    """The distinction the old two-mapping read could not make.

    A step answered with `metadata={}` has a placement whose metadata is
    empty. A step nobody has answered has no placement at all. Reading
    them apart is what lets a caller say "a person put this here" rather
    than "nothing here claims to be an agent's", which is the same
    sentence about a step that does not exist yet.
    """
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"}, metadata={})

    placements = driver.placements()
    assert placements["first"].metadata == {}
    assert "second" not in placements


def test_a_placement_holds_the_answers_and_the_metadata_together():
    """One read, both halves, and they cannot disagree about the run."""
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    placement = driver.placements()["first"]
    assert placement.answers == {"name": "Ada"}
    assert placement.metadata == {"placed_by": "person"}
    assert placement.files == {}


def test_answers_is_the_placements_with_the_rest_dropped():
    """`answers()` keeps its shape; it is now a view of the same read."""
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})

    assert driver.answers() == {
        name: placement.answers for name, placement in driver.placements().items()
    }


def test_json_safe_renders_a_placements_metadata_too():
    """Metadata is the caller's own mapping, so it need not have been JSON
    before it was stored — and a caller serialising a run cannot hold what
    it cannot render."""
    driver = RunDriver.begin(_BookingViewSet)

    driver.submit(_BOOKING, metadata={"placed_at": date(2026, 8, 16)})

    placement = driver.placements(json_safe=True)["booking"]
    assert placement.metadata == {"placed_at": "2026-08-16"}


def test_a_run_will_not_be_finished_unless_the_driver_was_told_it_may():
    """The default. A driver is by definition not the person filling the
    form in, so `done()` firing from one has to be asked for."""
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    with pytest.raises(ConfirmationRequired):
        driver.finish()


def test_a_caller_can_say_this_driver_may_conclude_a_run():
    driver = RunDriver.begin(_SignupViewSet, may_finish=True)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    assert driver.finish().content == b"agent done"


def test_the_permission_belongs_to_the_driver_not_the_wizard():
    """Two drivers over the same wizard, answering differently — which is
    the point of moving it here. Whether a run may be concluded unattended
    depends on what is holding it, not on what it is."""

    def _filled(**kwargs):
        driver = RunDriver.begin(_SignupViewSet, **kwargs)
        driver.submit({"name": "Ada"})
        driver.submit({"email": "ada@example.com"})
        return driver

    assert _filled(may_finish=True).finish().content == b"agent done"
    with pytest.raises(ConfirmationRequired):
        _filled().finish()


def test_a_subclass_can_carry_the_permission():
    """For a caller that is always allowed — an import command, say — so
    every construction does not have to remember."""

    class _Concluding(RunDriver):
        may_finish = True

    driver = _Concluding.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    assert driver.finish().content == b"agent done"


def test_an_unfinished_run_is_refused_before_permission_is_considered():
    """The more useful complaint wins: a run still at a step is refused for
    being unfinished, whether or not anything was allowed to finish it."""
    driver = RunDriver.begin(_SignupViewSet, may_finish=True)
    driver.submit({"name": "Ada"})

    with pytest.raises(RunIncomplete):
        driver.finish()


def test_agent_driver_finish_fires_done_and_retires_the_run():
    context = WizardContext()
    driver = RunDriver.begin(_SignupViewSet, context=context, may_finish=True)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    response = driver.finish()

    assert response.content == b"agent done"
    assert context.session["gandalf_runs"][driver.run_id] == {"completed": True}


def test_agent_driver_finish_before_completion_refuses():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})

    with pytest.raises(RunIncomplete):
        driver.finish()


def test_agent_driver_resume_continues_an_existing_run():
    context = WizardContext()
    started = RunDriver.begin(_SignupViewSet, context=context)
    started.submit({"name": "Ada"})

    resumed = RunDriver.resume(_SignupViewSet, started.run_id, context=context)

    description = resumed.describe()
    assert description.step == "second"
    assert description.answers == {"first": {"name": "Ada"}}


def test_the_driver_re_cursors_when_a_dynamic_wizard_changes_shape():
    """The answer that decides the tree is placed against a tree that does
    not contain the steps it grows, so the cursor the walk ended on cannot
    be the answer. A dynamic `get_wizard()` builds a fresh declaration each
    call, which is what tells the driver to resolve again and take its
    cursor from the new tree; a static wizard hands back the very same
    declaration and is spared the second walk.
    """

    class _DynamicViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"

        def get_wizard(self, run):
            state = run.get_state()
            wizard = Wizard().step(ItemCountForm, name="count")
            if state:
                for index in range(int(state[0]["step"]["count"])):
                    wizard = wizard.step(ItemForm, name=f"item-{index}")
            return wizard

    driver = RunDriver.begin(_DynamicViewSet)

    result = driver.submit({"count": "2"})

    assert result.status == "advanced"
    assert result.next_step == "item-0"


def test_agent_driver_resume_of_an_unknown_run_raises():
    with pytest.raises(RunNotFound):
        RunDriver.resume(_SignupViewSet, "no-such-run")


def test_agent_driver_follows_a_branch():
    driver = RunDriver.begin(_BranchingViewSet)

    result = driver.submit({"account_type": "personal"})

    assert result.next_step == "personal"
    driver.submit({"preferred_name": "Ada"})
    assert driver.describe().step == "review"


def test_agent_driver_reroutes_when_an_earlier_answer_flips_a_branch():
    driver = RunDriver.begin(_BranchingViewSet)
    driver.submit({"account_type": "personal"})
    driver.submit({"preferred_name": "Ada"})

    result = driver.submit({"account_type": "business"}, step="account_type")

    assert result.status == "advanced"
    assert result.next_step == "business"
    assert driver.describe().step == "business"


def test_agent_driver_edit_of_an_unreachable_step_raises():
    driver = RunDriver.begin(_SignupViewSet)

    with pytest.raises(StepNotFound):
        driver.submit({"name": "Ada"}, step="nonexistent")

    assert driver.describe().step == "first"


def test_agent_driver_walks_an_expanding_wizard():
    driver = RunDriver.begin(_ExpandViewSet)

    result = driver.submit({"count": "2"})

    assert result.next_step == "item-0"
    driver.submit({"name": "Hat"})
    assert driver.describe().step == "item-1"
    driver.submit({"name": "Scarf"})
    assert driver.describe().step == "review"


def test_agent_driver_edits_a_step_the_declaration_does_not_hold():
    """A step grown by `.expand()` is not in the declaration tree, so the
    prefix lookup finds nothing — the submission still lands there."""
    driver = RunDriver.begin(_ExpandViewSet)
    driver.submit({"count": "2"})
    driver.submit({"name": "Hat"})

    result = driver.submit({"name": "Bonnet"}, step="item-0")

    assert result.status == "advanced"
    assert driver.describe().answers["item-0"] == {"name": "Bonnet"}


def test_agent_driver_maps_bare_keys_through_the_steps_form_prefix():
    driver = RunDriver.begin(_PrefixedViewSet)

    result = driver.submit({"name": "Ada"})

    assert result.status == "advanced"
    assert driver.describe().answers == {"first": {"name": "Ada"}}


def test_agent_driver_reports_a_parking_escape_and_keeps_the_run_where_it_was():
    driver = RunDriver.begin(_escaping_viewset(_ParkingForm))

    result = driver.submit({"email": "existing@example.com"})

    assert result.status == "escaped"
    assert result.escape == "park"
    description = driver.describe()
    assert description.step == "escaping"
    assert description.answers == {}


def test_agent_driver_persists_an_advancing_escape():
    driver = RunDriver.begin(_escaping_viewset(_AdvancingForm))

    result = driver.submit({"email": "ada@example.com", "subscribe": "on"})

    assert result.status == "escaped"
    assert result.escape == "advance"
    assert driver.describe().step == "after"


def test_agent_driver_obliterates_when_a_step_says_so():
    context = WizardContext()
    driver = RunDriver.begin(_escaping_viewset(_ObliteratingForm), context=context)

    result = driver.submit({"cancel": "on"})

    assert result.status == "escaped"
    assert result.escape == "obliterate"
    assert driver.run_id not in context.session["gandalf_runs"]


def test_agent_driver_rejects_a_bare_escape():
    driver = RunDriver.begin(_escaping_viewset(_BareEscapeForm))

    with pytest.raises(ImproperlyConfigured):
        driver.submit({"name": "Ada"})


# --- The outline -------------------------------------------------------------


def test_outline_describes_a_linear_wizard_upfront():
    driver = RunDriver.begin(_SignupViewSet)

    outline = driver.outline()

    assert [entry["kind"] for entry in outline] == ["step", "step"]
    assert [entry["step"] for entry in outline] == ["first", "second"]
    assert set(outline[0]["schema"]["properties"]) == {"name"}
    assert set(outline[1]["schema"]["properties"]) == {"email"}


def test_outline_shows_every_branch_arm():
    driver = RunDriver.begin(_BranchingViewSet)

    outline = driver.outline()

    assert [entry["kind"] for entry in outline] == ["step", "branch", "step"]
    branch = outline[1]
    [business_arm] = branch["arms"]
    assert [entry["step"] for entry in business_arm["steps"]] == ["business"]
    assert [entry["step"] for entry in branch["default"]] == ["personal"]


def test_outline_explains_an_arm_with_its_predicates_own_words():
    """Which arm runs is arbitrary Python, so it cannot be derived — but
    the predicate names and documents itself, and that is the author's
    description of the choice."""
    driver = RunDriver.begin(_BranchingViewSet)

    [arm] = driver.outline()[1]["arms"]

    assert arm["when"] == "_is_business"
    assert arm["description"] == "The customer asked for a business account."


def test_outline_copes_with_a_predicate_that_says_nothing():
    """A lambda has no useful name and no docstring; the arm is still
    reported, just without an explanation."""

    class _TerseViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        wizard = (
            Wizard()
            .step(AccountTypeForm, name="account_type")
            .branch(
                condition(
                    lambda request: True,
                    Wizard().step(BusinessDetailsForm, name="business"),
                ),
                default=Wizard().step(PersonalDetailsForm, name="personal"),
            )
        )

        def done(self, run):
            return HttpResponse(b"done")

    driver = RunDriver.begin(_TerseViewSet)

    [arm] = driver.outline()[1]["arms"]

    assert arm["when"] == "<lambda>"
    assert arm["description"] is None
    assert [entry["step"] for entry in arm["steps"]] == ["business"]


def test_outline_marks_an_expansion_it_cannot_know_yet():
    driver = RunDriver.begin(_ExpandViewSet)

    outline = driver.outline()

    assert [entry["kind"] for entry in outline] == ["step", "expand", "step"]


def test_outline_degrades_to_no_schema_for_a_view_it_cannot_compose_yet():
    """A hand-written FormView may build its form from earlier answers; for
    a step the run has not reached, that composition can fail — the outline
    reports the step without a schema rather than refusing the whole tree."""

    class _DependentStepView(StepFormView):
        form_class = SecondStepForm
        template_name = "testapp/linear_wizard.html"

        def get_initial(self):
            initial = super().get_initial()
            first = self.request.wizard.path.find_step(name="first")
            initial["email"] = first.form.cleaned_data["name"] + "@example.com"
            return initial

    class _DependentViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        wizard = (
            Wizard()
            .step(FirstStepForm, name="first")
            .step(_DependentStepView, name="second")
        )

        def done(self, run):
            return HttpResponse(b"done")

    driver = RunDriver.begin(_DependentViewSet)

    outline = driver.outline()

    assert outline[0]["schema"] is not None
    assert outline[1] == {"kind": "step", "step": "second", "schema": None}


# --- Prefill -----------------------------------------------------------------


def test_prefill_fills_everything_it_was_handed():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.prefill(
        {
            "first": {"name": "Ada"},
            "second": {"email": "ada@example.com"},
        }
    )

    assert result.placed == ["first", "second"]
    assert result.complete
    assert result.next_step is None
    assert result.errors == {}
    assert result.unused == []


def test_prefill_stops_at_the_first_step_it_has_no_answer_for():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.prefill({"second": {"email": "ada@example.com"}})

    assert result.placed == []
    assert result.next_step == "first"
    assert result.unused == ["second"]
    assert not result.complete


def test_prefill_reports_a_rejected_answer_and_stops():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.prefill(
        {
            "first": {"name": "Ada"},
            "second": {"email": "not-an-email"},
        }
    )

    assert result.placed == ["first"]
    assert result.errors["second"]["email"][0]["code"] == "invalid"
    assert result.next_step == "second"
    assert not result.complete


def test_prefill_crosses_a_branch_as_its_answers_open_it():
    driver = RunDriver.begin(_BranchingViewSet)

    result = driver.prefill(
        {
            "account_type": {"account_type": "business"},
            "business": {"business_name": "Ada Ltd"},
            "review": {"confirmed": "on"},
            "personal": {"preferred_name": "never taken"},
        }
    )

    assert result.placed == ["account_type", "business", "review"]
    assert result.complete
    assert result.unused == ["personal"]


def test_prefill_materialises_an_expansion_and_keeps_filling():
    driver = RunDriver.begin(_ExpandViewSet)

    result = driver.prefill(
        {
            "count": {"count": "2"},
            "item-0": {"name": "Hat"},
            "item-1": {"name": "Scarf"},
            "review": {"confirmed": "on"},
        }
    )

    assert result.placed == ["count", "item-0", "item-1", "review"]
    assert result.complete


def test_prefill_reports_an_escape_and_stops():
    driver = RunDriver.begin(_escaping_viewset(_ParkingForm))

    result = driver.prefill(
        {
            "escaping": {"email": "existing@example.com"},
            "after": {"name": "Ada"},
        }
    )

    assert result.escape == "park"
    assert result.placed == []
    assert result.next_step == "escaping"
    assert result.unused == ["after"]


def test_prefill_on_a_complete_run_places_nothing():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    result = driver.prefill({"first": {"name": "again"}})

    assert result.placed == []
    assert result.complete
    assert result.unused == ["first"]


# --- Outlining a switch ------------------------------------------------------


def _company_route(context):
    """Which registration details this company owes."""
    return context.run.path.find_step(name="account_type").form.cleaned_data[
        "account_type"
    ]


def _switch_viewset(selector):
    class _SwitchViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        wizard = (
            Wizard()
            .step(AccountTypeForm, name="account_type")
            .switch(
                selector,
                {
                    "business": Wizard().step(BusinessDetailsForm, name="business"),
                    "personal": Wizard().step(PersonalDetailsForm, name="personal"),
                },
                default=Wizard().step(ReviewForm, name="other"),
            )
        )

        def done(self, run):
            return HttpResponse(b"done")

    return _SwitchViewSet


def test_outline_names_a_switchs_possible_outcomes():
    """Even when the selector is a black box, the outcomes are declared —
    so a caller knows what the answers could be."""
    driver = RunDriver.begin(_switch_viewset(_company_route))

    entry = driver.outline()[1]

    assert entry["kind"] == "switch"
    assert entry["decided_by"] == "_company_route"
    assert entry["description"] == "Which registration details this company owes."
    assert [case["case"] for case in entry["cases"]] == ["business", "personal"]
    assert [step["step"] for step in entry["cases"][0]["steps"]] == ["business"]
    assert [step["step"] for step in entry["default"]] == ["other"]
    assert "source" not in entry


def test_outline_reports_the_answer_an_on_field_switch_reads():
    """The declarative case: the dependency is data, not prose, so the
    route can be worked out rather than guessed."""
    driver = RunDriver.begin(_switch_viewset(on_field("account_type", "account_type")))

    entry = driver.outline()[1]

    assert entry["source"] == {"step": "account_type", "field": "account_type"}
    assert entry["decided_by"] == "account_type.account_type"
    assert entry["description"] is None


# --- check(): what a bag of answers would do, without doing it --------------


def test_check_passes_answers_that_validate():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.check(
        {"first": {"name": "Ada"}, "second": {"email": "ada@example.com"}}
    )

    assert result.ok == ["first", "second"]
    assert result.invalid == {}
    assert result.missing == []


def test_check_reports_every_bad_answer_at_once():
    """The point of checking rather than placing: one message to the person
    instead of one per failure."""
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.check({"first": {"name": ""}, "second": {"email": "not-an-email"}})

    assert set(result.invalid) == {"first", "second"}
    assert result.invalid["first"]["name"][0]["code"] == "required"
    assert result.invalid["second"]["email"][0]["code"] == "invalid"


def test_check_writes_nothing():
    driver = RunDriver.begin(_SignupViewSet)

    driver.check({"first": {"name": "Ada"}})

    description = driver.describe()
    assert description.step == "first"
    assert description.answers == {}


def test_check_lists_the_steps_it_has_no_answer_for():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.check({"first": {"name": "Ada"}})

    assert result.missing == ["second"]


def test_check_does_not_demand_answers_for_steps_behind_a_branch():
    """Both arms cannot apply, so asking for both would be asking for
    something the person will never be shown."""
    driver = RunDriver.begin(_BranchingViewSet)

    result = driver.check({})

    assert result.missing == ["account_type", "review"]


def test_check_still_validates_a_conditional_answer_it_was_given():
    driver = RunDriver.begin(_BranchingViewSet)

    result = driver.check({"business": {"business_name": ""}})

    assert "business" in result.invalid


def test_check_ignores_steps_the_run_has_already_answered():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})

    result = driver.check({})

    assert result.missing == ["second"]


def test_check_reports_an_answer_naming_no_declared_step():
    driver = RunDriver.begin(_SignupViewSet)

    result = driver.check({"nonexistent": {"x": "1"}})

    assert result.unknown == ["nonexistent"]


def test_check_cannot_judge_a_step_whose_form_needs_missing_answers():
    """A hand-written view may compose its form from earlier answers; until
    those exist there is nothing to bind, and saying so is better than
    guessing."""

    class _DependentStepView(StepFormView):
        form_class = SecondStepForm
        template_name = "testapp/linear_wizard.html"

        def get_initial(self):
            initial = super().get_initial()
            first = self.request.wizard.path.find_step(name="first")
            initial["email"] = first.form.cleaned_data["name"] + "@example.com"
            return initial

    class _DependentViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        wizard = (
            Wizard()
            .step(FirstStepForm, name="first")
            .step(_DependentStepView, name="second")
        )

        def done(self, run):
            return HttpResponse(b"done")

    driver = RunDriver.begin(_DependentViewSet)

    result = driver.check({"second": {"email": "ada@example.com"}})

    assert "second" in result.unchecked
    assert "second" not in result.ok


def test_check_notes_an_escape_without_acting_on_it():
    """A dry run must never park, advance or obliterate a run — it is a
    question, not a submission."""
    context = WizardContext()
    driver = RunDriver.begin(_escaping_viewset(_ObliteratingForm), context=context)

    result = driver.check({"escaping": {"cancel": "on"}})

    assert "escaping" in result.unchecked
    assert "obliterate" in result.unchecked["escaping"]
    # The run is still there, and still where it was.
    assert driver.run_id in context.session["gandalf_runs"]
    assert driver.describe().step == "escaping"


def test_check_cannot_see_steps_an_expansion_has_not_grown():
    """An expansion's steps do not exist until the answer that shapes them
    does, so answers for them have no declared step to bind to yet."""
    driver = RunDriver.begin(_ExpandViewSet)

    result = driver.check({"count": {"count": "2"}, "item-0": {"name": "Hat"}})

    assert result.ok == ["count"]
    assert result.unknown == ["item-0"]
    assert result.missing == ["review"]


def test_a_wizard_can_be_outlined_without_starting_a_run():
    """The constraint this removes: asking what a journey looks like is a
    question about the wizard, and used to require minting a run to ask
    it. Nothing is left behind by asking."""
    context = WizardContext()

    outline = RunDriver.outline_for(_SignupViewSet, context=context)

    assert [entry["step"] for entry in outline] == ["first", "second"]
    assert set(outline[0]["schema"]["properties"]) == {"name"}
    # No run was created to answer the question.
    assert context.session.get("gandalf_runs", {}) == {}


def test_outlining_a_run_and_outlining_the_wizard_agree():
    driver = RunDriver.begin(_SignupViewSet)

    assert driver.outline() == RunDriver.outline_for(_SignupViewSet)


def test_a_context_and_url_kwargs_reach_the_same_view():
    """Naming a url kwarg beside a context used to lose it.

    A whole context was taken as it stood, so `begin(ViewSet, item=x,
    context=…)` set the view up with no `item` at all — and a wizard
    mounted under a segment fails on that with a complaint about not being
    mounted, from a call that named the segment plainly. Both are the
    caller saying something, so both are honoured.
    """
    context = WizardContext(actor="ada")

    driver = RunDriver.begin(_SignupViewSet, context=context, item="v1")

    assert driver.view.kwargs == {"item": "v1"}
    # And it is the context the view was set up from, so the run is still
    # scoped to whoever the context named.
    assert driver.run.context.actor == "ada"


def test_url_kwargs_named_at_the_call_win_over_the_contexts_own():
    """The call is the more specific statement — a context is held for a
    conversation and a kwarg names one thing inside it."""
    context = WizardContext(url_kwargs={"item": "held", "shared": "kept"})

    driver = RunDriver.begin(_SignupViewSet, context=context, item="named")

    assert driver.view.kwargs == {"item": "named", "shared": "kept"}


def test_a_contexts_own_url_kwargs_survive_a_call_that_names_none():
    context = WizardContext(url_kwargs={"item": "held"})

    driver = RunDriver.begin(_SignupViewSet, context=context)

    assert driver.view.kwargs == {"item": "held"}


def test_addressing_a_url_keeps_the_session_the_context_was_using():
    """The twin must not invent its own store, or the run it starts is one
    the original context cannot find."""
    context = WizardContext()
    context.session["planted"] = True

    driver = RunDriver.begin(_SignupViewSet, context=context, item="v1")

    assert driver.run.context.session is context.session
