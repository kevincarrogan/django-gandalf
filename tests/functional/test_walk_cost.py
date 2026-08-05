"""How much work one request does, asserted exactly.

Issue #46 asks for the validation-walk cost to be characterised. Wall-clock
timings are too noisy to assert, but dispatch counts are exact and identical
on every machine, so they pin the cost down as a fact.

These numbers are deliberately hard-coded rather than derived: they are the
thing under test. When the walk changes shape they should be updated in one
place, and that diff is the review artifact showing what the change bought.
"""

from http import HTTPStatus

import pytest

from tests.testapp.counting import counting_walks


@pytest.fixture
def run_at_third_step(wizard_driver):
    """A run with `first` and `second` answered, parked on `third`."""
    run = wizard_driver("walk-counting-wizard").start()
    run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
        ]
    )
    return run


def test_post_walks_the_tree_once(run_at_third_step):
    """One walk, because only one question is ever being asked.

    The walk replays the two stored answers, arrives at the claimed step —
    arriving *is* the authorisation, since it cannot happen without the
    prefix validating — puts the submission there, and carries on. So the
    three validations are two replays plus one live dispatch of the answer
    the user just made.
    """
    with counting_walks() as counts:
        response = run_at_third_step.post_step("third", {"preferred_name": "Ada"})

    assert response.status_code == HTTPStatus.FOUND
    assert counts.walks == 1
    assert counts.validations == 2 + 1
    assert counts.renders == 0


def test_get_walks_the_tree_once(run_at_third_step):
    """The render side was always at the floor: one walk, one validation per
    stored answer, one dispatch to render the step itself."""
    run_at_third_step.post_step("third", {"preferred_name": "Ada"})

    with counting_walks() as counts:
        response = run_at_third_step.get_step("fourth")

    assert response.status_code == HTTPStatus.OK
    assert counts.walks == 1
    assert counts.validations == 3
    assert counts.renders == 1


def test_completing_one_step_costs_two_walks(run_at_third_step):
    """The whole POST-redirect-GET cycle a user pays to advance one step.

    Two walks because PRG is genuinely two requests, and each validates the
    answers before it exactly once. That is the invariant worth holding on
    to: a form's `clean()` runs once per completed step per HTTP request.
    """
    with counting_walks() as counts:
        run_at_third_step.post_step("third", {"preferred_name": "Ada"}, follow=True)

    assert counts.walks == 2
    assert counts.validations == 3 + 3
