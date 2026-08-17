"""Drive every README example through the Django test client.

Each example in ``README.md`` has a runnable counterpart in
``tests/testapp/readme_examples.py`` mounted under ``readme/``. These tests
exercise those counterparts end to end, so a README snippet that stops working
(or a "Try it live" link that stops resolving) fails CI. The "Testing your
wizards" README section is kept honest the same way: its snippets are these
tests, driven through ``gandalf.testing``.
"""

from http import HTTPStatus

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
import pytest
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertRedirects,
    assertTemplateUsed,
)

from gandalf.testing import stored_stash


# --- Every start URL reverses (the "Try it live" links resolve) -------------


@pytest.mark.parametrize(
    "name, url_kwargs",
    [
        ("readme-signup", None),
        ("readme-branching", None),
        ("readme-onboarding", {"plan": "solo"}),
        ("readme-expand", None),
        ("readme-file-upload", None),
        ("readme-form-view", None),
        ("readme-escape", None),
        ("readme-editing", None),
        ("readme-summary", None),
        ("readme-flip-flop", None),
        ("readme-stash", None),
    ],
)
def test_readme_example_start_url_is_reachable(client, wizard_driver, name, url_kwargs):
    if url_kwargs is None:
        url_kwargs = {}
    driver = wizard_driver(name, **url_kwargs)

    response = client.get(driver.start_url)

    # The start URL creates a run and redirects to it, so the link is live.
    assert response.status_code == HTTPStatus.FOUND


def test_demo_index_page_lists_the_example_wizards(client):
    # `just serve` lands on this page; it must render and link to the examples.
    response = client.get(reverse("index"))

    assert response.status_code == HTTPStatus.OK
    assertContains(response, reverse("readme-signup"))
    assertContains(response, reverse("readme-flip-flop"))


# --- Quickstart: linear signup ----------------------------------------------


def test_signup_wizard_collects_and_merges_both_steps(wizard_driver):
    # README "Testing your wizards" drive() snippet.
    response, run = wizard_driver("readme-signup").drive(
        [
            ("name", {"name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Signed up Ada <ada@example.com>"
    assert run.is_completed


def test_signup_first_answer_advances_and_stores(wizard_driver):
    # README "Testing your wizards" step-at-a-time snippet.
    run = wizard_driver("readme-signup").start()

    response = run.post_step("name", {"name": "Ada"})

    assert response["Location"] == run.step_url("email")
    assert run.state == [{"step": {"name": "Ada"}}]


# --- Branching --------------------------------------------------------------


def test_branching_wizard_takes_business_arm(wizard_driver):
    response, _ = wizard_driver("readme-branching").drive(
        [
            ("account_type", {"account_type": "business"}),
            ("business", {"business_name": "Acme"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Acme"


def test_branching_wizard_takes_personal_arm(wizard_driver):
    response, _ = wizard_driver("readme-branching").drive(
        [
            ("account_type", {"account_type": "personal"}),
            ("personal", {"preferred_name": "Ada"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Ada"


# --- Dynamic wizards: get_wizard() ------------------------------------------


def test_onboarding_solo_plan_skips_the_company_step(wizard_driver):
    response, _ = wizard_driver("readme-onboarding", plan="solo").drive(
        [
            ("name", {"name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Ada on the solo plan"


def test_onboarding_team_plan_inserts_the_company_step(wizard_driver):
    response, _ = wizard_driver("readme-onboarding", plan="team").drive(
        [
            ("name", {"name": "Ada"}),
            ("company", {"business_name": "Acme"}),
            ("email", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Ada on the team plan"


# --- .expand() --------------------------------------------------------------


def test_expand_wizard_grows_item_steps_mid_walk(wizard_driver):
    response, _ = wizard_driver("readme-expand").drive(
        [
            ("count", {"count": "2"}),
            ("item-0", {"name": "x"}),
            ("item-1", {"name": "y"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Collected x, y"


# --- File uploads -----------------------------------------------------------


def test_file_upload_wizard_stores_and_reports_the_upload(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("readme-file-upload").start()

    response = run.post_steps(
        [
            (
                "photo",
                {
                    "photo": SimpleUploadedFile(
                        "avatar.png", b"bytes", content_type="image/png"
                    )
                },
            ),
            ("name", {"name": "Ada"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Uploaded avatar.png"


# --- Step views: bringing your own FormView ---------------------------------


def test_form_view_step_uses_its_own_template(wizard_driver):
    run = wizard_driver("readme-form-view").start()

    response = run.post_step("account", {"email": "ada@example.com"}, follow=True)

    # The step's own template wins over the viewset's.
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/other_linear_wizard.html")


def test_form_view_step_prefills_from_a_prior_answer(wizard_driver):
    run = wizard_driver("readme-form-view").start()

    response = run.post_step("account", {"email": "ada@example.com"}, follow=True)

    # get_initial() read the account step's answer off context.run.path.
    assert response.context["form"]["company"].value() == "example.com"


def test_form_view_step_survives_being_walked_past(wizard_driver):
    # The step's get_initial() reads run state, and every later request
    # replays the step — re-entering that read from inside the walk.
    response, _ = wizard_driver("readme-form-view").drive(
        [
            ("account", {"email": "ada@example.com"}),
            ("billing", {"company": "Acme", "country": "IE"}),
            ("confirm", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Billing Acme (IE)"


# --- Escaping the wizard ----------------------------------------------------


def test_escape_wizard_parks_a_known_email(wizard_driver):
    run = wizard_driver("readme-escape").start()

    response = run.post_step("email", {"email": "existing@example.com"})

    # Park redirects the user out (to the landing page) and does not store the
    # answer, so the run keeps no stored steps and stays on the email step.
    assertRedirects(response, reverse("escape-landing"), fetch_redirect_response=False)
    assert run.state == []


def test_escape_wizard_continues_for_a_new_email(wizard_driver):
    response, run = wizard_driver("readme-escape").drive(
        [
            ("email", {"email": "new@example.com"}),
            ("name", {"name": "Ada"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"Signed up {run.run_id}".encode()


# --- Back-navigation / editing ----------------------------------------------


def test_editing_wizard_renders_a_completed_step_prefilled(wizard_driver):
    run = wizard_driver("readme-editing").start()
    run.post_step("account_type", {"account_type": "personal"}, follow=True)

    # A completed step's own URL renders it again, pre-filled — this is the
    # edit affordance the review template links to.
    response = run.get_step("account_type", follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'name="account_type"')


# --- Summary: a check-your-answers step -------------------------------------


def test_summary_wizard_lists_every_answer_with_a_change_link(wizard_driver):
    run = wizard_driver("readme-summary").start()
    run.post_steps(
        [
            ("name", {"name": "Ada"}),
            ("delivery", {"method": "express", "leave_with_neighbour": "on"}),
        ]
    )

    response = run.get_step("review")

    assert response.status_code == HTTPStatus.OK
    rows = response.context["summary"]
    assert [(row.label, row.url) for row in rows] == [
        ("Your name", run.step_url("name")),
        ("Delivery", run.step_url("delivery")),
    ]
    # The stored answers, as display text rather than raw values.
    assert [field.value for field in rows[1].fields] == ["Express", "Yes"]
    assertContains(
        response, f'<a href="{run.step_url("name")}">Change Your name</a>', html=True
    )


# --- Dormant memory: flipping a branch and back -----------------------------


def test_flip_flop_wizard_restores_a_dormant_arm_answer(wizard_driver):
    run = wizard_driver("readme-flip-flop").start()

    # Business arm: answer the account type and the company name.
    run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme"}),
        ]
    )

    # Edit the account type to personal — the business arm goes dormant.
    run.post_step("account_type", {"account_type": "personal"}, follow=True)
    # Flip back to business — the dormant "Acme" is restored, not re-asked.
    run.post_step("account_type", {"account_type": "business"}, follow=True)

    # The company step is satisfied again from dormant memory: GETting it shows
    # Acme pre-filled, and completing the run reports it without re-entry.
    prefilled = run.get_step("business_name", follow=True)
    assertContains(prefilled, "Acme")

    response = run.post_step("review", {"confirmed": "on"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Acme"


# --- Stashing and resurrecting runs -----------------------------------------


def test_stash_wizard_completes_reopens_and_recompletes_with_an_edit(
    client, wizard_driver
):
    driver = wizard_driver("readme-stash")
    response, first_run = driver.drive(
        [
            ("name", {"name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
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
    response = new_run.post_step("name", {"name": "Grace"}, follow=True)

    assert response.content == b"Contact details saved."
    payload = stored_stash(client, "contact")
    assert payload["state"][0] == {"step": {"name": "Grace"}}


def test_stash_reopen_without_a_stash_starts_fresh(client, wizard_driver):
    response = client.get(reverse("readme-stash-reopen"))

    assertRedirects(
        response,
        wizard_driver("readme-stash").start_url,
        fetch_redirect_response=False,
    )


# --- Hub and spoke: parallel sections ---------------------------------------


def test_hub_lists_sections_and_drives_one_to_complete(client, wizard_driver):
    hub_url = reverse("readme-hub")
    response = client.get(hub_url)

    assert response.status_code == HTTPStatus.OK
    assert [(row.title, row.status) for row in response.context["sections"]] == [
        ("Contact details", "not-started"),
        ("Address", "not-started"),
    ]

    # Entering a section from the hub lands on its first step.
    door = reverse("readme-hub-section", kwargs={"section": "contact"})
    client.get(door, follow=True)
    driver = wizard_driver("readme-hub-contact")
    run = driver.only_run()

    # Half-answered, the section reads as Incomplete on the hub.
    run.post_step("name", {"name": "Ada"}, follow=True)
    assertContains(client.get(hub_url), "Incomplete")

    # Finished, it stashes its answers and reads as Complete.
    response = run.post_steps(
        [
            ("email", {"email": "ada@example.com"}),
            ("review", {}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assertContains(response, "Complete")
    assert stored_stash(client, "contact")["state"][0] == {"step": {"name": "Ada"}}


def test_hub_reopens_a_completed_section_on_its_review_page(client, wizard_driver):
    door = reverse("readme-hub-section", kwargs={"section": "address"})
    client.get(door, follow=True)
    driver = wizard_driver("readme-hub-address")
    run = driver.only_run()
    run.post_steps(
        [
            ("address", {"line_one": "1 Main St", "postcode": "SW1A 1AA"}),
            ("review", {}),
        ]
    )

    response = client.get(door, follow=True)

    # `reopen_step="review"` lands the user on their answers, not step one.
    assert response.status_code == HTTPStatus.OK
    assertContains(response, "1 Main St")
    assertContains(response, "Check your answers")
    # A re-opened section arrives with every step answered, the review step
    # included, so the page has to drop itself from its own rows.
    assertContains(response, "Change Address")
    assertNotContains(response, "Change Review")


def test_a_collection_adds_changes_and_removes_items(client):
    """The README's add-another example, driven the way the page drives it:
    every action is a POST to the collection, and every link it hands out is
    one of its own routes."""
    page = reverse("readme-guests")

    # Empty, the page offers only the first item.
    assertContains(client.get(page), "You have not added any guests")

    # Adding registers the item, then lands on its first step.
    step_url = client.post(page, {"add_another": "yes"})["Location"]
    client.post(step_url, {"name": "Ada", "dietary_requirements": ""})
    assertContains(client.get(page), "Incomplete")

    # Finishing caches the name the row goes by.
    review_url = client.get(page).context["collection"].rows[0].url
    client.post(client.get(review_url)["Location"], {})
    listing = client.get(page)
    assert [
        (str(row.title), row.status) for row in listing.context["collection"].rows
    ] == [("Ada", "complete")]

    # A second item, removed again, leaves the first untouched and un-renumbered.
    first = listing.context["collection"].rows[0].item_id
    client.post(
        client.post(page, {"add_another": "yes"})["Location"],
        {"name": "Grace", "dietary_requirements": ""},
    )
    second = client.get(page).context["collection"].rows[1].item_id
    client.post(reverse("readme-guests-remove", kwargs={"item": second}))
    assert [row.item_id for row in client.get(page).context["collection"].rows] == [
        first
    ]

    # Saying there are no more completes the collection, and the task list
    # above it reads that status without walking anything.
    assertRedirects(
        client.post(page, {"add_another": "no"}), reverse("readme-party-hub")
    )
    hub = client.get(reverse("readme-party-hub"))
    assert [(row.title, row.status) for row in hub.context["sections"]] == [
        ("Venue", "not-started"),
        ("Guests", "complete"),
    ]
    assert hub.context["sections"][1].url == page
