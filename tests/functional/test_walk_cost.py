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
from django.urls import reverse

from tests.testapp.counting import counting_walks


@pytest.fixture
def walk_counting_wizard_url():
    return reverse("walk-counting-wizard")


@pytest.fixture
def walk_counting_wizard_run_url():
    def build_url(run_id):
        return reverse("walk-counting-wizard-run", kwargs={"run_id": run_id})

    return build_url


def _step(run_url, step):
    return f"{run_url}{step}/"


@pytest.fixture
def run_at_third_step(client, walk_counting_wizard_url, walk_counting_wizard_run_url):
    """A run with `first` and `second` answered, parked on `third`."""
    client.get(walk_counting_wizard_url)
    run_id = list(client.session["gandalf_runs"])[0]
    run_url = walk_counting_wizard_run_url(run_id)
    client.post(_step(run_url, "first"), data={"name": "Ada"}, follow=True)
    client.post(
        _step(run_url, "second"), data={"email": "ada@example.com"}, follow=True
    )
    return run_url


def test_post_walks_the_tree_once(client, run_at_third_step):
    """One walk, because only one question is ever being asked.

    The walk replays the two stored answers, arrives at the claimed step —
    arriving *is* the authorisation, since it cannot happen without the
    prefix validating — puts the submission there, and carries on. So the
    three validations are two replays plus one live dispatch of the answer
    the user just made.
    """
    with counting_walks() as counts:
        response = client.post(
            _step(run_at_third_step, "third"), data={"preferred_name": "Ada"}
        )

    assert response.status_code == HTTPStatus.FOUND
    assert counts.walks == 1
    assert counts.validations == 2 + 1
    assert counts.renders == 0


def test_get_walks_the_tree_once(client, run_at_third_step):
    """The render side was always at the floor: one walk, one validation per
    stored answer, one dispatch to render the step itself."""
    client.post(_step(run_at_third_step, "third"), data={"preferred_name": "Ada"})

    with counting_walks() as counts:
        response = client.get(_step(run_at_third_step, "fourth"))

    assert response.status_code == HTTPStatus.OK
    assert counts.walks == 1
    assert counts.validations == 3
    assert counts.renders == 1


def test_completing_one_step_costs_two_walks(client, run_at_third_step):
    """The whole POST-redirect-GET cycle a user pays to advance one step.

    Two walks because PRG is genuinely two requests, and each validates the
    answers before it exactly once. That is the invariant worth holding on
    to: a form's `clean()` runs once per completed step per HTTP request.
    """
    with counting_walks() as counts:
        client.post(
            _step(run_at_third_step, "third"),
            data={"preferred_name": "Ada"},
            follow=True,
        )

    assert counts.walks == 2
    assert counts.validations == 3 + 3
