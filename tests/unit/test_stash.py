"""Unit coverage for stashing and resurrecting runs.

A stash is a caller-owned, JSON-safe payload of a run's answers — the stored
state entries wrapped in a versioned envelope with file refs stripped — taken
inside `done()` before completion tears the run down. Resurrecting seeds a
brand-new run from a payload, so the standard walk machinery replays and
re-proves every answer.
"""

import pytest

from gandalf.context import WizardContext
from gandalf.runtime import STASH_VERSION, Run, InvalidStash
from gandalf.storage import SessionStorage
from gandalf.wizard import Wizard

from tests.testapp.forms import (
    FirstStepForm,
    OptionalPhotoForm,
    ProfilePhotoForm,
    SecondStepForm,
)


class _Session(dict):
    modified = False


@pytest.fixture
def request_factory(rf):
    def build(session=None):
        request = rf.get("/wizard/")
        request.session = _Session()
        if session:
            request.session.update(session)
        return request

    return build


def _bound(request, state):
    request.session["gandalf_runs"] = {"run": {"state": state}}
    context = WizardContext.from_request(request)
    bound = Run(context, SessionStorage(context))
    bound.retrieve("run")
    return bound


def test_stash_wraps_the_stored_state_in_a_versioned_envelope(request_factory):
    state = [{"step": {"first_name": "Ada"}}, {"step": {"last_name": "Lovelace"}}]
    bound = _bound(request_factory(), state)

    payload = bound.stash()

    assert payload == {"version": STASH_VERSION, "state": state}


def test_stash_includes_a_label_only_when_given(request_factory):
    bound = _bound(request_factory(), [{"step": {"first_name": "Ada"}}])

    assert "label" not in bound.stash()
    assert bound.stash(label="contact")["label"] == "contact"


def test_stash_strips_file_refs_but_keeps_the_step_data(request_factory):
    bound = _bound(
        request_factory(),
        [
            {
                "step": {"caption": "Me"},
                "files": {"photo": {"tmp_name": "gandalf/run/photo.png"}},
            }
        ],
    )

    payload = bound.stash()

    assert payload["state"] == [{"step": {"caption": "Me"}}]


def test_stash_drops_a_csrf_token_an_earlier_version_stored(request_factory):
    """New submissions never carry one — the viewset drops it as the POST is
    read. A run that was already in flight when that landed still holds one,
    and a stash is the one thing that carries state out of the session it was
    issued for, so it is swept here too."""
    bound = _bound(
        request_factory(),
        [{"step": {"first_name": "Ada", "csrfmiddlewaretoken": "sekrit"}}],
    )

    payload = bound.stash()

    assert payload["state"] == [{"step": {"first_name": "Ada"}}]


def test_stash_keeps_what_was_recorded_about_a_placement(request_factory):
    """File refs go because the bytes do not outlive the run. Metadata is
    not a pointer to anything — it describes the answer beside it, and the
    answer survives."""
    bound = _bound(
        request_factory(),
        [
            {
                "step": {"caption": "Me"},
                "files": {"photo": {"tmp_name": "gandalf/run/photo.png"}},
                "meta": {"placed_by": "person"},
            }
        ],
    )

    payload = bound.stash()

    assert payload["state"] == [
        {"step": {"caption": "Me"}, "meta": {"placed_by": "person"}}
    ]


def test_stash_strips_file_refs_inside_active_and_dormant_branch_arms(
    request_factory,
):
    bound = _bound(
        request_factory(),
        [
            {"step": {"account_type": "business"}},
            {
                "branch": {
                    "0": [
                        {
                            "step": {"business_name": "Acme"},
                            "files": {"logo": {"tmp_name": "gandalf/run/logo.png"}},
                        }
                    ],
                    "default": [
                        {
                            "step": {"preferred_name": "Ada"},
                            "files": {"avatar": {"tmp_name": "gandalf/run/me.png"}},
                        }
                    ],
                }
            },
        ],
    )

    payload = bound.stash()

    assert payload["state"][1] == {
        "branch": {
            "0": [{"step": {"business_name": "Acme"}}],
            "default": [{"step": {"preferred_name": "Ada"}}],
        }
    }


def test_stash_strips_file_refs_inside_a_legacy_bare_list_branch_entry(
    request_factory,
):
    bound = _bound(
        request_factory(),
        [
            {
                "branch": [
                    {
                        "step": {"business_name": "Acme"},
                        "files": {"logo": {"tmp_name": "gandalf/run/logo.png"}},
                    }
                ]
            }
        ],
    )

    payload = bound.stash()

    assert payload["state"] == [{"branch": [{"step": {"business_name": "Acme"}}]}]


def test_stash_strips_file_refs_inside_an_expansion(request_factory):
    bound = _bound(
        request_factory(),
        [
            {"step": {"count": "1"}},
            {
                "expand": [
                    {
                        "step": {"name": "Ada"},
                        "files": {"photo": {"tmp_name": "gandalf/run/ada.png"}},
                    }
                ]
            },
        ],
    )

    payload = bound.stash()

    assert payload["state"][1] == {"expand": [{"step": {"name": "Ada"}}]}


def test_stash_does_not_mutate_the_stored_state(request_factory):
    state = [
        {
            "step": {"caption": "Me"},
            "files": {"photo": {"tmp_name": "gandalf/run/photo.png"}},
        },
        {"branch": {"0": [{"step": {"a": "1"}, "files": {"f": {"tmp_name": "x"}}}]}},
    ]
    bound = _bound(request_factory(), state)

    bound.stash()

    assert state[0]["files"] == {"photo": {"tmp_name": "gandalf/run/photo.png"}}
    assert state[1]["branch"]["0"][0]["files"] == {"f": {"tmp_name": "x"}}


def test_stash_keeps_interior_holes_verbatim(request_factory):
    state = [
        {"step": None},
        {"step": {"last_name": "Lovelace"}},
    ]
    bound = _bound(request_factory(), state)

    payload = bound.stash()

    assert payload["state"] == state


def _linear_wizard():
    return (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(template_name="testapp/linear_wizard.html")
    )


def _fresh_bound(request, wizard=None):
    context = WizardContext.from_request(request)
    return Run(context, SessionStorage(context), wizard=wizard)


def test_resurrect_seeds_a_fresh_run_holding_the_payload_state(request_factory):
    request = request_factory()
    stashed = _bound(request, [{"step": {"name": "Ada"}}])
    payload = stashed.stash()

    resurrected = _fresh_bound(request)
    run_id = resurrected.resurrect(payload)

    assert run_id != "run"
    assert resurrected.run_id == run_id
    assert resurrected.get_state() == [{"step": {"name": "Ada"}}]


def test_resurrecting_the_same_payload_twice_yields_independent_runs(
    request_factory,
):
    request = request_factory()
    payload = _bound(request, [{"step": {"name": "Ada"}}]).stash()

    first = _fresh_bound(request)
    second = _fresh_bound(request)
    first_run = first.resurrect(payload)
    second_run = second.resurrect(payload)

    assert first_run != second_run
    first.get_state()[0]["step"]["name"] = "Grace"
    assert second.get_state() == [{"step": {"name": "Ada"}}]
    assert payload["state"] == [{"step": {"name": "Ada"}}]


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-payload",
        ["not", "a", "payload"],
        {"version": STASH_VERSION},
        {"version": STASH_VERSION, "state": {"step": None}},
        {"version": STASH_VERSION + 1, "state": []},
        {"state": []},
    ],
)
def test_resurrect_refuses_a_malformed_payload(request_factory, payload):
    bound = _fresh_bound(request_factory())

    with pytest.raises(InvalidStash):
        bound.resurrect(payload)


def test_resurrect_refuses_a_label_mismatch_before_creating_a_run(
    request_factory,
):
    request = request_factory()
    bound = _fresh_bound(request)
    payload = {"version": STASH_VERSION, "label": "contact", "state": []}

    with pytest.raises(InvalidStash):
        bound.resurrect(payload, expected_label="billing")
    with pytest.raises(InvalidStash):
        bound.resurrect(
            {"version": STASH_VERSION, "state": []}, expected_label="billing"
        )
    assert request.session.get("gandalf_runs", {}) == {}

    assert bound.resurrect(payload, expected_label="contact")


def test_a_resurrected_run_walks_to_completion(request_factory):
    request = request_factory()
    payload = {
        "version": STASH_VERSION,
        "state": [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ],
    }
    bound = _fresh_bound(request, wizard=_linear_wizard())

    bound.resurrect(payload)

    assert bound.cursor().node is None


def test_a_stripped_required_file_step_parks_the_cursor_there(request_factory):
    """The stash kept the step's data but dropped its files, so on
    resurrection the required file field no longer validates — the walk
    parks exactly where the user has to re-upload."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(ProfilePhotoForm, name="photo")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_factory()
    bound = _fresh_bound(request, wizard=wizard)

    bound.resurrect(
        {
            "version": STASH_VERSION,
            "state": [{"step": {"name": "Ada"}}, {"step": {}}],
        }
    )
    cursor = bound.cursor()

    assert cursor.node.context["name"] == "photo"


def test_a_stripped_optional_file_step_still_validates(request_factory):
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, name="photo")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_factory()
    bound = _fresh_bound(request, wizard=wizard)

    bound.resurrect(
        {"version": STASH_VERSION, "state": [{"step": {"label": "Holiday"}}]}
    )

    assert bound.cursor().node is None


def test_a_tampered_answer_parks_the_cursor_with_an_errored_render(
    request_factory,
):
    request = request_factory()
    bound = _fresh_bound(request, wizard=_linear_wizard())

    bound.resurrect(
        {
            "version": STASH_VERSION,
            "state": [
                {"step": {"name": "Ada"}},
                {"step": {"email": "not-an-email"}},
            ],
        }
    )
    cursor = bound.cursor()

    assert cursor.node.context["name"] == "second"
    assert cursor.response is not None


def test_stash_carries_the_runs_metadata_but_not_an_empty_bag(request_factory):
    bound = _bound(request_factory(), [{"step": {"first_name": "Ada"}}])

    # A run that recorded nothing says nothing, rather than shipping an
    # empty envelope key for every stash ever taken.
    assert "meta" not in bound.stash()

    bound.metadata["record_id"] = "abc"

    # And one that did: unlike the file refs, this rides. A ref names bytes
    # completion deletes; a record id names something that outlives the run.
    assert bound.stash()["meta"] == {"run": {"record_id": "abc"}}


def _proved(bound, step, **facts):
    """Record a proof through storage.

    `run.proof()` needs a walk to know what the fact stands behind, and
    these tests are about what a stash carries rather than about scoping.
    """
    envelope = bound.storage.get_run_metadata(bound.run_id) or {}
    envelope.setdefault("proofs", {})[step] = {"digest": "d", "data": facts}
    bound.storage.set_run_metadata(bound.run_id, envelope)


def test_stash_leaves_a_proof_behind(request_factory):
    """The metadata rides and the proofs do not, and the split is the point
    of each. A record id names something that outlives the run; a proof is a
    claim about *this* run's answers, so a consuming step re-proves itself
    in the run that resurrects them."""
    bound = _bound(request_factory(), [{"step": {"first_name": "Ada"}}])
    bound.metadata["record_id"] = "abc"
    _proved(bound, "first", verified=True)

    assert bound.stash()["meta"] == {"run": {"record_id": "abc"}}


def test_a_stash_of_nothing_but_proofs_carries_no_metadata_key(request_factory):
    bound = _bound(request_factory(), [{"step": {"first_name": "Ada"}}])
    _proved(bound, "first", verified=True)

    assert "meta" not in bound.stash()


def test_resurrecting_restores_what_the_stashed_run_had_recorded(request_factory):
    bound = _bound(request_factory(), [{"step": {"first_name": "Ada"}}])
    bound.metadata["record_id"] = "abc"
    payload = bound.stash()

    fresh = _bound(request_factory(), [])
    fresh.resurrect(payload)

    # Which is why `run_started()` must not fire for a resurrected run: the
    # record it would open is already there.
    assert dict(fresh.metadata) == {"record_id": "abc"}


def test_resurrecting_a_payload_that_recorded_nothing_leaves_an_empty_bag(
    request_factory,
):
    bound = _bound(request_factory(), [])

    bound.resurrect({"version": STASH_VERSION, "state": []})

    assert dict(bound.metadata) == {}


def test_resurrecting_one_payload_twice_gives_two_independent_bags(request_factory):
    bound = _bound(request_factory(), [{"step": {"first_name": "Ada"}}])
    bound.metadata["record_id"] = "abc"
    payload = bound.stash()

    first = _bound(request_factory(), [])
    first.resurrect(payload)
    second = _bound(request_factory(), [])
    second.resurrect(payload)

    first.metadata["record_id"] = "changed"

    # The payload is deep copied on the way in, so editing one resurrected
    # run cannot reach through it into the other.
    assert second.metadata["record_id"] == "abc"
    assert payload["meta"] == {"run": {"record_id": "abc"}}
