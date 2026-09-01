"""A check-your-answers step built with `SummaryMixin`, over HTTP.

The rows a summary page needs — every answered step, in route order, with
its answers as display text and the URL that changes them — and the
guarantee that each step's form is reconstructed once per request however
many times the page reads it.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertRedirects,
    assertTemplateUsed,
)

from gandalf.summary import Group, Hide, Question, Render
from gandalf.wizard import Wizard
from tests.testapp.forms import AddressForm
from tests.testapp import views
from tests.testapp.counting import counting_walks


PREFERENCES = {
    "contact_method": "post",
    "toppings": ["cheese", "basil"],
    "marketing": "on",
    "starts_on": "2025-10-12",
    "note": "Leave with a neighbour",
}


@pytest.fixture
def business_run(wizard_driver):
    """A run through the business arm, parked on the summary step."""
    run = wizard_driver("summary-wizard").start()
    run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme Ltd"}),
            ("preferences", PREFERENCES),
        ]
    )
    return run


def test_summary_lists_every_answered_step_in_route_order(business_run):
    response = business_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary_wizard.html")
    rows = response.context["summary"]
    assert [row.name for row in rows] == [
        "account_type",
        "business_name",
        "preferences",
    ]
    assertContains(response, "<dt>Account type</dt>", html=True)


def test_summary_labels_fall_back_to_the_step_name(wizard_driver):
    run = wizard_driver("summary-wizard").start()
    run.post_steps(
        [
            ("account_type", {"account_type": "personal"}),
            ("preferred_name", {"preferred_name": "Ada"}),
            ("preferences", PREFERENCES),
        ]
    )

    rows = run.get_step("summary").context["summary"]

    assert [row.label for row in rows] == [
        "Account type",
        "Preferred name",
        "Preferences",
    ]


def test_summary_renders_each_answer_as_display_text(business_run):
    rows = business_run.get_step("summary").context["summary"]

    preferences = {field.label: field.value for field in rows[-1].fields}

    assert preferences == {
        "Contact method": "Post",
        "Toppings": "Cheese, Basil",
        "Marketing emails": "Yes",
        "Start date": "Oct. 12, 2025",
        "Note": "Leave with a neighbour",
    }


def test_summary_omits_the_step_being_rendered(business_run):
    rows = business_run.get_step("summary").context["summary"]

    assert "summary" not in [row.name for row in rows]


def test_each_row_links_to_the_step_that_changes_it(business_run):
    response = business_run.get_step("summary")

    rows = response.context["summary"]

    assert [row.url for row in rows] == [
        business_run.step_url("account_type"),
        business_run.step_url("business_name"),
        business_run.step_url("preferences"),
    ]
    assertContains(
        response,
        f'<a href="{business_run.step_url("business_name")}">Change Business name</a>',
        html=True,
    )


def test_changing_an_answer_returns_to_the_summary(business_run):
    change_url = business_run.get_step("summary").context["summary"][1].url

    response = business_run.driver.client.post(
        change_url, {"business_name": "Beta Ltd"}
    )

    assertRedirects(
        response, business_run.step_url("summary"), fetch_redirect_response=False
    )


def test_summary_reflects_a_changed_answer(business_run):
    business_run.post_step("business_name", {"business_name": "Beta Ltd"})

    rows = business_run.get_step("summary").context["summary"]

    assert rows[1].fields[0].value == "Beta Ltd"


def test_summary_follows_the_run_through_a_branch_flip(business_run):
    business_run.post_step("account_type", {"account_type": "personal"})
    business_run.post_step("preferred_name", {"preferred_name": "Ada"})

    rows = business_run.get_step("summary").context["summary"]

    assert [row.name for row in rows] == [
        "account_type",
        "preferred_name",
        "preferences",
    ]
    assert rows[1].fields[0].value == "Ada"


def test_summary_rebuilds_each_answered_form_once(business_run):
    """The bind-once guarantee: one form reconstruction per row, however many
    fields the page renders from it.

    Four rather than three because this wizard's branch predicate reads an
    answer of its own to pick the arm — a cost the run pays on every request,
    summary or not. The summary's own share is one per row, even though the
    template renders five fields from the preferences row alone.
    """
    with counting_walks() as counts:
        response = business_run.get_step("summary")

    rows = response.context["summary"]
    assert [len(row.fields) for row in rows] == [1, 1, 5]
    assert counts.form_rebuilds == len(rows) + 1


def test_a_row_carries_the_form_behind_it(business_run):
    """The escape hatch: a template that needs more than the formatted text
    reaches the step's own bound form, still built only once."""
    rows = business_run.get_step("summary").context["summary"]

    assert rows[1].form.cleaned_data == {"business_name": "Acme Ltd"}
    assert rows[1].form is rows[1].step.form


def test_summary_renders_answers_that_have_no_plain_text_of_their_own(
    wizard_driver, isolated_media_root
):
    """Grouped choices, dates and times, and an upload — none of which a
    template can show by echoing the stored value."""
    run = wizard_driver("summary-display-wizard").start()
    run.post_step(
        "delivery",
        {
            "delivery": "sms",
            "collect_at": "2025-10-12 09:30",
            "opens_at": "09:30",
            "photo": SimpleUploadedFile("passport.png", b"bytes"),
            "deposit": "1234.5",
            "note": "",
        },
    )

    rows = run.get_step("summary").context["summary"]

    assert {field.label: field.value for field in rows[0].fields} == {
        "Delivery": "SMS",
        "Collect at": "Oct. 12, 2025, 9:30 a.m.",
        "Opens at": "9:30 a.m.",
        "Photo": "passport.png",
        # The project's own field, which nothing could have guessed at:
        # `str()` would have shown `1234.50`.
        "Deposit": "£1,234.50",
        "Note": "",
    }


def test_summary_hooks_are_overridable(wizard_driver):
    run = wizard_driver("custom-summary-wizard").start()
    run.post_step("preferences", PREFERENCES)

    rows = run.get_step("summary").context["summary"]

    assert [row.label for row in rows] == ["PREFERENCES"]
    assert [field.label for field in rows[0].fields] == [
        "Contact method",
        "Toppings",
        "Marketing emails",
        "Start date",
    ]
    assert rows[0].fields[-1].value == "12/10/2025"


def test_a_revisited_summary_step_does_not_list_itself(client, business_run):
    """A wizard that only runs forwards never has its summary step in `path`
    — the step being rendered is the cursor, and the cursor is unanswered by
    definition. A run revisited after the summary was answered does, so the
    page has to drop itself or it offers to change its own confirmation.
    """
    from gandalf.testing import stored_run, seed_run

    state = stored_run(client, business_run.run_id)["state"]
    seed_run(
        client,
        business_run.run_id,
        {"state": [*state, {"step": {}}]},
    )

    response = business_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    labels = [row.label for row in response.context["summary"]]
    assert labels == ["Account type", "Business name", "Preferences"]
    assertContains(response, "Change Preferences")
    assertNotContains(response, "Change Summary")


ADDRESS = {
    "line_1": "12 High Street",
    "line_2": "",
    "town": "Ely",
    "postcode": "CB7 4AA",
    "lookup_token": "tok-9",
}


@pytest.fixture
def address_run(wizard_driver):
    """A run whose address is answered, parked on the summary step."""
    run = wizard_driver("grouped-summary-wizard").start()
    run.post_steps(
        [
            ("who", {"name": "Ada"}),
            ("address", ADDRESS),
        ]
    )
    return run


def test_a_grouped_step_renders_as_one_line(address_run):
    """Four fields and a hidden token, declared on the summary view, reach
    the page as a single labelled answer under the step's own heading."""
    response = address_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary_wizard.html")
    rows = response.context["summary"]
    assert [(field.label, field.value) for field in rows[1].fields] == [
        (None, "12 High Street, Ely, CB7 4AA"),
    ]
    assertContains(response, "<span>12 High Street, Ely, CB7 4AA</span>", html=True)


def test_a_grouped_step_still_links_to_the_step_that_changes_it(address_run):
    response = address_run.get_step("summary")

    assertContains(
        response,
        f'<a href="{address_run.step_url("address")}">Change Address</a>',
        html=True,
    )


def test_a_grouped_row_costs_no_extra_form_rebuild(address_run):
    """Grouping reads the same single form the row was already built from."""
    with counting_walks() as counts:
        response = address_run.get_step("summary")

    rows = response.context["summary"]
    assert [len(row.fields) for row in rows] == [1, 1]
    assert counts.form_rebuilds == len(rows)


def test_a_step_grown_mid_walk_is_shaped_by_name_like_any_other(wizard_driver):
    """An expansion's steps do not exist until the walk reaches them, so the
    declaration is not the whole set of names — and a key naming one of them
    has to be taken on trust rather than refused."""
    run = wizard_driver("expanded-summary-wizard").start()
    run.post_steps([("delivery", {"delivery": "home"}), ("address", ADDRESS)])

    response = run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    rows = response.context["summary"]
    assert [(row.name, row.fields[0].value) for row in rows] == [
        ("delivery", "To my address"),
        ("address", "12 High Street, Ely, CB7 4AA"),
    ]


def test_a_key_that_names_no_step_is_refused(monkeypatch, address_run):
    """A renamed step would otherwise take its shaping with it and go quietly
    back to one line per field, in production."""
    monkeypatch.setattr(
        views.GroupedSummaryStepView,
        "summary_overrides",
        {"postal_address": [Group("town", "postcode")]},
    )

    with pytest.raises(ImproperlyConfigured, match="postal_address"):
        address_run.get_step("summary")


def test_a_field_named_by_two_specs_is_refused(monkeypatch, address_run):
    monkeypatch.setattr(
        views.GroupedSummaryStepView,
        "summary_overrides",
        {"address": [Group("line_1", "town"), Group("town", "postcode")]},
    )

    with pytest.raises(ImproperlyConfigured, match="town"):
        address_run.get_step("summary")


def test_a_group_survives_a_step_that_asks_for_less(wizard_driver):
    """A dynamic `get_form_class()` need not offer every field a group
    names, so the declaration cannot be checked and the group has to
    survive asking for less: `town` is named, never asked, and dropped."""
    run = wizard_driver("dynamic-summary-wizard").start()
    run.post_step("address", {"line_1": "12 High Street", "postcode": "CB7 4AA"})

    rows = run.get_step("summary").context["summary"]

    assert rows[0].fields[0].value == "12 High Street, CB7 4AA"


def test_a_group_naming_a_field_a_declared_step_has_not_got_is_refused(
    monkeypatch, address_run
):
    """Where the declaration does know the fields, a name it does not have
    is a typo — and a typo in a Hide leaves the answer on the page."""
    monkeypatch.setattr(
        views.GroupedSummaryStepView,
        "summary_overrides",
        {"address": [Hide("lookup_taken")]},
    )

    with pytest.raises(ImproperlyConfigured, match="lookup_taken"):
        address_run.get_step("summary")


def test_a_group_skips_a_field_the_page_leaves_off(monkeypatch, address_run):
    monkeypatch.setattr(
        views.GroupedSummaryStepView,
        "include_summary_field",
        lambda self, step, bound_field: bound_field.name != "town",
    )

    rows = address_run.get_step("summary").context["summary"]

    assert rows[1].fields[0].value == "12 High Street, CB7 4AA"


def test_a_summary_lists_every_row_of_a_formset_step(wizard_driver):
    """The acceptance case for a repeated step on a check-your-answers
    page: the answers are all on it, and the page is reached over HTTP the
    way a person reaches it. The first step is a bare Django `FormView`,
    which has no say in how its answer reads, so both halves are exercised
    at once."""
    run = wizard_driver("opening-hours-wizard").start()
    run.post_step("who", {"name": "Ada"})
    run.post_step(
        "opening-hours",
        {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "7",
            "form-0-day": "Monday",
            "form-0-opens": "09:00",
            "form-1-day": "Tuesday",
            "form-1-opens": "10:00",
        },
    )

    rows = run.get_step("summary").context["summary"]

    assert [field.value for field in rows[0].fields] == ["Ada"]
    assert [field.value for field in rows[1].fields] == [
        "Monday",
        "09:00",
        "Tuesday",
        "10:00",
    ]


@pytest.fixture
def templated_run(wizard_driver):
    """A run parked on a summary whose address names its own template."""
    run = wizard_driver("templated-summary-wizard").start()
    run.post_steps(
        [
            ("who", {"name": "Ada"}),
            (
                "address",
                {
                    "line_1": "12 High Street",
                    "line_2": "",
                    "town": "Ely",
                    "postcode": "CB7 4AA",
                    "lookup_token": "tok_123",
                },
            ),
        ]
    )
    return run


def test_a_group_renders_through_the_template_it_names(templated_run):
    """The review template includes `field.template_name` and knows no step
    names; the address's own partial decides how an address reads."""
    response = templated_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary/address.html")
    assertContains(
        response,
        '<ul class="address"><li>12 High Street</li><li>Ely</li><li>CB7 4AA</li></ul>',
        html=True,
    )


def test_a_partial_can_read_an_answer_the_form_derived(templated_run):
    """`outcode` is in `cleaned_data` and in no field, so only the form can
    say it — `field.form` is how the partial gets there."""
    response = templated_run.get_step("summary")

    assertContains(response, "Outcode: CB7")


def test_an_answer_that_names_no_template_reads_as_its_value(templated_run):
    """Gandalf ships no templates, so an answer naming none has nothing to
    render through and the page reads its value instead."""
    response = templated_run.get_step("summary")

    rows = response.context["summary"]
    assert rows[0].fields[0].template_name is None
    assertContains(response, "<span>Ada</span>", html=True)
    assertNotContains(response, "tok_123")


def test_a_render_shows_a_formset_step_as_its_rows(wizard_driver):
    """The reference used to teach a whole `build_summary_row()` override
    for this. A `Render` names no fields, and the formset's rows are in the
    form it is handed."""
    run = wizard_driver("rendered-summary-wizard").start()
    run.post_steps(
        [
            ("who", {"name": "Ada"}),
            (
                "opening-hours",
                {
                    "form-TOTAL_FORMS": "2",
                    "form-INITIAL_FORMS": "0",
                    "form-MIN_NUM_FORMS": "0",
                    "form-MAX_NUM_FORMS": "7",
                    "form-0-day": "Monday",
                    "form-0-opens": "09:00",
                    "form-1-day": "Tuesday",
                    "form-1-opens": "10:00",
                },
            ),
        ]
    )

    response = run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary/hours.html")
    assertContains(response, "<li>Monday from 09:00</li>", html=True)
    assertContains(response, "<li>Tuesday from 10:00</li>", html=True)
    rows = response.context["summary"]
    assert len(rows[1].fields) == 1


def test_a_render_leaves_out_what_a_hide_names_over_http(monkeypatch, templated_run):
    """A `Render` takes the whole step; a `Hide` beside it still hides."""
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "summary_overrides",
        {
            "address": [
                Render("testapp/summary/address.html"),
                Hide("lookup_token"),
            ]
        },
    )

    response = templated_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary/address.html")
    assertContains(response, "<li>12 High Street</li>", html=True)
    assertNotContains(response, "tok_123")


def test_a_render_asks_whether_to_include_each_answer(monkeypatch, templated_run):
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "summary_overrides",
        {"address": [Render("testapp/summary/address.html")]},
    )
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "include_summary_field",
        lambda self, step, bound_field: bound_field.name != "town",
    )

    response = templated_run.get_step("summary")

    assertNotContains(response, "<li>Ely</li>", html=True)
    assertContains(response, "<li>CB7 4AA</li>", html=True)


def test_a_group_beside_a_render_takes_its_own_fields_over_http(
    monkeypatch, templated_run
):
    """The rest of the address renders through the template; the two fields
    the group names keep a line of their own."""
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "summary_overrides",
        {
            "address": [
                Render("testapp/summary/address.html"),
                Group("town", "postcode"),
                Hide("lookup_token"),
            ]
        },
    )

    response = templated_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary/address.html")
    assertContains(response, "<li>12 High Street</li>", html=True)
    assertNotContains(response, "<li>Ely</li>", html=True)
    assertContains(response, "Ely, CB7 4AA")


def test_two_specs_naming_no_fields_are_refused_over_http(monkeypatch, templated_run):
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "summary_overrides",
        {
            "address": [
                Render("testapp/summary/address.html"),
                Render("testapp/summary/answer.html"),
            ]
        },
    )

    with pytest.raises(ImproperlyConfigured, match="names no fields"):
        templated_run.get_step("summary")


def test_a_render_left_with_nothing_still_renders(monkeypatch, templated_run):
    """Its template is the point, not the values it was handed — an empty
    formset says "none given" the same way."""
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "summary_overrides",
        {
            "address": [
                Render("testapp/summary/address.html"),
                Group("line_1", "line_2", "town", "postcode", "lookup_token"),
            ]
        },
    )

    response = templated_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/summary/address.html")
    assert response.context["summary"][1].fields[-1].parts == ()


def test_a_group_naming_no_fields_takes_the_rest_over_http(monkeypatch, templated_run):
    monkeypatch.setattr(
        views.TemplatedSummaryStepView,
        "summary_overrides",
        {"address": [Group(label="Address"), Hide("lookup_token")]},
    )

    response = templated_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assertContains(response, "12 High Street, Ely, CB7 4AA")
    assertNotContains(response, "tok-9")


@pytest.fixture
def colocated_run(wizard_driver):
    """A run whose address step says how its own answers read."""
    run = wizard_driver("colocated-summary-wizard").start()
    run.post_steps([("who", {"name": "Ada"}), ("address", ADDRESS)])
    return run


def test_a_step_shapes_its_own_row_without_the_page_naming_it(colocated_run):
    """`ColocatedSummaryWizardViewSet`'s review view declares nothing at
    all, and the address still reads as an address."""
    response = colocated_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    rows = response.context["summary"]
    assert [(field.label, field.value) for field in rows[1].fields] == [
        ("Address", "12 High Street, Ely, CB7 4AA"),
    ]
    assertNotContains(response, "tok-9")


def test_a_step_shaping_a_field_it_has_not_got_is_refused_over_http(
    monkeypatch, colocated_run
):
    monkeypatch.setattr(
        views.SelfShapingAddressStepView,
        "summary_fields",
        [Hide("lookup_taken")],
    )

    with pytest.raises(ImproperlyConfigured, match="own summary_fields"):
        colocated_run.get_step("summary")


def test_a_bare_form_step_shapes_its_row_from_the_declaration(wizard_driver):
    """`DeclaredSummaryWizardViewSet`'s address is a bare `forms.Form` with
    no view of its own, and still reads as one line."""
    run = wizard_driver("declared-summary-wizard").start()
    run.post_steps([("who", {"name": "Ada"}), ("address", ADDRESS)])

    response = run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    rows = response.context["summary"]
    assert [(field.label, field.value) for field in rows[1].fields] == [
        ("Address", "12 High Street, Ely, CB7 4AA"),
    ]
    assertNotContains(response, "tok-9")


def test_a_step_saying_how_it_reads_in_two_places_is_refused():
    with pytest.raises(ImproperlyConfigured, match="in one place"):
        Wizard().step(
            views.SelfShapingAddressStepView,
            name="address",
            summary_fields=[Group("town", "postcode")],
        )


def test_a_form_carrying_summary_fields_is_refused():
    class _LeftoverForm(AddressForm):
        summary_fields = [Group("town", "postcode")]

    with pytest.raises(ImproperlyConfigured, match="which nothing reads"):
        Wizard().step(_LeftoverForm, name="address")


@pytest.fixture
def questioned_run(wizard_driver):
    """A run whose address step asked two things and says so."""
    run = wizard_driver("questioned-summary-wizard").start()
    run.post_steps([("who", {"name": "Ada"}), ("address", ADDRESS)])
    return run


def test_one_step_reads_as_the_questions_it_asked(questioned_run):
    response = questioned_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    rows = response.context["summary"]
    assert [(row.label, row.fields[0].value) for row in rows] == [
        ("Who you are", "Ada"),
        ("Address", "12 High Street, Ely"),
        ("Postcode", "CB7 4AA"),
    ]
    assertContains(response, "<dt>Postcode</dt>", html=True)
    assertNotContains(response, "tok-9")


def test_every_row_of_a_step_changes_that_step(questioned_run):
    """Three things to check, one place to go and fix any of them."""
    response = questioned_run.get_step("summary")

    rows = response.context["summary"]
    assert rows[1].url == rows[2].url == questioned_run.step_url("address")


def test_an_answer_no_question_asks_is_refused_over_http(monkeypatch, questioned_run):
    monkeypatch.setattr(
        views.SummaryStepView,
        "summary_overrides",
        {"address": [Question("Address", Group("line_1", "line_2", "town"))]},
    )

    with pytest.raises(ImproperlyConfigured, match="in none of them"):
        questioned_run.get_step("summary")


def test_a_spec_beside_a_question_is_refused_over_http(monkeypatch, questioned_run):
    monkeypatch.setattr(
        views.SummaryStepView,
        "summary_overrides",
        {
            "address": [
                Question("Address", Group("line_1", "line_2", "town")),
                Group("postcode"),
            ]
        },
    )

    with pytest.raises(ImproperlyConfigured, match="no row to belong to"):
        questioned_run.get_step("summary")


def test_an_empty_question_is_refused_over_http(monkeypatch, questioned_run):
    monkeypatch.setattr(
        views.SummaryStepView,
        "summary_overrides",
        {"address": [Question("Address"), Hide("lookup_token")]},
    )

    with pytest.raises(ImproperlyConfigured, match="nothing in it"):
        questioned_run.get_step("summary")


def test_a_spec_naming_no_fields_inside_a_question_is_refused_over_http(
    monkeypatch, questioned_run
):
    monkeypatch.setattr(
        views.SummaryStepView,
        "summary_overrides",
        {
            "address": [
                Question("Address", Render("testapp/summary/address.html")),
                Hide("lookup_token"),
            ]
        },
    )

    with pytest.raises(ImproperlyConfigured, match="no rest"):
        questioned_run.get_step("summary")
