"""Watching a run: what an observer is told, and what it is not."""

import pytest

from gandalf.context import WizardContext
from gandalf.observers import WizardObserver
from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.wizard import Wizard, condition
from tests.testapp.forms import FirstStepForm, SecondStepForm


class _Session(dict):
    modified = False


@pytest.fixture
def request_with_session(rf):
    request = rf.get("/wizard/")
    request.session = _Session()
    return request


def _wizard(observer_class):
    return (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(
            template_name="testapp/linear_wizard.html",
            observer_class=observer_class,
        )
    )


def _answered_ada(context):
    """The first step said Ada."""
    first = context.run.path.find_step(name="first")
    return first.form.cleaned_data["name"] == "Ada"


def _branching_wizard(observer_class):
    """The same two steps, with the second one behind a fork — so the
    submission that answers it is placed by a nested walk."""
    return (
        Wizard()
        .step(FirstStepForm, name="first")
        .branch(condition(_answered_ada, Wizard().step(SecondStepForm, name="second")))
        .configure(
            template_name="testapp/linear_wizard.html",
            observer_class=observer_class,
        )
    )


def _run(observer_class, request, wizard=_wizard):
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(
        context, SessionStorage(context), wizard=wizard(observer_class)
    )
    bound_wizard.initialise()
    return bound_wizard


def _submit(bound_wizard, submission, metadata=None):
    walk = bound_wizard.walk(
        claim=bound_wizard.cursor().node, submission=submission, metadata=metadata
    )
    bound_wizard.persist(walk)
    return walk


def test_an_observer_is_told_which_step_was_answered_and_whether_it_held(
    request_with_session,
):
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append((step.context["name"], accepted))

    bound_wizard = _run(_Recorder, request_with_session)

    _submit(bound_wizard, {"name": "Ada"})
    _submit(bound_wizard, {"email": "not-an-email"})

    assert seen == [("first", True), ("second", False)]


def test_a_mistake_is_counted_once_however_many_pages_follow_it(request_with_session):
    """The property that makes the numbers mean anything. A run re-proves
    every stored answer on every request, so an observer told about
    validations would count one bad email again on every later step."""
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append(step.context["name"])

    bound_wizard = _run(_Recorder, request_with_session)
    _submit(bound_wizard, {"name": "Ada"})
    _submit(bound_wizard, {"email": "not-an-email"})
    seen.clear()

    # Several more walks over the same run, as later requests would do.
    bound_wizard.cursor()
    bound_wizard.cursor()
    list(bound_wizard.path)

    assert seen == []


def test_an_observer_hears_about_the_end_of_the_run(request_with_session):
    seen = []

    class _Recorder(WizardObserver):
        def run_completed(self):
            seen.append(self.run_id)

    bound_wizard = _run(_Recorder, request_with_session)

    bound_wizard.complete()

    assert seen == [bound_wizard.run_id]


def test_an_observer_knows_which_run_it_is_watching(request_with_session):
    """Per-run, so no event repeats the id — and a metric can be grouped by
    journey rather than only by step."""
    seen = []

    class _Watcher(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append(self.run_id)

    bound_wizard = _run(_Watcher, request_with_session)

    _submit(bound_wizard, {"name": "Ada"})

    assert seen == [bound_wizard.run_id]


def test_an_observer_is_never_handed_the_answers(request_with_session):
    """It is given the declaration and the outcome. Somebody's name is not
    a metric, and a hook that received one would put it wherever the
    metrics go."""
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append((step, accepted))

    bound_wizard = _run(_Recorder, request_with_session)

    _submit(bound_wizard, {"name": "Ada Lovelace"})

    assert "Ada Lovelace" not in str(seen)


def test_a_wizard_without_one_is_watched_by_a_no_op(request_with_session):
    """The default observer is the base class, and it does nothing."""
    bound_wizard = _run(WizardObserver, request_with_session)

    _submit(bound_wizard, {"name": "Ada"})

    assert bound_wizard.cursor().node.context == {"name": "second"}


def test_an_observer_is_told_what_the_placement_claimed_about_itself(
    request_with_session,
):
    """The distinction the library cannot make for itself. It never learns
    who is on the other end — it repeats what the placement said it was."""
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append(metadata)

    bound_wizard = _run(_Recorder, request_with_session)

    _submit(bound_wizard, {"name": "Ada"}, metadata={"unattended": True})

    assert seen == [{"unattended": True}]


def test_a_placement_inside_a_branch_arm_reports_what_it_claimed(request_with_session):
    """An arm is walked by a nested walk, and the claim has to reach it.
    Without that, an observer telling a person's answer from an agent's
    could do it only for the steps outside every fork."""
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append((step.context["name"], metadata))

    bound_wizard = _run(_Recorder, request_with_session, _branching_wizard)
    _submit(bound_wizard, {"name": "Ada"}, metadata={"unattended": True})

    _submit(
        bound_wizard, {"email": "ada@example.com"}, metadata={"placed_by": "person"}
    )

    assert seen == [
        ("first", {"unattended": True}),
        ("second", {"placed_by": "person"}),
    ]


def test_a_submission_that_claimed_nothing_arrives_as_none(request_with_session):
    """Which is every browser submission: a request carries no such claim,
    so an observer counting unattended placements counts none of them."""
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted, metadata):
            seen.append(metadata)

    bound_wizard = _run(_Recorder, request_with_session)

    _submit(bound_wizard, {"name": "Ada"})

    assert seen == [None]
