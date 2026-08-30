"""What an observer is told about a run somebody and something both filled.

The unit suite proves the argument arrives. This proves the point of it:
one observer, one run, two kinds of placement, told apart — which is the
question a shared journey actually asks and the one the hook could not
answer before.
"""

from django.http import HttpResponse

from gandalf.driver import RunDriver
from gandalf.observers import WizardObserver
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


SEEN: list[tuple[str, object]] = []


class _Recorder(WizardObserver):
    def submission(self, step, accepted, metadata):
        SEEN.append((step.context["name"], metadata))


class _WatchedViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(
            template_name="testapp/linear_wizard.html",
            observer_class=_Recorder,
        )
    )

    def done(self, run):
        return HttpResponse(b"done")


def test_an_observer_can_tell_a_persons_answer_from_a_drivers():
    SEEN.clear()
    driver = RunDriver.begin(_WatchedViewSet, may_finish=True)

    driver.submit({"name": "Ada"})
    driver.submit({"email": "ada@example.com"}, metadata={"placed_by": "person"})
    driver.finish()

    assert SEEN == [
        # The driver says what it is without being asked.
        ("first", {"unattended": True}),
        # And repeats what it was told, for the answer it was placing on
        # somebody else's behalf.
        ("second", {"placed_by": "person"}),
    ]
