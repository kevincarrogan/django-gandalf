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

from gandalf.summary import Group, Hide
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
        "summary_fields",
        {"postal_address": [Group("town", "postcode")]},
    )

    with pytest.raises(ImproperlyConfigured, match="postal_address"):
        address_run.get_step("summary")


def test_a_field_named_by_two_specs_is_refused(monkeypatch, address_run):
    monkeypatch.setattr(
        views.GroupedSummaryStepView,
        "summary_fields",
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
        "summary_fields",
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
