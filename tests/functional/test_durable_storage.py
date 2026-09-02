"""Storage that outlives a session, driven end to end.

Gandalf ships no durable backend — `storage_class` and `journey_store_class`
are the seams a project swaps. This suite is the proof that they are
sufficient: `tests/testapp/durable.py` implements both protocols against
ordinary models, and a whole page journey runs over them with the session
holding nothing but the login.

The point the tests make together is that *nothing else changes*. The wizard,
the walk, the escapes and the page are untouched; only where the bytes live
differs.
"""

from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from gandalf.context import WizardContext
from gandalf.tasklists import COMPLETE, INCOMPLETE, NOT_STARTED
from gandalf.storage import RunNotFound
from tests.testapp.durable import (
    ModelItemStore,
    ModelJourneyStore,
    ModelStorage,
)
from tests.testapp.models import (
    ItemRecord,
    ItemListRecord,
    JourneyRecord,
    SectionRecord,
    WizardRun,
)


pytestmark = pytest.mark.django_db

HUB_URL = "/durable-task-list/"
DOOR_URL = "/durable-task-list/durable/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("ada", password="secret")


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def _step_url(run_id, step):
    return reverse(
        "durable-task-list-durable-step",
        kwargs={"run_id": run_id, "gandalf_step": step},
    )


# --- the seam --------------------------------------------------------------


def test_a_run_and_its_answers_live_in_the_database_not_the_session(logged_in):
    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()

    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)

    run.refresh_from_db()
    assert run.state == [{"step": {"name": "Ada"}}]
    assert "gandalf_runs" not in logged_in.session


def test_the_pages_bookkeeping_lives_in_the_database_too(logged_in):
    logged_in.get(DOOR_URL, follow=True)

    record = SectionRecord.objects.get()
    assert record.key == "durable"
    assert record.run_id == WizardRun.objects.get().pk
    assert "gandalf_journeys" not in logged_in.session


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


def test_the_page_reads_every_status_off_model_storage(logged_in):
    assert _status(logged_in) == NOT_STARTED

    logged_in.get(DOOR_URL, follow=True)
    run = WizardRun.objects.get()
    logged_in.post(_step_url(run.pk, "first"), {"name": "Ada"}, follow=True)
    assert _status(logged_in) == INCOMPLETE

    logged_in.post(_step_url(run.pk, "second"), {"email": "ada@example.com"})
    assert _status(logged_in) == COMPLETE


def _status(client):
    (row,) = client.get(HUB_URL).context["task_list"].rows
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
    assert response.context["task_list"].rows[0].status == INCOMPLETE
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
    assertRedirects(response, DOOR_URL, fetch_redirect_response=False)
    assert client.get(HUB_URL).context["task_list"].rows[0].status == NOT_STARTED


# --- the storage protocol's own contracts ------------------------------------


def test_model_storage_answers_an_unknown_run_as_not_found(user):
    storage = ModelStorage(WizardContext(actor=user))

    with pytest.raises(RunNotFound):
        storage.retrieve_run("00000000-0000-0000-0000-000000000000")
    with pytest.raises(RunNotFound):
        storage.retrieve_run("not-a-uuid")


def test_model_storage_leaves_a_completed_run_addressable_and_empty(user):
    storage = ModelStorage(WizardContext(actor=user))
    run_id = storage.initialise_run()
    storage.set_state(run_id, [{"step": {"name": "Ada"}}])

    storage.complete_run(run_id)
    storage.complete_run(run_id)  # idempotent

    assert storage.is_run_complete(run_id) is True
    assert storage.retrieve_run(run_id) == run_id
    assert storage.get_state(run_id) == []


def test_model_storage_forgets_a_deleted_run_entirely(user):
    storage = ModelStorage(WizardContext(actor=user))
    run_id = storage.initialise_run()

    storage.delete_run(run_id)
    storage.delete_run(run_id)  # idempotent

    with pytest.raises(RunNotFound):
        storage.retrieve_run(run_id)


# --- a collection that outlives a session ------------------------------------


COLLECTION_URL = "/durable-guests/"


def _add_durable(client):
    return client.post(COLLECTION_URL, {"add_another": "yes"})["Location"]


def _complete_durable(client, name):
    response = client.post(
        _add_durable(client), {"name": name, "dietary_requirements": ""}
    )
    return client.post(response["Location"], {})


def test_a_collections_registry_lives_in_the_database_not_the_session(logged_in):
    _add_durable(logged_in)

    (record,) = ItemRecord.objects.all()
    assert record.list_key == "durable-guests"
    assert record.position == 0
    assert "gandalf_journeys" not in logged_in.session


def test_an_items_title_is_cached_in_the_database_when_it_finishes(logged_in):
    _complete_durable(logged_in, "Ada")

    assert ItemRecord.objects.get().title == "Ada"
    assert SectionRecord.objects.get().stash["label"] == "durable-guests"


def test_the_users_answer_to_add_another_lives_in_the_database(logged_in):
    _complete_durable(logged_in, "Ada")

    logged_in.post(COLLECTION_URL, {"add_another": "no"})

    assert ItemListRecord.objects.get().declared_done is True
    assert logged_in.get(COLLECTION_URL).context["items"].status == COMPLETE


def test_a_half_finished_item_survives_the_session_being_lost(logged_in, user):
    logged_in.post(_add_durable(logged_in), {"name": "Ada", "dietary_requirements": ""})

    logged_in.logout()
    logged_in.force_login(user)

    response = logged_in.get(COLLECTION_URL)
    assert [row.status for row in response.context["items"].rows] == [INCOMPLETE]
    assert [str(row.title) for row in response.context["items"].rows] == ["Guest 1"]


def test_a_finished_item_reopens_from_the_database_after_a_new_session(logged_in, user):
    _complete_durable(logged_in, "Ada")
    item_id = ItemRecord.objects.get().item_id
    logged_in.logout()
    logged_in.force_login(user)

    response = logged_in.get(
        reverse("durable-guests-item", kwargs={"item": item_id}), follow=True
    )

    assertContains(response, 'value="Ada"')


def test_removing_an_item_takes_its_row_and_its_run_out_of_the_database(logged_in):
    _complete_durable(logged_in, "Ada")
    _complete_durable(logged_in, "Grace")
    first, second = list(ItemRecord.objects.values_list("item_id", flat=True))

    logged_in.post(reverse("durable-guests-remove", kwargs={"item": first}))

    assert list(ItemRecord.objects.values_list("item_id", flat=True)) == [second]
    assert (
        SectionRecord.objects.filter(
            key=f"durable-guests:{first}", stash__isnull=False
        ).count()
        == 0
    )


def test_a_unique_constraint_settles_the_race_the_session_store_loses(logged_in):
    """Two tabs adding at once both read the same list and both append one,
    so a session-backed registry loses an item outright. A table cannot."""
    store = ModelItemStore(WizardContext(actor=User.objects.get()), "default")

    store.add_item("durable-guests", "same-id")
    store.add_item("durable-guests", "same-id")

    assert store.item_ids("durable-guests") == ["same-id"]
    assert ItemRecord.objects.count() == 1


def test_one_users_collection_is_not_another_users_to_read(logged_in, user):
    _complete_durable(logged_in, "Ada")
    intruder = User.objects.create_user("grace", password="secret")
    logged_in.force_login(intruder)

    response = logged_in.get(COLLECTION_URL)

    assert response.context["items"].is_empty


# --- the journey ------------------------------------------------------------


def test_a_journeys_metadata_lives_on_its_own_row(user):
    """The one part of a journey that survives submission — kept on a row of
    its own, written now rather than at the end of a walk."""
    store = ModelJourneyStore(WizardContext(actor=user), "app-1")

    store.metadata["applicant_type"] = "business"
    store.metadata.for_section("employment")["checked"] = True

    record = JourneyRecord.objects.get(owner=user, journey="app-1")
    assert record.meta == {
        "journey": {"applicant_type": "business"},
        "sections": {"employment": {"checked": True}},
    }
    assert (
        ModelJourneyStore(WizardContext(actor=user), "app-1").metadata["applicant_type"]
        == "business"
    )


def test_journeys_are_scoped_by_owner_and_by_journey(user, django_user_model):
    other = django_user_model.objects.create_user("grace", password="secret")
    ModelJourneyStore(WizardContext(actor=user), "app-1").put_stash("contact", {})

    assert ModelJourneyStore(WizardContext(actor=user), "app-2").keys() == []
    assert ModelJourneyStore(WizardContext(actor=other), "app-1").keys() == []


def test_completing_a_journey_deletes_its_sections_and_keeps_its_row(user):
    store = ModelItemStore(WizardContext(actor=user), "app-1")
    store.set_run("contact", None)
    store.put_stash("contact", {"state": []})
    store.add_item("guests", "a")
    store.set_declared_done("guests", True)
    store.metadata["reference"] = "APP-1"

    store.complete()

    assert store.is_complete() is True
    assert store.keys() == []
    assert store.item_ids("guests") == []
    assert store.is_declared_done("guests") is False
    assert store.metadata["reference"] == "APP-1"
    assert not SectionRecord.objects.filter(owner=user).exists()
    assert not ItemRecord.objects.filter(owner=user).exists()


def test_a_submitted_durable_journey_is_gone_from_its_page(logged_in, user):
    """The default `submitted()`: a tombstone is a 404 until the page
    says what a submitted journey looks like."""
    ModelJourneyStore(WizardContext(actor=user), "default").complete()

    assert logged_in.get(HUB_URL).status_code == HTTPStatus.NOT_FOUND
    assert logged_in.get(DOOR_URL).status_code == HTTPStatus.NOT_FOUND
