"""Unit coverage for `BoundWizard.entry_url()`.

The bare run URL redirects to wherever the cursor is, and when every stored
answer validates that is completion — so a GET there fires `done()` before the
user has touched anything. `entry_url()` is the link *into* a run from outside
it, and it names a step instead.
"""

import pytest

from gandalf.context import WizardContext
from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.wizard import Wizard

from tests.testapp.forms import FirstStepForm, SecondStepForm


class _Session(dict):
    modified = False


class _Urls:
    """Stand-in for the viewset's reverser — the two methods `run_url` and
    `step_url` call."""

    def get_wizard_url(self, run_id):
        return f"/wizard/{run_id}/"

    def get_step_url(self, run_id, segment):
        return f"/wizard/{run_id}/{segment}/"


@pytest.fixture
def request_factory(rf):
    def build():
        request = rf.get("/wizard/")
        request.session = _Session()
        return request

    return build


def _linear_wizard():
    return (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(template_name="testapp/linear_wizard.html")
    )


def _bound(request, state, wizard=None):
    if wizard is None:
        wizard = _linear_wizard()
    request.session["gandalf_runs"] = {"run": {"state": state}}
    context = WizardContext.from_request(request)
    bound = BoundWizard(context, SessionStorage(context), wizard=wizard)
    bound.retrieve("run")
    bound.urls = _Urls()
    return bound


def test_entry_url_names_the_step_it_is_given(request_factory):
    bound = _bound(request_factory(), [])

    assert bound.entry_url("second") == "/wizard/run/second/"


def test_entry_url_is_the_cursor_step_for_a_half_answered_run(request_factory):
    bound = _bound(request_factory(), [{"step": {"name": "Ada"}}])

    assert bound.entry_url() == "/wizard/run/second/"


def test_entry_url_is_the_first_step_when_every_answer_validates(request_factory):
    """A run whose answers all validate has no cursor step to name, and the
    bare run URL would fire `done()`, so an edit begins at the top."""
    bound = _bound(
        request_factory(),
        [{"step": {"name": "Ada"}}, {"step": {"email": "ada@example.com"}}],
    )

    assert bound.entry_url() == "/wizard/run/first/"


def test_entry_url_falls_back_to_the_run_url_for_a_wizard_with_no_steps(
    request_factory,
):
    """Nothing to name — and nothing to fire either."""
    bound = _bound(
        request_factory(),
        [],
        wizard=Wizard().configure(template_name="testapp/linear_wizard.html"),
    )

    assert bound.entry_url() == "/wizard/run/"


def test_entry_url_is_none_without_a_url_reverser(request_factory):
    """Programmatic use, exactly as `run_url` and `step_url` behave."""
    bound = _bound(request_factory(), [{"step": {"name": "Ada"}}])
    bound.urls = None

    assert bound.entry_url() is None
