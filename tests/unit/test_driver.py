"""The agent driver: wizards driven as data rather than as rendered forms.

`form_json_schema` is the vocabulary half — a Django form described as a
JSON Schema object an agent can read. `RunDriver` is the mechanics half,
exercised further down this file.
"""

import json

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

from gandalf.driver import (
    ConfirmationRequired,
    RunDriver,
    RunComplete,
    RunIncomplete,
    fabricate_request,
    field_json_schema,
    form_json_schema,
)
from gandalf.escapes import Advance, Escape, Obliterate, Park
from gandalf.form_views import StepFormView
from gandalf.runtime import StepNotFound
from gandalf.storage import RunNotFound
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard, condition, on_field
from tests.testapp.forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
    ItemCountForm,
    ItemForm,
    PersonalDetailsForm,
    ReviewForm,
    SecondStepForm,
    SummaryDisplayForm,
    SummaryFieldsForm,
    ToppingsForm,
)


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


def test_choice_field_enumerates_values_and_explains_labels():
    schema = field_json_schema(AccountTypeForm().fields["account_type"])

    assert schema["type"] == "string"
    assert schema["enum"] == ["personal", "business"]
    assert schema["description"] == "Choices: personal (Personal), business (Business)."


def test_grouped_choices_flatten_into_one_enum():
    schema = field_json_schema(SummaryDisplayForm().fields["delivery"])

    assert schema["enum"] == ["email", "sms", "post"]


def test_multiple_choice_field_maps_to_an_array_of_choices():
    schema = field_json_schema(ToppingsForm().fields["toppings"])

    assert schema["type"] == "array"
    assert schema["items"] == {"type": "string", "enum": ["cheese", "olives", "basil"]}
    assert schema["description"] == (
        "Choices: cheese (Cheese), olives (Olives), basil (Basil)."
    )


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


def test_help_text_and_choice_legend_share_the_description():
    field = forms.ChoiceField(choices=[("a", "Alpha")], help_text="Pick your tier.")

    schema = field_json_schema(field)

    assert schema["description"] == "Pick your tier. Choices: a (Alpha)."


def test_unsupported_field_falls_back_to_string_with_a_note():
    schema = field_json_schema(forms.FileField(label="Photo"))

    assert schema["type"] == "string"
    assert schema["title"] == "Photo"
    assert "FileField" in schema["description"]
    assert "not supported" in schema["description"]


# --- The driver --------------------------------------------------------------


class _SignupViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second")
    )

    def done(self, bound_wizard):
        return HttpResponse(b"agent done")


def _is_business(request):
    """The customer asked for a business account."""
    account_step = request.wizard.path.find_step(name="account_type")
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

    def done(self, bound_wizard):
        return HttpResponse(b"branch done")


def _build_items(request):
    count_step = request.wizard.path.find_step(name="count")
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

    def done(self, bound_wizard):
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

    def done(self, bound_wizard):
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

        def done(self, bound_wizard):
            return HttpResponse(b"escape done")

    return _EscapingViewSet


def test_fabricate_request_carries_a_session():
    request = fabricate_request()

    assert request.method == "GET"
    request.session["probe"] = True
    assert request.session["probe"] is True


def test_fabricate_request_accepts_a_shared_session_and_user():
    session = {"existing": True}
    user = object()

    request = fabricate_request(user=user, session=session)

    assert request.session is session
    assert request.user is user


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

    def done(self, bound_wizard):
        return HttpResponse(b"booked")


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

    state = driver.bound_wizard.get_state()
    assert json.loads(json.dumps(state)) == state


def test_a_value_no_encoder_can_render_is_refused_where_it_was_passed():
    driver = RunDriver.begin(_BookingViewSet)

    with pytest.raises(TypeError, match="not JSON serializable"):
        driver.submit({**_BOOKING, "note": object()})


# --- Step metadata -----------------------------------------------------


def test_a_placement_carries_metadata_that_can_be_read_back():
    """What the answers alone cannot say: who put this here, and how."""
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    assert driver.metadata() == {"first": {"placed_by": "person"}}


def test_the_driver_marks_its_own_placements_unattended():
    """It knows it is not a person, so it says so without being asked."""
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"})

    assert driver.metadata() == {"first": {"unattended": True}}


def test_metadata_survives_the_steps_that_come_after_it():
    """The property that makes it worth storing. Every later request
    re-proves this answer, and a re-proof must not lose what was recorded
    about the placement it is re-proving."""
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    driver.submit({"email": "ada@example.com"})

    assert driver.metadata()["first"] == {"placed_by": "person"}


def test_re_answering_a_step_replaces_its_metadata():
    """Metadata describes the placement that is there now, not the history
    of the ones that were."""
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    driver.submit({"name": "Grace"}, step="first")

    assert driver.metadata()["first"] == {"unattended": True}


def test_a_step_answered_without_metadata_has_none():
    driver = RunDriver.begin(_SignupViewSet)

    driver.submit({"name": "Ada"}, metadata={})

    assert driver.metadata() == {}


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
    request = fabricate_request()
    driver = RunDriver.begin(_SignupViewSet, request=request, may_finish=True)
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    response = driver.finish()

    assert response.content == b"agent done"
    assert request.session["gandalf_runs"][driver.run_id] == {"completed": True}


def test_agent_driver_finish_before_completion_refuses():
    driver = RunDriver.begin(_SignupViewSet)
    driver.submit({"name": "Ada"})

    with pytest.raises(RunIncomplete):
        driver.finish()


def test_agent_driver_resume_continues_an_existing_run():
    request = fabricate_request()
    started = RunDriver.begin(_SignupViewSet, request=request)
    started.submit({"name": "Ada"})

    resumed = RunDriver.resume(_SignupViewSet, started.run_id, request=request)

    description = resumed.describe()
    assert description.step == "second"
    assert description.answers == {"first": {"name": "Ada"}}


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
    request = fabricate_request()
    driver = RunDriver.begin(_escaping_viewset(_ObliteratingForm), request=request)

    result = driver.submit({"cancel": "on"})

    assert result.status == "escaped"
    assert result.escape == "obliterate"
    assert driver.run_id not in request.session["gandalf_runs"]


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

        def done(self, bound_wizard):
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

        def done(self, bound_wizard):
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


def _company_route(request):
    """Which registration details this company owes."""
    return request.wizard.path.find_step(name="account_type").form.cleaned_data[
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

        def done(self, bound_wizard):
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

        def done(self, bound_wizard):
            return HttpResponse(b"done")

    driver = RunDriver.begin(_DependentViewSet)

    result = driver.check({"second": {"email": "ada@example.com"}})

    assert "second" in result.unchecked
    assert "second" not in result.ok


def test_check_notes_an_escape_without_acting_on_it():
    """A dry run must never park, advance or obliterate a run — it is a
    question, not a submission."""
    request = fabricate_request()
    driver = RunDriver.begin(_escaping_viewset(_ObliteratingForm), request=request)

    result = driver.check({"escaping": {"cancel": "on"}})

    assert "escaping" in result.unchecked
    assert "obliterate" in result.unchecked["escaping"]
    # The run is still there, and still where it was.
    assert driver.run_id in request.session["gandalf_runs"]
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
    request = fabricate_request()

    outline = RunDriver.outline_for(_SignupViewSet, request=request)

    assert [entry["step"] for entry in outline] == ["first", "second"]
    assert set(outline[0]["schema"]["properties"]) == {"name"}
    # No run was created to answer the question.
    assert request.session.get("gandalf_runs", {}) == {}


def test_outlining_a_run_and_outlining_the_wizard_agree():
    driver = RunDriver.begin(_SignupViewSet)

    assert driver.outline() == RunDriver.outline_for(_SignupViewSet)
