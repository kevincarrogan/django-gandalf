"""The proof bag, and what `run.proof()` scopes it to.

The functional suite proves what it is *for* — a check that cannot be
performed twice. This proves the two mechanics that make it safe: a bag
stamped with a digest reads as empty once that digest changes, and the
digest `run.proof()` supplies is the answers before the step it names.
Everything else the bag inherits from `MetadataBag`, which
`test_run_metadata_bag.py` covers.
"""

import pytest

from gandalf.context import WizardContext
from gandalf.runtime import Run, RunMetadata, StepProof
from gandalf.storage import SessionStorage
from gandalf.wizard import Wizard

from tests.testapp.forms import FirstStepForm, SecondStepForm
from gandalf.testing import configured


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


def proof(storage, digest, name="token"):
    return StepProof(storage, storage.run_id, name, digest)


def test_a_proof_reads_back_under_the_digest_it_was_written_with(storage):
    proof(storage, "abc")["verified"] = 123456

    assert proof(storage, "abc")["verified"] == 123456


def test_a_proof_written_behind_other_answers_reads_as_empty(storage):
    """The whole point: the answers it was established behind are gone, so
    nothing was proved here as far as any reader is concerned."""
    proof(storage, "abc")["verified"] = 123456

    stale = proof(storage, "different")

    assert dict(stale) == {}
    assert len(stale) == 0
    with pytest.raises(KeyError):
        stale["verified"]


def test_a_stale_proof_is_replaced_rather_than_merged(storage):
    """A write behind new answers starts a fresh proof. Merging would let a
    key from the voided one survive into it, which is the leak the digest
    exists to stop."""
    proof(storage, "abc").update(verified=123456, sent_to="+44...")

    proof(storage, "different")["verified"] = 999999

    assert dict(proof(storage, "different")) == {"verified": 999999}


def test_answers_changing_and_changing_back_leaves_the_proof_standing(storage):
    """The digest describes the answers, not how many times they moved. A
    proof behind a prefix that has come back to where it was is about the
    answers that are there now, and holds."""
    proof(storage, "abc")["verified"] = 123456

    assert dict(proof(storage, "different")) == {}
    assert proof(storage, "abc")["verified"] == 123456


def test_two_steps_proofs_cannot_tread_on_each_other(storage):
    proof(storage, "abc", name="token")["verified"] = 1
    proof(storage, "abc", name="payment")["verified"] = 2

    assert proof(storage, "abc", name="token")["verified"] == 1
    assert proof(storage, "abc", name="payment")["verified"] == 2


def test_a_proof_cannot_tread_on_the_steps_durable_metadata(storage):
    """Adjacent buckets, deliberately: one survives everything, the other is
    void the moment the answers behind it move. Reading the wrong one is the
    bug this separation makes impossible."""
    metadata = RunMetadata(storage, storage.run_id)
    metadata.for_step("token")["verified"] = "durable"
    proof(storage, "abc")["verified"] = "scoped"

    assert metadata.for_step("token")["verified"] == "durable"
    assert proof(storage, "abc")["verified"] == "scoped"
    assert storage.get_run_metadata(storage.run_id) == {
        "steps": {"token": {"verified": "durable"}},
        "proofs": {"token": {"digest": "abc", "data": {"verified": "scoped"}}},
    }


def test_deleting_a_key_from_a_voided_proof_leaves_storage_untouched(storage):
    proof(storage, "abc")["verified"] = 123456

    with pytest.raises(KeyError):
        del proof(storage, "different")["verified"]

    assert proof(storage, "abc")["verified"] == 123456


def test_a_proof_says_which_of_its_three_states_it_is_in(storage):
    """An empty read has two causes and they need different fixes. The
    voided one does not show what it held: it is void, and an expired
    one-time password is not a thing to leave in a log."""
    assert repr(proof(storage, "abc")) == "StepProof('token', nothing proved)"

    proof(storage, "abc")["verified"] = 123456

    assert repr(proof(storage, "abc")) == "StepProof('token', {'verified': 123456})"
    assert repr(proof(storage, "different")) == (
        "StepProof('token', voided by a change to the answers before it)"
    )


# --- what `run.proof()` scopes the bag to -----------------------------------


ADA = [{"step": {"name": "Ada"}}, {"step": {"email": "ada@example.com"}}]
GRACE = [{"step": {"name": "Grace"}}, {"step": {"email": "ada@example.com"}}]


@pytest.fixture
def bound(rf):
    """A bound run over one session, whose answers a test can rewrite.

    One session throughout, because the point of these tests is a proof
    written under one set of answers and read back under another — and the
    bag lives in storage beside them.
    """
    request = rf.get("/wizard/")
    request.session = _Session()
    request.session["gandalf_runs"] = {"run": {"state": ADA}}
    context = WizardContext.from_request(request)
    run = Run(
        context,
        SessionStorage(context),
        wizard=(
            configured(
                Wizard()
                .step(FirstStepForm, name="first")
                .step(SecondStepForm, name="second"),
                template_name="testapp/linear_wizard.html",
            )
        ),
    )
    run.retrieve("run")

    def answered(state):
        request.session["gandalf_runs"]["run"]["state"] = state
        return run

    run.answered = answered
    return run


def test_a_proof_stands_while_the_answers_before_its_step_hold(bound):
    bound.proof("second")["verified"] = True

    assert bound.answered(ADA).proof("second")["verified"] is True


def test_changing_an_answer_before_the_step_voids_its_proof(bound):
    bound.proof("second")["verified"] = True

    assert dict(bound.answered(GRACE).proof("second")) == {}


def test_the_step_a_proof_names_is_not_part_of_its_own_scope(bound):
    """Which is what lets the step read its proof during its own dispatch,
    where its answer is not on the walked prefix yet — and what makes a new
    submission at the step a new claim for the form to check rather than
    something the proof silently covers."""
    bound.proof("second")["verified"] = True

    answered_again = [
        {"step": {"name": "Ada"}},
        {"step": {"email": "grace@example.com"}},
    ]

    assert bound.answered(answered_again).proof("second")["verified"] is True


def test_a_name_no_step_carries_is_scoped_to_the_whole_route(bound):
    """Not an error — checking would cost a walk — so it behaves like a step
    at the very end: scoped to everything, and void as soon as anything
    moves."""
    bound.proof("nowhere")["noted"] = True

    assert bound.answered(ADA).proof("nowhere")["noted"] is True
    assert dict(bound.answered(GRACE).proof("nowhere")) == {}


def test_a_rotated_csrf_token_does_not_void_a_proof(bound):
    """A token says nothing about whether an answer changed, and a proof
    that vanished when one rotated would be a mystery to debug."""
    bound.proof("second")["verified"] = True

    with_token = [
        {"step": {"name": "Ada", "csrfmiddlewaretoken": "rotated"}},
        {"step": {"email": "ada@example.com"}},
    ]

    assert bound.answered(with_token).proof("second")["verified"] is True


def test_discarding_proofs_leaves_the_durable_metadata_standing(bound):
    """What retiring a run sweeps, and what it must not. A proof is a claim
    about answers completion discards; a record the run opened somewhere
    else outlives the run entirely, and the two sit in adjacent buckets so
    that this sweep can tell them apart."""
    bound.metadata.for_step("second")["reference"] = "INV-1"
    bound.proof("second")["verified"] = True

    bound.discard_proofs()

    assert bound.storage.get_run_metadata("run") == {
        "steps": {"second": {"reference": "INV-1"}}
    }


def test_discarding_proofs_on_a_run_that_holds_none_writes_nothing(bound):
    """Every run without a consuming check takes this path on completion,
    and a write here would dirty the session on the way out for nothing."""
    bound.metadata.for_step("second")["reference"] = "INV-1"
    bound.context.session.modified = False

    bound.discard_proofs()

    assert bound.context.session.modified is False
    assert bound.storage.get_run_metadata("run") == {
        "steps": {"second": {"reference": "INV-1"}}
    }
