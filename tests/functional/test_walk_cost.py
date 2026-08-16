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

from gandalf.driver import RunDriver, fabricate_request
from tests.testapp.counting import counting_walks
from tests.testapp.views import WalkCountingWizardViewSet


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


# --- the driver's reads -----------------------------------------------------


@pytest.fixture
def driven_run():
    """The same wizard filled from Python: `first` and `second` answered.

    No HTTP here — a driver skips it deliberately — so these numbers are the
    cost of reading a run rather than of serving a request.
    """
    driver = RunDriver.begin(WalkCountingWizardViewSet, request=fabricate_request())
    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"})
    return driver


def test_reading_the_answers_walks_once(driven_run):
    """The floor for any read: one walk, re-proving each stored answer once.

    Every driver read pays this, because a run lives in storage rather than
    in the driver — there is no cached tree to read instead.
    """
    with counting_walks() as counts:
        driven_run.answers()

    assert counts.walks == 1
    assert counts.validations == 2


def test_describing_the_run_walks_once(driven_run):
    """One walk, because one question is being asked.

    `describe()` walks for the cursor and then reads the answers, which
    would walk again for the tree the cursor is already holding. Handing
    that tree over is what keeps a description at the floor `answers()`
    sets above — describing a run costs no more than reading it.
    """
    with counting_walks() as counts:
        driven_run.describe()

    assert counts.walks == 1
    assert counts.validations == 2


# --- a hub of sections ------------------------------------------------------


@pytest.fixture
def counting_hub(client):
    """A hub whose two sections are wired to the counting classes: one left
    half-answered, one untouched."""
    client.get("/counting-hub/counting/", follow=True)
    from gandalf.testing import stored_section_run

    run_id = stored_section_run(client, "counting")
    client.post(f"/counting-hub-section/{run_id}/first/", {"name": "Ada"}, follow=True)
    return client


def test_rendering_a_hub_walks_nothing(counting_hub):
    """The claim the hub's design rests on: status comes from the shape of
    stored state, so a row costs storage reads and no form validation —
    however many sections the page lists and however far each has got.
    """
    with counting_walks() as counts:
        response = counting_hub.get("/counting-hub/")

    assert response.status_code == HTTPStatus.OK
    assert counts.walks == 0
    assert counts.validations == 0
    assert counts.form_rebuilds == 0


def test_entering_a_section_walks_once_in_the_door_and_once_in_the_wizard(
    counting_hub,
):
    """The one walk a hub cannot avoid, paid once for the section clicked.

    The door walks to turn "this run exists" into "this step URL"; the
    wizard walks again to render it. Two walks for the redirect-and-render,
    exactly like the POST-redirect-GET cycle above — not one per section.
    """
    with counting_walks() as counts:
        response = counting_hub.get("/counting-hub/counting/", follow=True)

    assert response.status_code == HTTPStatus.OK
    assert counts.walks == 2
    assert counts.validations == 1 + 1
    assert counts.renders == 1
