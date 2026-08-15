"""Watching a run: what an observer is told, and what it is not."""

import pytest

from gandalf.observers import WizardObserver
from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.wizard import Wizard
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


def _run(observer_class, request):
    bound_wizard = BoundWizard(
        request, SessionStorage(request), wizard=_wizard(observer_class)
    )
    bound_wizard.initialise()
    return bound_wizard


def _submit(bound_wizard, submission):
    walk = bound_wizard.walk(claim=bound_wizard.cursor().node, submission=submission)
    bound_wizard.persist(walk)
    return walk


def test_an_observer_is_told_which_step_was_answered_and_whether_it_held(
    request_with_session,
):
    seen = []

    class _Recorder(WizardObserver):
        def submission(self, step, accepted):
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
        def submission(self, step, accepted):
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
        def submission(self, step, accepted):
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
        def submission(self, step, accepted):
            seen.append((step, accepted))

    bound_wizard = _run(_Recorder, request_with_session)

    _submit(bound_wizard, {"name": "Ada Lovelace"})

    assert "Ada Lovelace" not in str(seen)


def test_a_wizard_without_one_is_watched_by_a_no_op(request_with_session):
    """The default observer is the base class, and it does nothing."""
    bound_wizard = _run(WizardObserver, request_with_session)

    _submit(bound_wizard, {"name": "Ada"})

    assert bound_wizard.cursor().node.context == {"name": "second"}
