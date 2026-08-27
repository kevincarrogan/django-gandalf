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

from gandalf.driver import RunDriver
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
    to: the walk runs a form's `clean()` once per completed step per HTTP
    request. Reading an answer back costs one more — see
    `test_a_summary_render_validates_each_answer_twice`.
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
    driver = RunDriver.begin(WalkCountingWizardViewSet)
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


def test_every_read_walks_again(driven_run):
    """Reads are not memoised across accesses, and nothing outside a render
    holds a tree for them to reuse.

    This is the shape that turns a linear cost quadratic inside a single
    request: `k` fresh reads of a `k`-answer run cost `k²` validations. A
    `done()` or a completion page that looks each step up separately pays
    it, which is why the advice is to hold the steps you iterate rather
    than re-reading `path` per answer.
    """
    with counting_walks() as counts:
        driven_run.answers()
        driven_run.answers()

    assert counts.walks == 2
    assert counts.validations == 2 + 2


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


# --- a check-your-answers page ----------------------------------------------


@pytest.fixture
def run_at_summary(wizard_driver):
    """The summary wizard's business arm, answered up to its summary step."""
    run = wizard_driver("summary-wizard").start()
    run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme Ltd"}),
            (
                "preferences",
                {
                    "contact_method": "post",
                    "toppings": ["cheese", "basil"],
                    "marketing": "on",
                    "starts_on": "2025-10-12",
                    "note": "Leave with a neighbour",
                },
            ),
        ]
    )
    return run


def test_a_summary_render_validates_each_answer_twice(run_at_summary):
    """The one page where the walk's count is not the whole bill.

    Proving an answer and displaying it are separate passes over the same
    form: the walk re-dispatches each stored answer to prove it still
    stands, and then `SummaryMixin` reads `RuntimeStep.form` per row to get
    `cleaned_data` for the display text. Both run `clean()`, so a
    check-your-answers page costs two validations per answered step where
    an ordinary step page costs one.

    The extra rebuild on top of the three rows is the branch predicate,
    which reads an answer of its own to pick the arm — a route's own reads
    are charged the same way, summary or not.
    """
    with counting_walks() as counts:
        response = run_at_summary.get_step("summary")

    assert response.status_code == HTTPStatus.OK
    assert len(response.context["summary"]) == 3
    assert counts.walks == 1
    # Proving: one per answered step.
    assert counts.validations == 3
    # Displaying: one per row, plus the branch predicate's own read.
    assert counts.form_rebuilds == 3 + 1


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


def test_a_hub_asked_for_its_rows_twice_builds_them_once(counting_hub):
    """The `Hub` counts them and the view asks again for the first unfinished
    one. A row is two storage reads and a `reverse()`, and a whole
    `Collection` for a section that is one, so the second ask is cached."""
    response = counting_hub.get("/counting-hub/")

    assert response.context["builds"] == 1
    assert response.context["first_unfinished"].key == "counting"


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
