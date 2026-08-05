"""A check-your-answers step built with `SummaryMixin`, over HTTP.

The rows a summary page needs — every answered step, in route order, with
its answers as display text and the URL that changes them — and the
guarantee that each step's form is reconstructed once per request however
many times the page reads it.
"""

from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertRedirects,
    assertTemplateUsed,
)

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
            "note": "",
        },
    )

    rows = run.get_step("summary").context["summary"]

    assert {field.label: field.value for field in rows[0].fields} == {
        "Delivery": "SMS",
        "Collect at": "Oct. 12, 2025, 9:30 a.m.",
        "Opens at": "9:30 a.m.",
        "Photo": "passport.png",
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
        {"state": [*state, {"step": {"confirmed": "on"}}]},
    )

    response = business_run.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    labels = [row.label for row in response.context["summary"]]
    assert labels == ["Account type", "Business name", "Preferences"]
    assertContains(response, "Change Preferences")
    assertNotContains(response, "Change Summary")
