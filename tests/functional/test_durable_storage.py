"""Storage that outlives a session, driven end to end.

Gandalf ships no durable backend — `storage_class` and `section_store_class`
are the seams a project swaps. This suite is the proof that they are
sufficient: `tests/testapp/durable.py` implements both protocols against
ordinary models, and a whole hub journey runs over them with the session
holding nothing but the login.

The point the tests make together is that *nothing else changes*. The wizard,
the walk, the escapes and the hub are untouched; only where the bytes live
differs.
"""

from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from gandalf.sections import COMPLETE, INCOMPLETE, NOT_STARTED
from gandalf.storage import RunNotFound
from tests.testapp.durable import ModelStorage
from tests.testapp.models import SectionRecord, WizardRun


pytestmark = pytest.mark.django_db

HUB_URL = "/durable-hub/"
DOOR_URL = "/durable-hub/durable/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ada", password="secret")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def _step_url(run_id, step):
    return reverse(
        "durable-section-step", kwargs={"run_id": run_id, "gandalf_step": step}
    )


# --- the seam --------------------------------------------------------------


def test_a_run_and_its_answers_live_in_the_database_not_the_session(logged_in):
    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()

    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)

    run.refresh_from_db()
    assert run.state == [{"step": {"name": "Ada"}}]
    assert "gandalf_runs" not in logged_in.session


def test_the_hubs_bookkeeping_lives_in_the_database_too(logged_in):
    logged_in.get(DOOR_URL, follow=True)

    record = SectionRecord.objects.get()
    assert record.key == "durable"
    assert record.run_id == WizardRun.objects.get().pk
    assert "gandalf_section_runs" not in logged_in.session


def test_a_whole_section_completes_over_model_storage(logged_in):
    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()

    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)
    response = logged_in.post(_step_url(run.pk, "second"), {"email": "ada@example.com"})

    assertRedirects(response, HUB_URL)
    run.refresh_from_db()
    # Completion tombstones the run and discards its state, exactly as the
    # session backend does — the stash is what survives.
    assert (run.completed, run.state) == (True, [])
    record = SectionRecord.objects.get()
    assert record.run_id is None
    assert record.stash["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_the_hub_reads_every_status_off_model_storage(logged_in):
    assert _status(logged_in) == NOT_STARTED

    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()
    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)
    assert _status(logged_in) == INCOMPLETE

    logged_in.post(_step_url(run.pk, "second"), {"email": "ada@example.com"})
    assert _status(logged_in) == COMPLETE


def _status(client):
    (row,) = client.get(HUB_URL).context["sections"]
    return row.status


# --- what durability actually buys ------------------------------------------


def test_a_half_answered_section_survives_the_session_being_lost(logged_in, user):
    """The whole point: come back tomorrow, on a new session, and the section
    is still where you left it."""
    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()
    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)

    logged_in.logout()
    logged_in.force_login(user)

    response = logged_in.get(HUB_URL)
    assert response.context["sections"][0].status == INCOMPLETE
    assertRedirects(logged_in.get(DOOR_URL), _step_url(run.pk, "second"))


def test_a_completed_section_reopens_from_its_stored_stash(logged_in, user):
    logged_in.get(DOOR_URL, follow=True)
    original = WizardRun.objects.get()
    logged_in.post(_step_url(original.pk, "first"), {"name": "Ada"}, follow=True)
    logged_in.post(_step_url(original.pk, "second"), {"email": "ada@example.com"})

    logged_in.logout()
    logged_in.force_login(user)
    response = logged_in.get(DOOR_URL, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="Ada"')
    # A fresh run seeded from the stash, beside the original's tombstone —
    # so the once-per-run `done()` guarantee is untouched.
    reopened = WizardRun.objects.exclude(pk=original.pk).get()
    assert reopened.state == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]
    original.refresh_from_db()
    assert original.completed is True


def test_one_users_run_is_not_another_users_to_resume(client, user, logged_in):
    """`retrieve_run` raising `RunNotFound` is the whole authorisation model,
    and scoping the queryset by owner is what implements it."""
    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()
    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)

    intruder = User.objects.create_user("grace", password="secret")
    client.force_login(intruder)
    response = client.get(_step_url(run.pk, "second"))

    # Not this session's run, so the wizard answers exactly as it would for a
    # run that never existed: back to the start.
    assertRedirects(response, "/durable-section/", fetch_redirect_response=False)
    assert client.get(HUB_URL).context["sections"][0].status == NOT_STARTED


# --- the storage protocol's own contracts ------------------------------------


def test_model_storage_answers_an_unknown_run_as_not_found(rf, user):
    request = rf.get("/")
    request.user = user
    storage = ModelStorage(request)

    with pytest.raises(RunNotFound):
        storage.retrieve_run("00000000-0000-0000-0000-000000000000")
    with pytest.raises(RunNotFound):
        storage.retrieve_run("not-a-uuid")


def test_model_storage_leaves_a_completed_run_addressable_and_empty(rf, user):
    request = rf.get("/")
    request.user = user
    storage = ModelStorage(request)
    run_id = storage.initialise_run()
    storage.set_state(run_id, [{"step": {"name": "Ada"}}])

    storage.complete_run(run_id)
    storage.complete_run(run_id)  # idempotent

    assert storage.is_run_complete(run_id) is True
    assert storage.retrieve_run(run_id) == run_id
    assert storage.get_state(run_id) == []


def test_model_storage_forgets_a_deleted_run_entirely(rf, user):
    request = rf.get("/")
    request.user = user
    storage = ModelStorage(request)
    run_id = storage.initialise_run()

    storage.delete_run(run_id)
    storage.delete_run(run_id)  # idempotent

    with pytest.raises(RunNotFound):
        storage.retrieve_run(run_id)
