"""What a run can remember about what it did outside itself.

A wizard's state is answers, and answers are re-proved from scratch on
every request. That leaves nowhere to keep the *other* kind of fact a run
accumulates: the record it opened, the case it raised, the call it made.
Nobody typed those, no form validates them, and re-deriving them means
doing them twice.

`run_started()` is where they are made and `bound_wizard.metadata` is where
they are kept. These are the four things that has to survive: a walk that
persists nothing, a re-answer, completion, and a stash round trip.
"""

from django.urls import reverse
import pytest

from gandalf.driver import RunDriver
from gandalf.testing import stored_runs
from tests.testapp.views import (
    OPENED_RECORDS,
    RunMetadataWizardViewSet,
    SEEN_RECORDS,
)


class _Session(dict):
    """As much of a session as a session-backed storage needs: a place to
    put a key, and a flag saying it moved."""

    modified = False


@pytest.fixture(autouse=True)
def _clean_records():
    OPENED_RECORDS.clear()
    SEEN_RECORDS.clear()
    yield
    OPENED_RECORDS.clear()
    SEEN_RECORDS.clear()


def test_a_run_opens_its_record_once_and_reads_it_back_on_every_request(client):
    client.get(reverse("run-metadata-wizard"))
    run_id = next(iter(stored_runs(client)))
    step_url = reverse("run-metadata-wizard-step", args=[run_id, "second"])

    # Three requests that each replay the first answer and persist nothing
    # at the second step.
    client.post(
        reverse("run-metadata-wizard-step", args=[run_id, "first"]), {"name": "Ada"}
    )
    client.get(step_url)
    client.get(step_url)

    # One record, however many times the wizard was walked.
    assert OPENED_RECORDS == ["record-1"]
    # And every dispatch of the step could see it — which is the whole
    # point, since a GET never persists anything the walk produces.
    assert SEEN_RECORDS == ["record-1", "record-1"]


def test_a_completed_run_still_names_the_record_it_opened(client):
    client.get(reverse("run-metadata-wizard"))
    run_id = next(iter(stored_runs(client)))

    client.post(
        reverse("run-metadata-wizard-step", args=[run_id, "first"]), {"name": "Ada"}
    )
    response = client.post(
        reverse("run-metadata-wizard-step", args=[run_id, "second"]),
        {"email": "ada@example.com"},
    )

    # `done()` read it out of the bag, not out of the answers.
    assert response.content == b"completed record-1 recording 1"
    # And the tombstone kept it: the answers are gone, the record is not.
    run_data = stored_runs(client)[run_id]
    assert run_data["completed"] is True
    assert "state" not in run_data
    assert run_data["meta"] == {
        "run": {"record_id": "record-1"},
        # Rewritten by the walk `keep_readable()` takes after `done()`, which
        # is why a step's own metadata writes have to be idempotent.
        "steps": {"second": {"drafted": True}},
    }


def test_re_answering_a_step_does_not_open_a_second_record(client):
    client.get(reverse("run-metadata-wizard"))
    run_id = next(iter(stored_runs(client)))
    first_url = reverse("run-metadata-wizard-step", args=[run_id, "first"])

    client.post(first_url, {"name": "Ada"})
    client.post(first_url, {"name": "Grace"})

    assert OPENED_RECORDS == ["record-1"]


def test_a_second_run_opens_a_second_record(client):
    client.get(reverse("run-metadata-wizard"))
    client.get(reverse("run-metadata-wizard"))

    assert OPENED_RECORDS == ["record-1", "record-2"]


def test_a_driven_run_starts_the_same_way_a_browsed_one_does():
    driver = RunDriver.begin(RunMetadataWizardViewSet, may_finish=True)

    assert OPENED_RECORDS == ["record-1"]
    assert driver.metadata["record_id"] == "record-1"


def test_a_driver_can_record_what_it_did_for_the_run_to_read():
    driver = RunDriver.begin(RunMetadataWizardViewSet, may_finish=True)

    driver.metadata["reviewed_by"] = "ops"
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})

    # Still there after two placements, which rewrite the state list whole.
    assert dict(driver.metadata) == {
        "record_id": "record-1",
        "pending": True,
        "reviewed_by": "ops",
    }


def test_a_stash_carries_the_record_and_reopening_does_not_open_another(rf):
    request = rf.get("/")
    request.session = _Session()

    driver = RunDriver.begin(RunMetadataWizardViewSet, may_finish=True)
    driver.submit({"name": "Ada"})
    payload = driver.bound_wizard.stash()

    assert payload["meta"]["run"] == {"record_id": "record-1", "pending": True}

    reopened = RunMetadataWizardViewSet.reopen(request, payload)

    # A resurrected run is a continuation: the record came back with the
    # answers, so `run_started()` must not fire and raise a second one.
    assert OPENED_RECORDS == ["record-1"]
    assert reopened.metadata["record_id"] == "record-1"


def test_a_step_can_keep_its_own_note_without_treading_on_the_runs():
    driver = RunDriver.begin(RunMetadataWizardViewSet, may_finish=True)

    driver.metadata["record_id"] = "record-1"
    driver.metadata.for_step("first")["record_id"] = "line-item-7"
    driver.metadata.for_step("second")["record_id"] = "line-item-8"

    assert driver.metadata["record_id"] == "record-1"
    assert driver.metadata.for_step("first")["record_id"] == "line-item-7"
    assert driver.metadata.for_step("second")["record_id"] == "line-item-8"
