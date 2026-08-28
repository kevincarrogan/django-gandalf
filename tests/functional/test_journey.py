"""A whole journey over HTTP: the README's application example, start to
submit.

A journey is what a hub's sections add up to. The load-bearing claims here
are the ones a single hub cannot make: two journeys in one session never see
each other; a section that does not apply yet is not there, while one that
waits on another is there but locked; what a section decided reaches the
rest of the journey without a walk; and submitting is a thing that happens
exactly once, after which nothing can be re-opened.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from gandalf.context import WizardContext
from gandalf.sections import BLOCKED, COMPLETE, NOT_STARTED, Section
from gandalf.storage import SessionSectionStore
from gandalf.testing import (
    seed_journey_complete,
    seed_journey_data,
    seed_section_stash,
    stored_journey,
    stored_journey_data,
    stored_section_run,
    stored_section_stashes,
)


def _start(client, applicant_type="individual"):
    """Answer the setup wizard and return the journey it minted."""
    response = client.get(reverse("readme-apply-start"), follow=True)
    run_url = response.redirect_chain[-1][0]
    response = client.post(run_url, {"applicant_type": applicant_type})
    hub_url = response["Location"]
    return hub_url.rstrip("/").rsplit("/", 1)[-1]


def _hub(journey):
    return reverse("readme-apply-hub", kwargs={"journey": journey})


def _door(journey, section):
    return reverse(
        "readme-apply-hub-section", kwargs={"journey": journey, "section": section}
    )


def _statuses(client, journey):
    response = client.get(_hub(journey))
    return {row.key: row.status for row in response.context["hub"].rows}


def _finish(client, journey, section, url_name, steps):
    """Enter a section from the hub and drive it to its end."""
    client.get(_door(journey, section), follow=True)
    run_id = stored_section_run(client, section, journey=journey)
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


# --- minting ---------------------------------------------------------------


def test_the_setup_wizard_mints_a_journey_and_lands_on_its_hub(client):
    journey = _start(client, "business")

    response = client.get(_hub(journey))

    assert response.status_code == HTTPStatus.OK
    # The setup answers are the journey's first section, already complete,
    # and the answer the journey turns on is in its data.
    assert _statuses(client, journey)["setup"] == COMPLETE
    assert stored_journey_data(client, journey) == {
        "journey": {"applicant_type": "business"}
    }


def test_two_journeys_in_one_session_never_see_each_other(client):
    first = _start(client)
    second = _start(client)
    _finish(
        client,
        first,
        "contact",
        "readme-apply-contact",
        [("name", {"name": "Ada"}), ("email", {"email": "ada@example.com"})],
    )

    assert first != second
    assert _statuses(client, first)["contact"] == COMPLETE
    assert _statuses(client, second)["contact"] == NOT_STARTED
    assert set(stored_section_stashes(client, second)) == {"setup"}


# --- hidden and locked -----------------------------------------------------


def test_a_section_that_does_not_apply_yet_is_not_on_the_page(client):
    journey = _start(client)

    statuses = _statuses(client, journey)

    assert "employer" not in statuses
    response = client.get(_hub(journey))
    assertNotContains(response, "Employer")
    assertContains(response, "of 4 sections")


def test_a_hidden_sections_door_is_refused(client):
    journey = _start(client)

    response = client.get(_door(journey, "employer"))

    assertRedirects(response, _hub(journey))
    assert stored_section_run(client, "employer", journey=journey) is None


def test_a_section_appears_once_another_sections_answer_reveals_it(client):
    journey = _start(client)

    _finish(
        client,
        journey,
        "employment",
        "readme-apply-employment",
        [("status", {"status": "employed"})],
    )

    statuses = _statuses(client, journey)
    assert statuses["employer"] == NOT_STARTED
    assertContains(client.get(_hub(journey)), "of 5 sections")
    assert stored_journey_data(client, journey)["journey"]["employment_status"] == (
        "employed"
    )


def test_a_section_disappears_again_when_the_answer_is_withdrawn(client):
    journey = _start(client)
    _finish(
        client,
        journey,
        "employment",
        "readme-apply-employment",
        [("status", {"status": "employed"})],
    )
    assert "employer" in _statuses(client, journey)

    # Re-open Employment and change the answer.
    _finish(
        client,
        journey,
        "employment",
        "readme-apply-employment",
        [("status", {"status": "unemployed"})],
    )

    assert "employer" not in _statuses(client, journey)


def test_a_section_waiting_on_another_is_listed_but_cannot_start(client):
    journey = _start(client)

    response = client.get(_hub(journey))

    assert _statuses(client, journey)["references"] == BLOCKED
    assertContains(response, "Cannot start yet")
    assertRedirects(client.get(_door(journey, "references")), _hub(journey))


def test_a_locked_section_unlocks_when_the_one_it_waits_on_finishes(client):
    journey = _start(client)

    _finish(
        client,
        journey,
        "contact",
        "readme-apply-contact",
        [("name", {"name": "Ada"}), ("email", {"email": "ada@example.com"})],
    )

    assert _statuses(client, journey)["references"] == NOT_STARTED
    response = client.get(_door(journey, "references"))
    assert response.status_code == HTTPStatus.FOUND
    assert f"/readme/apply-references/{journey}/" in response["Location"]


# --- submitting ------------------------------------------------------------


def _complete_everything(client, journey):
    _finish(
        client,
        journey,
        "contact",
        "readme-apply-contact",
        [("name", {"name": "Ada"}), ("email", {"email": "ada@example.com"})],
    )
    _finish(
        client,
        journey,
        "employment",
        "readme-apply-employment",
        [("status", {"status": "self_employed"})],
    )
    _finish(
        client,
        journey,
        "references",
        "readme-apply-references",
        [("referee", {"referee": "Grace"})],
    )


def test_the_submit_button_appears_only_once_every_section_is_complete(client):
    journey = _start(client)
    assertNotContains(client.get(_hub(journey)), "Submit application")

    _complete_everything(client, journey)

    response = client.get(_hub(journey))
    assert response.context["hub"].is_complete
    assertContains(response, "Submit application")


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
    assertContains(response, "Application submitted")
    assertContains(response, f"APP-{journey[:8].upper()}")
    record = stored_journey(client, journey)
    assert record["completed"] is True
    assert "stashes" not in record
    assert "runs" not in record


def test_a_submitted_journey_refuses_every_way_back_in(client):
    journey = _start(client)
    _complete_everything(client, journey)
    client.post(_hub(journey))

    # The hub is the done page now, the door leads there, and the section's
    # own wizard sends a bookmarked URL back to it.
    assertContains(client.get(_hub(journey)), "Application submitted")
    assertContains(client.get(_door(journey, "contact")), "Application submitted")
    response = client.get(reverse("readme-apply-contact", kwargs={"journey": journey}))
    assertRedirects(response, _hub(journey), target_status_code=HTTPStatus.OK)
    assert "stashes" not in stored_journey(client, journey)


def test_submitting_one_journey_leaves_another_untouched(client):
    first = _start(client)
    second = _start(client)
    _complete_everything(client, first)

    client.post(_hub(first))

    assert stored_journey(client, first)["completed"] is True
    assert _statuses(client, second)["setup"] == COMPLETE
    assert not stored_journey(client, second).get("completed")


# --- the machinery, on a hub with nothing to say ---------------------------


def _submit_hub(journey):
    return reverse("submit-hub", kwargs={"journey": journey})


def _submit_everything(client, journey):
    for section, url_name, data in [
        ("first", "submit-first", {"name": "Ada"}),
        ("second", "submit-second", {"name": "Grace"}),
    ]:
        client.get(
            reverse(
                "submit-hub-section", kwargs={"journey": journey, "section": section}
            ),
            follow=True,
        )
        run_id = stored_section_run(client, section, journey=journey)
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
    """The default `journey_completed()` is a 404: the library cannot know
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
        reverse("submit-hub-section", kwargs={"journey": "app-1", "section": "first"})
    )

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert not stored_journey(client, "app-1").get("completed")


def test_a_hub_with_nothing_to_do_at_submit_is_misconfigured(client):
    """The README's profile hub has no `journey_done()`: a complete hub can
    be submitted, and the library refuses to pretend that meant something."""
    for key, label in [("contact", "contact"), ("address", "address")]:
        seed_section_stash(client, key, {"version": 1, "label": label, "state": []})

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        client.post(reverse("readme-hub"))


def test_a_section_on_another_journey_than_its_hub_is_misconfigured(rf, client):
    from tests.testapp.readme_examples import (
        ApplicationHubView,
        ApplyContactSectionViewSet,
    )

    class _Astray(ApplyContactSectionViewSet):
        journey_url_kwarg = "application"

    class _Mismatched(ApplicationHubView):
        sections = [Section("contact", _Astray)]

    request = rf.get("/readme/apply/app-1/")
    request.session = client.session

    with pytest.raises(ImproperlyConfigured, match="Astray"):
        _Mismatched.as_view()(request, journey="app-1")


# --- arranging a journey from a test ----------------------------------------


def test_a_seeded_answer_reveals_a_section_without_driving_the_wizard(client):
    journey = _start(client)

    seed_journey_data(client, {"employment_status": "employed"}, journey=journey)

    assert "employer" in _statuses(client, journey)
    assert stored_journey_data(client, journey)["journey"] == {
        "applicant_type": "individual",
        "employment_status": "employed",
    }


def test_a_seeded_tombstone_reads_as_submitted(client):
    journey = _start(client)
    seed_journey_data(client, {"reference": "APP-SEEDED"}, journey=journey)

    seed_journey_complete(client, journey=journey)

    assertContains(client.get(_hub(journey)), "APP-SEEDED")
    assert "stashes" not in stored_journey(client, journey)


def test_a_seeded_tombstone_with_nothing_decided_is_the_bare_one(client):
    seed_journey_complete(client, journey="app-9")

    assert stored_journey(client, "app-9") == {"completed": True}
    assert client.get(_submit_hub("app-9")).status_code == HTTPStatus.NOT_FOUND


def test_the_stash_keys_are_the_finished_sections(client):
    journey = _start(client)
    _complete_everything(client, journey)

    store = SessionSectionStore(WizardContext(session=client.session), journey)

    assert store.keys() == ["setup", "contact", "employment", "references"]
