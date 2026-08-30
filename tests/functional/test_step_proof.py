"""A step whose check cannot be performed twice.

Re-proving every answer on every request is what lets Gandalf store
submissions rather than a position, and it assumes a form's `clean()` is a
pure function of its submission and durable state. A one-time password, a
card authorisation, a claimed reference number: proving it consumes it, so
the second dispatch of the same answer fails where the first succeeded and
the user is parked at a step they have already passed.

`run.proof()` is where the durable half of such a check goes — recorded
behind the answers that were true when it was made, and void the moment
they change. These tests hold both halves: that the check runs once however
many requests replay it, and that changing an earlier answer makes it run
again.
"""

from html import unescape
from http import HTTPStatus

import pytest

from tests.testapp.counting import counting_walks
from tests.testapp.views import SPENT_TOKENS, VERIFICATIONS


@pytest.fixture(autouse=True)
def _fresh_device():
    SPENT_TOKENS.clear()
    VERIFICATIONS.clear()
    yield
    SPENT_TOKENS.clear()
    VERIFICATIONS.clear()


@pytest.fixture
def run(wizard_driver):
    run = wizard_driver("one-time-token-wizard").start()
    run.post_step("first", {"name": "Ada"})
    return run


def test_a_consuming_check_survives_the_request_that_makes_it(run):
    """Without a proof this fails on its own POST: the walk dispatches the
    step it is placing, and then the request that follows dispatches it
    again."""
    response = run.post_step("token", {"token": "123456"})

    assert response.status_code == HTTPStatus.FOUND
    assert VERIFICATIONS == ["123456"]


def test_the_check_is_performed_once_however_many_requests_replay_it(run):
    run.post_step("token", {"token": "123456"})

    run.get_step("second")
    run.get_step("second")
    response = run.post_step("second", {"email": "ada@example.com"}, follow=True)

    # Four more dispatches of the token step, none of them a verification —
    # and `done()` reads the proof back, because it holds the same answers
    # before the token step that the step's own dispatch did.
    assert VERIFICATIONS == ["123456"]
    assert response.content.decode() == "verified 1 time(s) as 123456"


def test_changing_an_earlier_answer_voids_the_proof(run):
    """The security property, and the reason a proof is not a note in
    `metadata.for_step()`. The token was proved for one applicant; it must
    not carry a different one through."""
    run.post_step("token", {"token": "123456"})

    response = run.post_step("first", {"name": "Grace"})

    # The same POST walks on past the answer it placed, finds the proof
    # gone, performs the check again, finds the token spent — and parks the
    # user back at the step to enter a fresh one.
    assert VERIFICATIONS == ["123456", "123456"]
    assert response["Location"] == run.step_url("token")


def test_a_fresh_token_gets_past_a_voided_proof(run):
    run.post_step("token", {"token": "123456"})
    run.post_step("first", {"name": "Grace"})

    response = run.post_step("token", {"token": "999999"}, follow=True)
    run.post_step("second", {"email": "grace@example.com"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert VERIFICATIONS == ["123456", "123456", "999999"]


def test_re_answering_the_step_itself_re_performs_the_check(run):
    """A proof stands behind the answers *before* its step, so a new
    submission at the step is a new claim and is checked. The old token
    being spent is what stops a replayed POST standing in for a fresh one."""
    run.post_step("token", {"token": "123456"})

    response = run.post_step("token", {"token": "999999"})

    assert response.status_code == HTTPStatus.FOUND
    assert VERIFICATIONS == ["123456", "999999"]


def test_a_proof_costs_no_dispatch_and_rebuilds_no_form(run):
    """It reads the stored submissions on the walked prefix, not `path`.
    Deriving the scope from `path` would be a form per answered step, on a
    step that reads its proof on every dispatch — the n² trap in
    `docs/reference/walk-costs.md`, in the one place that can least afford
    it."""
    with counting_walks() as counts:
        run.post_step("token", {"token": "123456"})

    # One replay of `first`, one live dispatch of the answer being placed.
    assert counts.validations == 1 + 1
    assert counts.form_rebuilds == 0


def test_the_page_says_which_state_the_proof_is_in(run):
    """The repr, over HTTP, because "my proof is always empty" is the first
    thing anyone hits and its two causes need different fixes."""

    def shown():
        return unescape(run.get_step("token").content.decode())

    assert "StepProof('token', nothing proved)" in shown()

    run.post_step("token", {"token": "123456"})

    assert "StepProof('token', {'token': '123456'})" in shown()

    run.post_step("first", {"name": "Grace"})

    assert "voided by a change to the answers before it" in shown()
