"""The driver against the README wizards, end to end.

The unit suite proves the driver's mechanics; these tests prove that the
exact wizards the README shows can be driven start to `done()` without a
browser or a test client, and that the policies the README spells out do
what it says they do.
"""

import pytest

from gandalf.driver import ConfirmationRequired, EditRefused, RunDriver
from tests.testapp.readme_examples import (
    BranchingWizardViewSet,
    SignupWizardViewSet,
)


def _unattended(viewset_class):
    """The same wizard, permitting completion without a person.

    Driving a run to `done()` is the unattended path by definition, so
    these tests have to say so — which is the API working, not a wart.
    """

    return type(
        f"Unattended{viewset_class.__name__}",
        (viewset_class,),
        {"may_finish_unattended": lambda self, bound_wizard: True},
    )


def test_a_wizard_that_says_nothing_will_not_be_finished_without_a_person():
    """The default a wizard gets for free. Everything can be filled and the
    run still refuses to fire `done()`, because nothing declared that
    anything but a person may confirm it."""
    driver = RunDriver.begin(SignupWizardViewSet)
    driver.submit({"name": "Ada"})
    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    with pytest.raises(ConfirmationRequired):
        driver.finish()


def test_what_was_recorded_about_a_placement_survives_a_stash(tmp_path):
    """A run can be lifted out of one store and put down in another. What
    was recorded about who answered what travels with it — otherwise every
    move would quietly relabel a person's answers as nobody's."""
    driver = RunDriver.begin(SignupWizardViewSet)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    payload = driver.bound_wizard.stash()

    assert payload["state"][0]["meta"] == {"placed_by": "person"}


def test_an_agent_drives_the_signup_wizard_to_done():
    driver = RunDriver.begin(_unattended(SignupWizardViewSet))

    assert driver.describe().step == "name"
    driver.submit({"name": "Ada"})
    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    assert driver.finish().content == b"Signed up Ada <ada@example.com>"


def test_an_agent_sees_validation_errors_and_recovers():
    driver = RunDriver.begin(_unattended(SignupWizardViewSet))
    driver.submit({"name": "Ada"})

    rejected = driver.submit({"email": "not-an-email"})
    result = driver.submit({"email": "ada@example.com"})

    assert rejected.status == "invalid"
    assert rejected.errors["email"][0]["code"] == "invalid"
    assert result.status == "complete"


def test_an_earlier_answer_can_be_corrected_and_the_walk_re_routes():
    """A wizard that says nothing about editing lets an answer be replaced —
    which is what makes the retry loop work, since correcting a rejected
    answer is itself an edit. Flipping the answer that chose the arm sends
    the run down the other one."""
    driver = RunDriver.begin(_unattended(BranchingWizardViewSet))
    driver.submit({"account_type": "business"})

    driver.submit({"account_type": "personal"}, step="account_type")

    assert driver.describe().step == "personal"


class _WhatAPersonAnsweredIsTheirs(SignupWizardViewSet):
    """The README's `may_edit_step` example, run for real.

    Whatever a person answered is theirs, whole; the driver may still
    correct answers it placed itself.
    """

    def may_edit_step(self, bound_wizard, step, submission):
        current = bound_wizard.path.find_step(name=step.context["name"])
        return bool((current.metadata or {}).get("unattended"))


def test_the_driver_may_correct_the_answers_it_placed_itself():
    """Required, not merely convenient: recovering from a rejected answer
    means replacing it, so a policy that refused every edit would break the
    retry loop it was never aimed at."""
    driver = RunDriver.begin(_WhatAPersonAnsweredIsTheirs)
    driver.submit({"name": "Ada"})

    result = driver.submit({"name": "Grace"}, step="name")

    assert result.status == "advanced"
    assert driver.answers()["name"] == {"name": "Grace"}


def test_the_driver_may_not_overwrite_what_a_person_answered():
    driver = RunDriver.begin(_WhatAPersonAnsweredIsTheirs)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    with pytest.raises(EditRefused):
        driver.submit({"name": "Grace"}, step="name")

    assert driver.answers()["name"] == {"name": "Ada"}


def test_an_agent_drives_the_branching_wizard_down_the_business_arm():
    driver = RunDriver.begin(_unattended(BranchingWizardViewSet))

    driver.submit({"account_type": "business"})

    assert driver.describe().step == "business"
    driver.submit({"business_name": "Ada Ltd"})
    result = driver.submit({"confirmed": "on"})
    assert result.status == "complete"
    assert driver.finish().content == b"Onboarded Ada Ltd"
