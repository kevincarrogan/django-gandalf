"""Drive every chapter of the Learn walkthrough through the Django test client.

Each chapter of ``docs/learn/`` has a runnable counterpart in
``tests/testapp/readme/`` mounted under ``readme/``. These tests exercise those
counterparts end to end, so a chapter snippet that stops working (or a "Try it
live" link that stops resolving) fails CI. The *Testing* reference page
(``docs/reference/testing.md``) is kept honest the same way: its snippets are these tests, driven
through ``gandalf.testing``.
"""

from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertRedirects,
    assertTemplateUsed,
)

from gandalf.testing import stored_section_stash, stored_stash
from tests.testapp.models import Application


ADDRESS = {
    "line_1": "12 High Street",
    "line_2": "",
    "town": "Ely",
    "postcode": "CB7 4AA",
    "lookup_token": "10009312345",
}

ORGANISATION = [
    ("applying-as", {"applying_as": "organisation"}),
    ("organisation", {"organisation_name": "Ely Rowing Club"}),
    ("organisation-type", {"organisation_type": "charity"}),
    ("charity-number", {"charity_number": "1234567"}),
    ("trustees", {"trustees": "2"}),
    ("trustee-0", {"name": "Ada"}),
    ("trustee-1", {"name": "Grace"}),
]


# --- Every start URL reverses (the "Try it live" links resolve) -------------


@pytest.mark.parametrize(
    "name, url_kwargs",
    [
        ("readme-first", None),
        ("readme-branching", None),
        ("readme-switch", None),
        ("readme-expand", None),
        ("readme-fund", {"fund": "arts"}),
        ("readme-review", None),
        ("readme-step-view", None),
        ("readme-upload", None),
        ("readme-stash", None),
        ("readme-apply-start", None),
    ],
)
def test_readme_chapter_start_url_is_reachable(client, wizard_driver, name, url_kwargs):
    if url_kwargs is None:
        url_kwargs = {}
    driver = wizard_driver(name, **url_kwargs)

    response = client.get(driver.start_url)

    # The start URL creates a run and redirects to it, so the link is live.
    assert response.status_code == HTTPStatus.FOUND


def test_demo_index_page_lists_the_chapters(client):
    # `just serve` lands on this page; it must render and link to the chapters.
    response = client.get(reverse("index"))

    assert response.status_code == HTTPStatus.OK
    assertContains(response, reverse("readme-first"))
    assertContains(response, reverse("readme-apply-start"))


# --- Chapter 1: a first wizard ----------------------------------------------


def test_chapter_1_collects_both_steps_and_finishes_once(wizard_driver):
    # README "Testing your wizards" drive() snippet.
    response, run = wizard_driver("readme-first").drive(
        [
            ("applicant", {"full_name": "Ada"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Application received from Ada <ada@example.com>"
    assert run.is_completed


def test_chapter_1_first_answer_advances_and_stores(wizard_driver):
    # README "Testing your wizards" step-at-a-time snippet.
    run = wizard_driver("readme-first").start()

    response = run.post_step("applicant", {"full_name": "Ada"})

    assert response["Location"] == run.step_url("contact")
    assert run.state == [{"step": {"full_name": "Ada"}}]


# --- Chapter 2: individuals and organisations -------------------------------


def test_chapter_2_takes_the_organisation_arm(wizard_driver):
    response, _ = wizard_driver("readme-branching").drive(
        [
            ("applying-as", {"applying_as": "organisation"}),
            ("organisation", {"organisation_name": "Ely Rowing Club"}),
            ("contact", {"email": "club@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Application from Ely Rowing Club <club@example.com>"


def test_chapter_2_takes_the_individual_arm(wizard_driver):
    response, _ = wizard_driver("readme-branching").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Application from Sculptor <ada@example.com>"


# --- Chapter 3: which kind of organisation ----------------------------------


@pytest.mark.parametrize(
    "organisation_type, number_step, number, expected",
    [
        ("charity", "charity-number", {"charity_number": "1234567"}, "(1234567)"),
        ("company", "company-number", {"company_number": "09876543"}, "(09876543)"),
    ],
)
def test_chapter_3_asks_the_number_the_kind_of_organisation_has(
    wizard_driver, organisation_type, number_step, number, expected
):
    response, _ = wizard_driver("readme-switch").drive(
        [
            ("applying-as", {"applying_as": "organisation"}),
            ("organisation", {"organisation_name": "Ely Rowing Club"}),
            ("organisation-type", {"organisation_type": organisation_type}),
            (number_step, number),
            ("contact", {"email": "club@example.com"}),
        ]
    )

    assert response.content == f"Application from Ely Rowing Club {expected}".encode()


def test_chapter_3_a_community_group_has_no_number_to_give(wizard_driver):
    """No case names it and there is no default, so the walk goes straight
    past the switch."""
    run = wizard_driver("readme-switch").start()

    response = run.post_steps(
        [
            ("applying-as", {"applying_as": "organisation"}),
            ("organisation", {"organisation_name": "Ely Allotments"}),
            ("organisation-type", {"organisation_type": "community"}),
        ]
    )

    assert response.context["form"].fields.keys() == {"email"}


# --- Chapter 4: as many trustees as there are --------------------------------


def test_chapter_4_grows_one_step_per_trustee(wizard_driver):
    response, _ = wizard_driver("readme-expand").drive(
        ORGANISATION + [("contact", {"email": "club@example.com"})]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Trustees: Ada, Grace"


# --- Chapter 5: different funds, different questions -------------------------


def test_chapter_5_an_applicant_is_not_asked_when_the_paper_arrived(wizard_driver):
    response, _ = wizard_driver("readme-paper").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Coach"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.content == b"Application from ada@example.com"


def test_chapter_5_a_staff_member_is_asked_when_the_paper_arrived(
    client, django_user_model, wizard_driver
):
    officer = django_user_model.objects.create_user("officer", is_staff=True)
    client.force_login(officer)

    response, _ = wizard_driver("readme-paper").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Coach"}),
            ("received-on", {"received_on": "2026-08-01"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert (
        response.content == b"Application from ada@example.com, received on 2026-08-01"
    )


def test_chapter_5_the_sport_fund_asks_no_portfolio(wizard_driver):
    response, _ = wizard_driver("readme-fund", fund="sport").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Coach"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.content == b"Application to the sport fund from ada@example.com"


def test_chapter_5_the_arts_fund_inserts_a_portfolio_step(wizard_driver):
    response, _ = wizard_driver("readme-fund", fund="arts").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("portfolio", {"portfolio_url": "https://ada.example.com"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.content == b"Application to the arts fund from ada@example.com"


# --- Chapter 7: check your answers -------------------------------------------


def _individual(run):
    return run.post_steps(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("contact", {"email": "ada@example.com"}),
            ("address", ADDRESS),
        ]
    )


def test_chapter_7_renders_a_completed_step_prefilled(wizard_driver):
    run = wizard_driver("readme-review").start()
    run.post_step("applying-as", {"applying_as": "individual"}, follow=True)

    # A completed step's own URL renders it again, pre-filled — this is the
    # edit affordance the summary links to.
    response = run.get_step("applying-as", follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="individual" selected')


def test_chapter_7_lists_every_answer_with_a_change_link(wizard_driver):
    run = wizard_driver("readme-review").start()
    _individual(run)

    response = run.get_step("review")

    assert response.status_code == HTTPStatus.OK
    rows = response.context["summary"]
    # Each row is named by the question that asked it, except the address,
    # which reads as one answer and takes its step's name.
    assert [(row.label, row.url) for row in rows] == [
        ("Are you applying as", run.step_url("applying-as")),
        ("What do you do?", run.step_url("about-you")),
        ("Email address", run.step_url("contact")),
        ("Address", run.step_url("address")),
    ]
    # The stored answers, as display text rather than raw values.
    assert rows[0].value == "An individual"
    assertContains(
        response,
        f'<a href="{run.step_url("contact")}">Change Email address</a>',
        html=True,
    )


def test_chapter_7_reads_an_address_back_as_one_line(wizard_driver):
    # README "Shaping a row" snippet: four fields on one row, the lookup's
    # own answer hidden, and the row still named by the step.
    run = wizard_driver("readme-review").start()
    _individual(run)

    response = run.get_step("review")

    address = response.context["summary"][3]
    assert (address.label, address.value) == (
        "Address",
        "12 High Street, Ely, CB7 4AA",
    )
    assertContains(response, "<span>12 High Street, Ely, CB7 4AA</span>", html=True)


def test_chapter_7_restores_a_dormant_arm_answer(wizard_driver):
    run = wizard_driver("readme-review").start()

    # Organisation arm: answer the type and the organisation's name.
    run.post_steps(
        [
            ("applying-as", {"applying_as": "organisation"}),
            ("organisation", {"organisation_name": "Ely Rowing Club"}),
        ]
    )

    # Edit the type to individual — the organisation arm goes dormant.
    run.post_step("applying-as", {"applying_as": "individual"}, follow=True)
    # Flip back — the dormant name is restored, not re-asked.
    run.post_step("applying-as", {"applying_as": "organisation"}, follow=True)

    prefilled = run.get_step("organisation", follow=True)
    assertContains(prefilled, "Ely Rowing Club")


def test_chapter_7_confirms_and_finishes(wizard_driver):
    run = wizard_driver("readme-review").start()
    _individual(run)

    response = run.post_step("review", {}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Application from Sculptor confirmed"


# --- Chapter 6: a step with a view of its own -------------------------------


def _to_contact(run):
    return run.post_steps(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
        ]
    )


def test_chapter_6_the_website_step_uses_its_own_template(wizard_driver):
    run = wizard_driver("readme-step-view").start()
    _to_contact(run)

    response = run.post_step("contact", {"email": "ada@example.com"}, follow=True)

    # The step's own template wins over the viewset's.
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/other_linear_wizard.html")


def test_chapter_6_the_website_step_prefills_from_the_email(wizard_driver):
    run = wizard_driver("readme-step-view").start()
    _to_contact(run)

    response = run.post_step("contact", {"email": "ada@example.com"}, follow=True)

    # get_initial() read the contact step's answer off request.run.path.
    assert response.context["form"]["website"].value() == "https://example.com"


def test_chapter_6_a_revisit_shows_the_stored_answer_not_the_guess(wizard_driver):
    # Chapter 8's wizard, because it has steps after the website one to come
    # back from; the view under test is chapter 6's.
    run = wizard_driver("readme-escape").start()
    _to_contact(run)
    run.post_steps(
        [
            ("contact", {"email": "ada@example.com"}),
            ("website", {"website": "https://ada.example.com"}),
        ]
    )

    response = run.get_step("website")

    # super().get_initial() carried the stored answer; the guess only fills a gap.
    assert response.context["form"]["website"].value() == "https://ada.example.com"


def test_chapter_6_the_website_step_survives_being_walked_past(wizard_driver):
    # The step's get_initial() reads run state, and every later request
    # replays the step — re-entering that read from inside the walk.
    run = wizard_driver("readme-step-view").start()
    _to_contact(run)
    response = run.post_steps(
        [
            ("contact", {"email": "ada@example.com"}),
            ("website", {"website": "https://ada.example.com"}),
        ]
    )

    assert (
        response.content
        == b"Application from ada@example.com (https://ada.example.com)"
    )


# --- Chapter 8: an answer that means "not here" -----------------------------


def test_chapter_8_parks_a_known_email_at_the_login_page(wizard_driver):
    run = wizard_driver("readme-escape").start()
    _to_contact(run)

    response = run.post_step("contact", {"email": "existing@example.com"})

    # Park redirects the user out and does not store the answer, so the run
    # keeps only the two answers before it and stays on the contact step.
    assertRedirects(response, reverse("readme-login"), fetch_redirect_response=False)
    assert len(run.state) == 2


# --- Chapter 9: proof it exists ----------------------------------------------


def _document():
    return SimpleUploadedFile(
        "constitution.pdf", b"bytes", content_type="application/pdf"
    )


def test_chapter_9_stores_and_reports_the_upload(wizard_driver, isolated_media_root):
    run = wizard_driver("readme-upload").start()

    response = run.post_steps(
        ORGANISATION
        + [
            ("governing-document", {"document": _document()}),
            ("contact", {"email": "club@example.com"}),
            ("website", {"website": ""}),
            ("address", ADDRESS),
            ("review", {}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Received constitution.pdf"


def test_chapter_9_an_individual_is_never_asked_for_a_document(wizard_driver):
    response, _ = wizard_driver("readme-upload").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("contact", {"email": "ada@example.com"}),
            ("website", {"website": ""}),
            ("address", ADDRESS),
            ("review", {}),
        ]
    )

    assert response.content == b"Application received (no document needed)"


# --- Chapter 10: finishing, and what it leaves behind -------------------------


@pytest.mark.django_db
def test_chapter_10_opens_a_record_at_the_start_and_submits_it_at_the_end(
    wizard_driver,
):
    run = wizard_driver("readme-record").start()
    application = Application.objects.get()
    assert application.submitted is False

    response = run.post_steps(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("contact", {"email": "ada@example.com"}),
            ("website", {"website": ""}),
            ("address", ADDRESS),
            ("review", {}),
        ]
    )

    assertContains(response, application.reference)
    application.refresh_from_db()
    assert (application.submitted, application.email) == (True, "ada@example.com")
    assert Application.objects.count() == 1
    assert run.is_completed


@pytest.mark.django_db
def test_chapter_10_a_revisit_after_completion_still_names_the_record(wizard_driver):
    run = wizard_driver("readme-record").start()
    run.post_steps(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("contact", {"email": "ada@example.com"}),
            ("website", {"website": ""}),
            ("address", ADDRESS),
            ("review", {}),
        ]
    )

    # The answers are gone; the metadata bag on the tombstone is not.
    response = run.get(follow=True)

    assertContains(response, Application.objects.get().reference)
    assert run.data == {"completed": True, "meta": {"run": {"application_id": 1}}}


# --- Chapter 11: coming back later -------------------------------------------


def test_chapter_11_completes_reopens_and_recompletes_with_an_edit(
    client, wizard_driver
):
    driver = wizard_driver("readme-stash")
    response, first_run = driver.drive(
        [
            ("applicant", {"full_name": "Ada"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )
    assert response.content == b"Contact details saved."

    # Reopening resurrects the stash into a fresh run, landing on a step
    # with the saved answer pre-filled.
    response = client.get(reverse("readme-stash-reopen"), follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="Ada"')
    new_run = driver.new_run(first_run)
    assert new_run.run_id != first_run.run_id

    # One successful edit re-completes the wizard: done() fires again and the
    # stash now holds the edited answers.
    response = new_run.post_step("applicant", {"full_name": "Grace"}, follow=True)

    assert response.content == b"Contact details saved."
    payload = stored_stash(client, "contact")
    assert payload["state"][0] == {"step": {"full_name": "Grace"}}


def test_chapter_11_reopening_without_a_stash_starts_fresh(client, wizard_driver):
    response = client.get(reverse("readme-stash-reopen"))

    assertRedirects(
        response,
        wizard_driver("readme-stash").start_url,
        fetch_redirect_response=False,
    )


# --- Chapter 12: a task list --------------------------------------------------


def test_chapter_12_lists_sections_and_drives_one_to_complete(client, wizard_driver):
    page_url = reverse("readme-task-list")
    response = client.get(page_url)

    assert response.status_code == HTTPStatus.OK
    assert [(row.title, row.status) for row in response.context["task_list"].rows] == [
        ("Contact details", "not-started"),
        ("Address", "not-started"),
    ]

    # Entering a member from the hub lands on its first step.
    door = reverse("readme-task-list-entry", kwargs={"entry": "contact"})
    client.get(door, follow=True)
    driver = wizard_driver("readme-task-list-contact")
    run = driver.only_run()

    # Half-answered, the member reads as Incomplete on the hub.
    run.post_step("name", {"full_name": "Ada"}, follow=True)
    assertContains(client.get(page_url), "Incomplete")

    # Finished, it stashes its answers and reads as Complete.
    response = run.post_steps(
        [
            ("email", {"email": "ada@example.com"}),
            ("review", {}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assertContains(response, "Complete")
    assert stored_section_stash(client, "contact")["state"][0] == {
        "step": {"full_name": "Ada"}
    }


def test_chapter_12_reopens_a_completed_section_on_its_review_page(
    client, wizard_driver
):
    door = reverse("readme-task-list-entry", kwargs={"entry": "address"})
    client.get(door, follow=True)
    driver = wizard_driver("readme-task-list-address")
    run = driver.only_run()
    run.post_steps([("address", ADDRESS), ("review", {})])

    response = client.get(door, follow=True)

    # `reopen_at="review"` lands the user on their answers, not step one.
    assert response.status_code == HTTPStatus.OK
    assertContains(response, "12 High Street")
    assertContains(response, "Check your answers")
    # A re-opened member arrives with every step answered, the review step
    # included, so the page has to drop itself from its own rows.
    assertContains(response, "Change Address")
    assertNotContains(response, "Change Review")


# --- Chapter 13: budget lines -------------------------------------------------


def test_chapter_13_adds_changes_and_removes_budget_lines(client):
    """The README's add-another example, driven the way the page drives it:
    every action is a POST to the collection, and every link it hands out is
    one of its own routes."""
    page = reverse("readme-project-budget")

    # Empty, the page offers only the first line.
    assertContains(client.get(page), "You have not added any budget lines")

    # Adding registers the line, then lands on its first step.
    step_url = client.post(page, {"add_another": "yes"})["Location"]
    client.post(step_url, {"item": "Paint", "cost": "120"})
    assertContains(client.get(page), "Incomplete")

    # Finishing caches the name the row goes by.
    review_url = client.get(page).context["items"].rows[0].url
    client.post(client.get(review_url)["Location"], {})
    listing = client.get(page)
    assert [(str(row.title), row.status) for row in listing.context["items"].rows] == [
        ("Paint", "complete")
    ]

    # A second line, removed again, leaves the first untouched and un-renumbered.
    first = listing.context["items"].rows[0].item_id
    client.post(
        client.post(page, {"add_another": "yes"})["Location"],
        {"item": "Brushes", "cost": "30"},
    )
    second = client.get(page).context["items"].rows[1].item_id
    client.post(reverse("readme-project-budget-remove", kwargs={"item": second}))
    assert [row.item_id for row in client.get(page).context["items"].rows] == [first]

    # Saying there are no more completes the collection, and the task list
    # above it reads that status without walking anything.
    assertRedirects(client.post(page, {"add_another": "no"}), reverse("readme-project"))
    overview = client.get(reverse("readme-project"))
    assert [(row.title, row.status) for row in overview.context["task_list"].rows] == [
        ("Project", "not-started"),
        ("Budget", "complete"),
    ]
    assert overview.context["task_list"].rows[1].url == page


def test_chapter_13_an_empty_budget_cannot_be_declared_complete(client):
    """`min_items = 1`: saying "no more" with nothing added is not a budget."""
    page = reverse("readme-project-budget")

    client.post(page, {"add_another": "no"})

    overview = client.get(reverse("readme-project"))
    assert overview.context["task_list"].rows[1].status == "incomplete"


# --- Chapter 14: locked and hidden -------------------------------------------


def _finish_project(client, amount):
    door = reverse("readme-gated-entry", kwargs={"entry": "project"})
    step_url = client.get(door)["Location"]
    client.post(step_url, {"title": "Boathouse roof", "amount": str(amount)})
    review_url = step_url.rsplit("/project/", 1)[0] + "/review/"
    return client.post(review_url, {}, follow=True)


def _gated_statuses(client):
    response = client.get(reverse("readme-gated"))
    return {row.key: row.status for row in response.context["task_list"].rows}


def test_chapter_14_referees_are_locked_until_the_project_is_described(client):
    assert _gated_statuses(client)["referees"] == "blocked"
    door = reverse("readme-gated-entry", kwargs={"entry": "referees"})
    assertRedirects(client.get(door), reverse("readme-gated"))

    _finish_project(client, 5_000)

    assert _gated_statuses(client)["referees"] == "not-started"


def test_chapter_14_match_funding_appears_above_the_threshold(client):
    assert "match-funding" not in _gated_statuses(client)

    _finish_project(client, 25_000)

    assert _gated_statuses(client)["match-funding"] == "not-started"
    assertContains(client.get(reverse("readme-gated")), "Match funding")


def test_chapter_14_match_funding_stays_hidden_below_it(client):
    _finish_project(client, 5_000)

    assert "match-funding" not in _gated_statuses(client)
    door = reverse("readme-gated-entry", kwargs={"entry": "match-funding"})
    assertRedirects(client.get(door), reverse("readme-gated"))
