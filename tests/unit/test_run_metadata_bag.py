"""The run's metadata bag, as a mapping.

The functional suite proves what it is *for*. This proves the mechanics
that make that possible: every write reaches storage immediately, two
handles on one run agree, and the step bags cannot tread on each other or
on the run's own keys.
"""

import pytest

from gandalf.runtime import RunMetadata
from gandalf.storage import SessionStorage


class _Session(dict):
    modified = False


class _Context:
    def __init__(self):
        self.session = _Session()

    def session_changed(self):
        self.session.modified = True


@pytest.fixture
def storage():
    storage = SessionStorage(_Context())
    storage.run_id = storage.initialise_run()
    return storage


@pytest.fixture
def metadata(storage):
    return RunMetadata(storage, storage.run_id)


def test_a_new_run_has_an_empty_bag(metadata):
    assert dict(metadata) == {}
    assert len(metadata) == 0
    with pytest.raises(KeyError):
        metadata["nothing"]


def test_a_write_reaches_storage_without_anything_persisting_a_walk(storage, metadata):
    metadata["record_id"] = "abc"

    assert storage.get_run_metadata(storage.run_id) == {"run": {"record_id": "abc"}}


def test_two_handles_on_one_run_see_each_others_writes(storage, metadata):
    metadata["record_id"] = "abc"

    # The case a request actually hits: the viewset holds one, a step view
    # takes another. A cached bag would have the second one stale.
    assert RunMetadata(storage, storage.run_id)["record_id"] == "abc"


def test_a_step_bag_cannot_collide_with_the_runs_own_keys(storage, metadata):
    metadata["record_id"] = "run-level"
    metadata.for_step("billing")["record_id"] = "step-level"

    assert metadata["record_id"] == "run-level"
    assert metadata.for_step("billing")["record_id"] == "step-level"
    assert storage.get_run_metadata(storage.run_id) == {
        "run": {"record_id": "run-level"},
        "steps": {"billing": {"record_id": "step-level"}},
    }


def test_step_bags_are_addressed_from_the_root_however_they_are_reached(metadata):
    metadata.for_step("a").for_step("b")["x"] = 1

    # Not a nesting: `for_step` names a step, and a step is not inside
    # another one.
    assert metadata.for_step("b")["x"] == 1
    assert dict(metadata.for_step("a")) == {}


def test_a_step_bag_nothing_wrote_to_is_empty_rather_than_missing(metadata):
    assert dict(metadata.for_step("never-answered")) == {}


def test_deleting_a_key_that_is_not_there_leaves_storage_untouched(storage, metadata):
    metadata["kept"] = "yes"

    with pytest.raises(KeyError):
        del metadata["absent"]

    assert storage.get_run_metadata(storage.run_id) == {"run": {"kept": "yes"}}


def test_deleting_a_key_writes_through(storage, metadata):
    metadata["record_id"] = "abc"

    del metadata["record_id"]

    assert storage.get_run_metadata(storage.run_id) == {"run": {}}


def test_mutating_a_nested_value_in_place_changes_nothing(storage, metadata):
    metadata["refs"] = {"first": 1}

    metadata["refs"]["second"] = 2

    # A read hands back a deep copy, so this is refused on every backend
    # rather than landing in a session's live dict (where nothing marks the
    # session, so the middleware never saves it) and vanishing outright on
    # a durable store. Same answer in development and in production.
    assert metadata["refs"] == {"first": 1}
    assert storage.get_run_metadata(storage.run_id) == {"run": {"refs": {"first": 1}}}


def test_assigning_the_whole_value_back_is_how_a_nested_change_lands(metadata):
    metadata["refs"] = {"first": 1}

    metadata["refs"] = {**metadata["refs"], "second": 2}

    assert metadata["refs"] == {"first": 1, "second": 2}


def test_update_sets_every_key_in_a_single_write(storage, metadata):
    calls = []
    inner = storage.set_run_metadata
    storage.set_run_metadata = lambda run_id, meta: (
        calls.append(run_id),
        inner(run_id, meta),
    )[1]

    metadata.update({"a": 1}, b=2)

    # `MutableMapping` would loop over `__setitem__` — one full
    # read-modify-write of the envelope per key, which is one round trip
    # per key on a durable backend.
    assert len(calls) == 1
    assert dict(metadata) == {"a": 1, "b": 2}


def test_update_reaches_a_step_bag_like_any_other_write(metadata):
    metadata.update(record_id="abc")
    metadata.for_step("billing").update(charged=True, reference="ref-1")

    assert dict(metadata) == {"record_id": "abc"}
    assert dict(metadata.for_step("billing")) == {
        "charged": True,
        "reference": "ref-1",
    }


def test_the_bag_reads_as_a_dict(metadata):
    metadata["a"] = 1
    metadata["b"] = 2

    assert sorted(metadata) == ["a", "b"]
    assert len(metadata) == 2
    assert metadata.get("c", "fallback") == "fallback"
    assert dict(metadata) == {"a": 1, "b": 2}


def test_the_bag_shows_what_it_holds_when_printed(metadata):
    metadata["record_id"] = "abc"

    assert repr(metadata) == "RunMetadata({'record_id': 'abc'})"
