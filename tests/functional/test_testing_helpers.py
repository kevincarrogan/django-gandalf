from http import HTTPStatus

from django.urls import reverse
import pytest
from pytest_django.asserts import assertContains, assertTemplateUsed

from gandalf.testing import (
    RunDiscoveryError,
    seed_collection_item,
    seed_run,
    seed_stash,
    stored_collection_items,
    stored_run,
    stored_runs,
    stored_stash,
    stored_stashes,
)
from tests.testapp.forms import FirstStepForm, SecondStepForm

SEEDED_RUN_ID = "11111111-1111-1111-1111-111111111111"


def test_start_returns_the_freshly_created_run(client, wizard_driver):
    driver = wizard_driver("linear-wizard")

    run = driver.start()

    assert run.run_id in stored_runs(client)
    assert run.data == {}
    assert run.state == []
    assert not run.is_completed
    assert run.url == reverse("linear-wizard-run", kwargs={"run_id": run.run_id})
    assert run.step_url("first") == reverse(
        "linear-wizard-step",
        kwargs={"run_id": run.run_id, "gandalf_step": "first"},
    )


def test_start_discovers_the_new_run_among_existing_runs(client, wizard_driver):
    driver = wizard_driver("linear-wizard")
    first_run = driver.start()

    second_run = driver.start()

    assert second_run.run_id != first_run.run_id
    assert set(stored_runs(client)) == {first_run.run_id, second_run.run_id}


def test_only_run_returns_the_sessions_single_run(wizard_driver):
    driver = wizard_driver("linear-wizard")
    started = driver.start()

    assert driver.only_run().run_id == started.run_id


def test_only_run_raises_before_any_run_starts(wizard_driver):
    driver = wizard_driver("linear-wizard")

    with pytest.raises(RunDiscoveryError):
        driver.only_run()


def test_only_run_raises_when_the_session_holds_several_runs(wizard_driver):
    driver = wizard_driver("linear-wizard")
    driver.start()
    driver.start()

    with pytest.raises(RunDiscoveryError):
        driver.only_run()


def test_new_run_ignores_known_runs_given_as_runs_or_ids(wizard_driver):
    driver = wizard_driver("linear-wizard")
    known = driver.start()
    fresh = driver.start()

    assert driver.new_run(known).run_id == fresh.run_id
    assert driver.new_run(known.run_id).run_id == fresh.run_id


def test_new_run_raises_when_no_run_is_new(wizard_driver):
    driver = wizard_driver("linear-wizard")
    only = driver.start()

    with pytest.raises(RunDiscoveryError):
        driver.new_run(only)


def test_new_run_raises_when_several_runs_are_new(wizard_driver):
    driver = wizard_driver("linear-wizard")
    driver.start()
    driver.start()

    with pytest.raises(RunDiscoveryError):
        driver.new_run()


def test_drive_runs_the_wizard_to_completion(wizard_driver):
    response, run = wizard_driver("done-linear-wizard").drive(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"
    assert run.is_completed
    assert run.data == {"completed": True}
    assert run.state == []


def test_post_step_returns_the_advance_redirect_by_default(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    response = run.post_step("first", {"name": "Ada"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("second")
    assert run.state == [{"step": {"name": "Ada"}}]


def test_post_step_follows_to_the_rendered_next_step(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}


def test_post_steps_returns_the_last_followed_response(wizard_driver):
    run = wizard_driver("done-linear-wizard").start()

    response = run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"


def test_get_redirects_to_the_cursor_step(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    response = run.get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("first")


def test_post_without_a_step_redirects_to_the_cursor_step(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    response = run.post()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("first")


def test_get_step_renders_an_answered_step_for_editing(wizard_driver):
    run = wizard_driver("linear-wizard").start()
    run.post_step("first", {"name": "Ada"})

    response = run.get_step("first")

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, 'value="Ada"')


def test_url_kwargs_thread_through_start_run_and_step_urls(wizard_driver):
    driver = wizard_driver("org-scoped-wizard", org="acme")

    run = driver.start()

    assert driver.start_url == reverse("org-scoped-wizard", kwargs={"org": "acme"})
    assert run.url == reverse(
        "org-scoped-wizard-run",
        kwargs={"org": "acme", "run_id": run.run_id},
    )
    assert run.step_url("first") == reverse(
        "org-scoped-wizard-step",
        kwargs={"org": "acme", "run_id": run.run_id, "gandalf_step": "first"},
    )


def test_drive_completes_a_wizard_mounted_with_url_kwargs(wizard_driver):
    response, run = wizard_driver("org-scoped-wizard", org="acme").drive(
        [
            ("first", {"name": "Ada"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run.run_id}".encode()


def test_seed_state_is_visible_to_the_next_request(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    run.seed_state([{"step": {"name": "Ada"}}])

    assert run.state == [{"step": {"name": "Ada"}}]
    response = run.get()
    assert response["Location"] == run.step_url("second")


def test_seed_run_creates_the_runs_mapping_for_a_fresh_session(client, wizard_driver):
    seed_run(client, SEEDED_RUN_ID, {"state": [{"step": {"name": "Ada"}}]})

    assert stored_run(client, SEEDED_RUN_ID) == {
        "state": [{"step": {"name": "Ada"}}],
    }
    run = wizard_driver("linear-wizard").run(SEEDED_RUN_ID)
    response = run.get()
    assert response["Location"] == run.step_url("second")


def test_stored_runs_is_empty_before_any_wizard_request(client):
    assert stored_runs(client) == {}


def test_stored_run_raises_for_a_run_the_session_does_not_hold(client):
    with pytest.raises(KeyError):
        stored_run(client, SEEDED_RUN_ID)


def test_completing_a_stashing_wizard_exposes_the_stored_payload(client, wizard_driver):
    response, run = wizard_driver("stashing-wizard").drive(
        [
            ("first", {"name": "Ada"}),
            ("photo", {"label": "Holiday"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"stashed Ada"
    payload = stored_stash(client, "contact")
    assert payload["label"] == "contact"
    assert payload["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"label": "Holiday"}},
    ]


def test_seed_stash_is_visible_to_later_reads(client):
    seed_stash(client, "contact", {"note": "hand-built"})

    assert stored_stash(client, "contact") == {"note": "hand-built"}
    assert stored_stashes(client) == {"contact": {"note": "hand-built"}}


def test_stored_stashes_is_empty_without_stashes(client):
    assert stored_stashes(client) == {}


def test_stored_stash_raises_for_an_unknown_key(client):
    with pytest.raises(KeyError):
        stored_stash(client, "contact")


def test_stored_collection_items_is_empty_before_anything_is_added(client):
    """A collection nobody has touched has no registry at all, which is not
    the same as an error."""
    assert stored_collection_items(client, "guests") == []


def test_a_seeded_item_is_listed_in_the_order_it_was_seeded(client):
    seed_collection_item(client, "guests", "11111111-1111-1111-1111-111111111111")
    seed_collection_item(
        client, "guests", "22222222-2222-2222-2222-222222222222", title="Ada"
    )

    assert stored_collection_items(client, "guests") == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    assert client.get("/party-guests/").context["collection"].rows[1].title == "Ada"
