"""A whole journey over HTTP: the README's grant application, start to
submit.

A journey is what a hub's members add up to. The load-bearing claims here
are the ones a single hub cannot make: two journeys in one session never see
each other; a member that does not apply yet is not there, while one that
waits on another is there but locked; what a member decided reaches the
rest of the journey without a walk; and submitting is a thing that happens
exactly once, after which nothing can be re-opened.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from gandalf.context import WizardContext
from gandalf.tasklists import BLOCKED, COMPLETE, NOT_STARTED
from gandalf.storage import SessionJourneyStore
from gandalf.testing import (
    seed_journey_complete,
    seed_journey_data,
    seed_section_stash,
    stored_journey,
    stored_journey_data,
    stored_section_run,
    stored_section_stashes,
)
from tests.testapp.models import Application
from tests.testapp.readme import ch14_journey


pytestmark = pytest.mark.django_db


def _start(client, applying_as="individual"):
    """Answer the setup wizard and return the journey it minted."""
    response = client.get(reverse("readme-apply-start"), follow=True)
    run_url = response.redirect_chain[-1][0]
    response = client.post(run_url, {"applying_as": applying_as})
    hub_url = response["Location"]
    return hub_url.rstrip("/").rsplit("/", 1)[-1]


def _hub(journey):
    return reverse("readme-apply", kwargs={"journey": journey})


def _door(journey, member, hub="readme-apply"):
    return reverse(f"{hub}-entry", kwargs={"journey": journey, "entry": member})


def _supporting(journey):
    return reverse("readme-apply-supporting", kwargs={"journey": journey})


def _statuses(client, journey, hub="readme-apply"):
    response = client.get(reverse(hub, kwargs={"journey": journey}))
    return {row.key: row.status for row in response.context["tasklist"].rows}


def _finish(client, journey, member, url_name, steps, hub="readme-apply"):
    """Enter a member from its hub and drive it to its end."""
    client.get(_door(journey, member, hub), follow=True)
    key = member if hub == "readme-apply" else f"supporting:{member}"
    run_id = stored_section_run(client, key, journey=journey)
    response = None
    for step, data in steps:
        response = client.post(
            reverse(
                f"{url_name}-step",
                kwargs={"journey": journey, "run_id": run_id, "gandalf_step": step},
            ),
            data,
        )
    return response


CONTACT = [
    ("name", {"full_name": "Ada"}),
    ("email", {"email": "ada@example.com"}),
    ("review", {}),
]


def _finish_contact(client, journey):
    return _finish(client, journey, "contact", "readme-apply-contact", CONTACT)


def _finish_project(client, journey, amount):
    return _finish(
        client,
        journey,
        "project",
        "readme-apply-project",
        [
            ("project", {"title": "Boathouse roof", "amount": str(amount)}),
            ("review", {}),
        ],
    )


def _finish_referees(client, journey):
    return _finish(
        client,
        journey,
        "referees",
        "readme-apply-supporting-referees",
        [("referee", {"referee_name": "Grace", "referee_email": "grace@example.com"})],
        hub="readme-apply-supporting",
    )


def _finish_documents(client, journey):
    return _finish(
        client,
        journey,
        "documents",
        "readme-apply-supporting-documents",
        [("document", {"document": SimpleUploadedFile("constitution.pdf", b"bytes")})],
        hub="readme-apply-supporting",
    )


def _finish_budget(client, journey):
    page = reverse("readme-apply-budget", kwargs={"journey": journey})
    step_url = client.post(page, {"add_another": "yes"})["Location"]
    client.post(step_url, {"item": "Paint", "cost": "120"})
    review_url = client.get(page).context["items"].rows[0].url
    client.post(client.get(review_url)["Location"], {})
    return client.post(page, {"add_another": "no"})


# --- minting ---------------------------------------------------------------


def test_the_setup_wizard_mints_a_journey_and_lands_on_its_hub(client):
    journey = _start(client, "organisation")

    response = client.get(_hub(journey))

    assert response.status_code == HTTPStatus.OK
    # The setup answers are the journey's first member, already complete,
    # and the answer the journey turns on is in its data.
    assert _statuses(client, journey)["setup"] == COMPLETE
    assert stored_journey_data(client, journey) == {
        "journey": {"applying_as": "organisation"}
    }


def test_two_journeys_in_one_session_never_see_each_other(client):
    first = _start(client)
    second = _start(client)
    _finish_contact(client, first)

    assert first != second
    assert _statuses(client, first)["contact"] == COMPLETE
    assert _statuses(client, second)["contact"] == NOT_STARTED
    assert set(stored_section_stashes(client, second)) == {"setup"}


# --- hidden and locked -----------------------------------------------------


def test_a_member_that_does_not_apply_is_not_on_the_page(client):
    journey = _start(client, "individual")

    assert "match_funding" not in _statuses(client, journey)
    assertContains(client.get(_hub(journey)), "of 5 sections")
    nested = _statuses(client, journey, "readme-apply-supporting")
    assert "documents" not in nested
    response = client.get(_supporting(journey))
    assertNotContains(response, "Governing document")
    assertContains(response, "of 1 section")


def test_a_member_that_applies_from_the_start_is_listed(client):
    """`hidden()` on a member two hubs down reads what the setup member
    wrote at the root: one journey, one record."""
    journey = _start(client, "organisation")

    nested = _statuses(client, journey, "readme-apply-supporting")

    assert nested["documents"] == NOT_STARTED
    assertContains(client.get(_supporting(journey)), "of 2 sections")


def test_a_hidden_members_door_is_refused(client):
    journey = _start(client, "individual")

    response = client.get(_door(journey, "documents", "readme-apply-supporting"))

    assertRedirects(response, _supporting(journey))
    assert stored_section_run(client, "supporting:documents", journey=journey) is None


def test_a_member_appears_once_another_members_answer_reveals_it(client):
    journey = _start(client)

    _finish_project(client, journey, 25_000)

    assert _statuses(client, journey)["match_funding"] == NOT_STARTED
    assert stored_journey_data(client, journey)["journey"]["amount"] == 25_000


def test_a_member_disappears_again_when_the_answer_is_withdrawn(client):
    journey = _start(client)
    _finish_project(client, journey, 25_000)
    assert "match_funding" in _statuses(client, journey)

    # Re-open the project and ask for less.
    _finish_project(client, journey, 5_000)

    assert "match_funding" not in _statuses(client, journey)


def test_a_member_waiting_on_another_is_listed_but_cannot_start(client):
    journey = _start(client)

    response = client.get(_supporting(journey))

    assert _statuses(client, journey, "readme-apply-supporting")["referees"] == BLOCKED
    assertContains(response, "Cannot start yet")
    door = _door(journey, "referees", "readme-apply-supporting")
    assertRedirects(client.get(door), _supporting(journey))


def test_a_locked_member_unlocks_when_the_one_it_waits_on_finishes(client):
    """`blocked()` reads `contact` — a root key — from inside a nested hub."""
    journey = _start(client)

    _finish_contact(client, journey)

    nested = _statuses(client, journey, "readme-apply-supporting")
    assert nested["referees"] == NOT_STARTED
    response = client.get(_door(journey, "referees", "readme-apply-supporting"))
    assert response.status_code == HTTPStatus.FOUND
    assert f"/readme/apply/{journey}/supporting/referees/" in response["Location"]


# --- a hub under the journey's hub -------------------------------------------


def test_a_nested_hubs_row_reads_its_own_rows(client):
    """The parent never reads a stash for a hub: the row's status is the
    nested hub's, derived from its members the same way its page derives
    it."""
    journey = _start(client)
    assert _statuses(client, journey)["supporting"] == NOT_STARTED

    _finish_contact(client, journey)
    assert _statuses(client, journey)["supporting"] == NOT_STARTED

    _finish_referees(client, journey)

    assert _statuses(client, journey)["supporting"] == COMPLETE
    assert stored_section_stashes(client, journey)["supporting:referees"]["label"] == (
        "supporting:referees"
    )


def test_a_nested_hubs_row_and_door_both_land_on_its_page(client):
    journey = _start(client)

    response = client.get(_hub(journey))
    rows = {row.key: row for row in response.context["tasklist"].rows}

    assert rows["supporting"].url == _supporting(journey)
    # A nested hub's segment under its parent *is* its page.
    assert _door(journey, "supporting") == _supporting(journey)
    assert client.get(_door(journey, "supporting")).status_code == HTTPStatus.OK


def test_a_nested_hubs_submit_returns_to_the_parent_and_tombstones_nothing(client):
    journey = _start(client)
    _finish_contact(client, journey)
    assertRedirects(client.post(_supporting(journey)), _supporting(journey))
    _finish_referees(client, journey)

    response = client.post(_supporting(journey))

    assertRedirects(response, _hub(journey))
    assert not stored_journey(client, journey).get("completed")
    assert _statuses(client, journey, "readme-apply-supporting")["referees"] == COMPLETE


# --- a collection under the journey -----------------------------------------


def test_the_budget_is_kept_under_the_journey(client):
    first = _start(client)
    second = _start(client)

    _finish_budget(client, first)

    assert _statuses(client, first)["budget"] == COMPLETE
    assert _statuses(client, second)["budget"] == NOT_STARTED
    page = reverse("readme-apply-budget", kwargs={"journey": second})
    assertContains(client.get(page), "You have not added any budget lines")


def test_a_finished_budget_line_returns_to_the_journeys_budget_page(client):
    journey = _start(client)
    page = reverse("readme-apply-budget", kwargs={"journey": journey})
    step_url = client.post(page, {"add_another": "yes"})["Location"]

    response = client.post(step_url, {"item": "Paint", "cost": "120"}, follow=True)
    response = client.post(response.redirect_chain[-1][0], {})

    assertRedirects(response, page)


# --- submitting ------------------------------------------------------------


def _complete_everything(client, journey):
    _finish_contact(client, journey)
    _finish_project(client, journey, 5_000)
    _finish_referees(client, journey)
    _finish_budget(client, journey)


def test_the_submit_button_appears_only_once_every_member_is_complete(client):
    journey = _start(client)
    assertNotContains(client.get(_hub(journey)), "Submit application")

    _complete_everything(client, journey)

    response = client.get(_hub(journey))
    assert response.context["tasklist"].is_complete
    assertContains(response, "Submit application")


def test_an_organisation_has_to_upload_its_document_too(client, isolated_media_root):
    journey = _start(client, "organisation")
    _complete_everything(client, journey)
    assert not client.get(_hub(journey)).context["tasklist"].is_complete

    _finish_documents(client, journey)

    assert client.get(_hub(journey)).context["tasklist"].is_complete


def test_submitting_early_is_refused(client):
    journey = _start(client)

    response = client.post(_hub(journey))

    assertRedirects(response, _hub(journey))
    assert not stored_journey(client, journey).get("completed")


def test_submitting_does_the_work_once_and_tombstones_the_journey(client):
    journey = _start(client)
    _complete_everything(client, journey)

    response = client.post(_hub(journey), follow=True)

    assert response.status_code == HTTPStatus.OK
    application = Application.objects.get()
    assertContains(response, "Application submitted")
    assertContains(response, application.reference)
    assert (application.submitted, application.email) == (True, "ada@example.com")
    record = stored_journey(client, journey)
    assert record["completed"] is True
    assert "stashes" not in record
    assert "runs" not in record
    assert "collections" not in record


def test_a_submitted_journey_refuses_every_way_back_in(client):
    journey = _start(client)
    _complete_everything(client, journey)
    client.post(_hub(journey))

    # The hub is the done page now, the door leads there, the budget page
    # leads there, and a member's own wizard sends a bookmarked URL back.
    assertContains(client.get(_hub(journey)), "Application submitted")
    assertContains(client.get(_door(journey, "contact")), "Application submitted")
    budget = reverse("readme-apply-budget", kwargs={"journey": journey})
    assertRedirects(client.get(budget), _hub(journey), target_status_code=HTTPStatus.OK)
    # A member's bare URL is its door, so it answers as the hub does; a
    # bookmarked run URL inside the member still sends the user back.
    response = client.get(reverse("readme-apply-contact", kwargs={"journey": journey}))
    assertContains(response, "Application submitted")
    run = "11111111-1111-1111-1111-111111111111"
    response = client.get(
        reverse("readme-apply-contact-run", kwargs={"journey": journey, "run_id": run})
    )
    assertRedirects(response, _hub(journey), target_status_code=HTTPStatus.OK)
    # A nested hub sends the user up, and so do its members' doors.
    assertRedirects(
        client.get(_supporting(journey)),
        _hub(journey),
        target_status_code=HTTPStatus.OK,
    )
    response = client.get(
        reverse("readme-apply-supporting-referees", kwargs={"journey": journey})
    )
    assertRedirects(response, _hub(journey), target_status_code=HTTPStatus.OK)


def test_submitting_one_journey_leaves_another_untouched(client):
    first = _start(client)
    second = _start(client)
    _complete_everything(client, first)

    client.post(_hub(first))

    assert stored_journey(client, first)["completed"] is True
    assert _statuses(client, second)["setup"] == COMPLETE
    assert not stored_journey(client, second).get("completed")


# --- watching it (chapter 15) ------------------------------------------------


def test_an_observer_counts_the_answers_applicants_get_wrong(client):
    ch14_journey.rejections.clear()
    response = client.get(reverse("readme-apply-start"), follow=True)
    run_url = response.redirect_chain[-1][0]

    client.post(run_url, {"applying_as": "a-collective"})
    client.post(run_url, {"applying_as": "individual"})

    # One event per placement: the rejected answer, and not the replays of
    # the accepted one on the requests that followed it.
    assert ch14_journey.rejections == ["applying-as"]


# --- the machinery, on a hub with nothing to say ---------------------------


def _submit_hub(journey):
    return reverse("submit-hub", kwargs={"journey": journey})


def _submit_everything(client, journey):
    for member, url_name, data in [
        ("first", "submit-hub-first", {"name": "Ada"}),
        ("second", "submit-hub-second", {"name": "Grace"}),
    ]:
        client.get(
            reverse("submit-hub-entry", kwargs={"journey": journey, "entry": member}),
            follow=True,
        )
        run_id = stored_section_run(client, member, journey=journey)
        client.post(
            reverse(
                f"{url_name}-step",
                kwargs={"journey": journey, "run_id": run_id, "gandalf_step": "first"},
            ),
            data,
        )


def test_a_journey_that_decided_nothing_leaves_a_bare_tombstone(client):
    _submit_everything(client, "app-1")

    response = client.post(_submit_hub("app-1"))

    assert response.content == b"submitted app-1"
    assert stored_journey(client, "app-1") == {"completed": True}


def test_a_submitted_journey_is_gone_until_the_hub_says_otherwise(client):
    """The default `submitted()` is a 404: the library cannot know
    what a submitted journey looks like."""
    _submit_everything(client, "app-1")
    client.post(_submit_hub("app-1"))

    assert client.get(_submit_hub("app-1")).status_code == HTTPStatus.NOT_FOUND


def test_only_the_most_recent_completed_journeys_are_kept(client):
    """A tombstone keeps the journey's data, so a session cannot hold them
    without bound. The oldest go first; a journey in progress never does."""
    _submit_everything(client, "app-1")
    client.post(_submit_hub("app-1"))
    _submit_everything(client, "app-2")
    _submit_everything(client, "app-3")

    client.post(_submit_hub("app-2"))

    assert stored_journey(client, "app-1") == {}
    assert stored_journey(client, "app-2") == {"completed": True}
    assert stored_section_run(client, "first", journey="app-3") is None
    assert set(stored_section_stashes(client, "app-3")) == {"first", "second"}


def test_a_post_to_a_door_submits_nothing(client):
    _submit_everything(client, "app-1")

    response = client.post(
        reverse("submit-hub-entry", kwargs={"journey": "app-1", "entry": "first"})
    )

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert not stored_journey(client, "app-1").get("completed")


def test_a_hub_with_nothing_to_do_at_submit_is_misconfigured(client):
    """Chapter 11's task list has no `journey_done()`: a complete hub can be
    submitted, and the library refuses to pretend that meant something."""
    for key in ("contact", "address"):
        seed_section_stash(client, key, {"version": 1, "label": key, "state": []})

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        client.post(reverse("readme-hub"))


# --- arranging a journey from a test ----------------------------------------


def test_a_seeded_answer_reveals_a_member_without_driving_the_wizard(client):
    journey = _start(client)

    seed_journey_data(client, {"amount": 20_000}, journey=journey)

    assert "match_funding" in _statuses(client, journey)
    assert stored_journey_data(client, journey)["journey"] == {
        "applying_as": "individual",
        "amount": 20_000,
    }


def test_a_seeded_tombstone_reads_as_submitted(client):
    journey = _start(client)
    seed_journey_data(client, {"reference": "GF-SEEDED"}, journey=journey)

    seed_journey_complete(client, journey=journey)

    assertContains(client.get(_hub(journey)), "GF-SEEDED")
    assert "stashes" not in stored_journey(client, journey)


def test_a_seeded_tombstone_with_nothing_decided_is_the_bare_one(client):
    seed_journey_complete(client, journey="app-9")

    assert stored_journey(client, "app-9") == {"completed": True}
    assert client.get(_submit_hub("app-9")).status_code == HTTPStatus.NOT_FOUND


def test_the_stash_keys_are_the_finished_members(client):
    journey = _start(client)
    _finish_contact(client, journey)
    _finish_project(client, journey, 5_000)

    store = SessionJourneyStore(WizardContext(session=client.session), journey)

    assert store.keys() == ["setup", "contact", "project"]
