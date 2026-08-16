"""The driver against the README wizards, end to end.

The unit suite proves the driver's mechanics; these tests prove that the
exact wizards the README shows can be driven start to `done()` without a
browser or a test client, and that the policies the README spells out do
what it says they do.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from gandalf.driver import ConfirmationRequired, RunDriver, fabricate_request
from tests.testapp.readme_examples import (
    BranchingWizardViewSet,
    SignupWizardViewSet,
)
from tests.testapp.views import FileUploadingWizardViewSet


def _is_the_drivers_own(driver, step):
    """Whether this driver placed the answer at `step` itself.

    The application's half of an edit policy, written on metadata alone.
    Nothing in the library refuses an edit — who owns an answer is a
    question about a domain rather than about wizards — so a caller that
    cares asks before it submits. This is the whole recipe.

    One read, because the question spans two of a placement's three parts:
    a step nobody has answered has no placement, and is a different thing
    from one answered by somebody who recorded nothing.
    """
    placement = driver.placements().get(step)
    return placement is not None and bool(placement.metadata.get("unattended"))


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
    driver = RunDriver.begin(SignupWizardViewSet, may_finish=True)

    assert driver.describe().step == "name"
    driver.submit({"name": "Ada"})
    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    assert driver.finish().content == b"Signed up Ada <ada@example.com>"


def test_an_agent_sees_validation_errors_and_recovers():
    driver = RunDriver.begin(SignupWizardViewSet, may_finish=True)
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
    driver = RunDriver.begin(BranchingWizardViewSet, may_finish=True)
    driver.submit({"account_type": "business"})

    driver.submit({"account_type": "personal"}, step="account_type")

    assert driver.describe().step == "personal"


def test_a_driver_can_tell_its_own_answers_from_a_persons():
    """What the metadata is for. The driver marks its own placements, so a
    caller holding both kinds can tell them apart — which is what any
    "leave their answers alone" rule needs and could not have without it."""
    driver = RunDriver.begin(SignupWizardViewSet)
    driver.submit({"name": "Ada"})

    assert _is_the_drivers_own(driver, "name")

    driver.submit({"name": "Grace"}, step="name", metadata={"placed_by": "person"})

    assert not _is_the_drivers_own(driver, "name")


def test_correcting_its_own_earlier_answer_is_never_refused():
    """Required rather than merely convenient: recovering from a rejected
    answer means replacing it, so a policy that refused every edit would
    break the retry loop it was never aimed at."""
    driver = RunDriver.begin(SignupWizardViewSet)
    driver.submit({"name": "Ada"})

    result = driver.submit({"name": "Grace"}, step="name")

    assert result.status == "advanced"
    assert driver.answers()["name"] == {"name": "Grace"}


def test_an_agent_drives_the_branching_wizard_down_the_business_arm():
    driver = RunDriver.begin(BranchingWizardViewSet, may_finish=True)

    driver.submit({"account_type": "business"})

    assert driver.describe().step == "business"
    driver.submit({"business_name": "Ada Ltd"})
    result = driver.submit({"confirmed": "on"})
    assert result.status == "complete"
    assert driver.finish().content == b"Onboarded Ada Ltd"


def test_a_driver_reads_a_run_whose_file_step_was_answered(
    client, wizard_driver, isolated_media_root
):
    """The read side of the file gap, which used to be a `TypeError`.

    A person uploads through the browser and hands the run on. Everything
    after that point is the driver's, so it has to be able to read what
    came before — and an open file is not JSON, which is what a driver's
    caller almost always speaks.
    """
    run = wizard_driver("file-uploading-wizard").start()
    run.post_step("photo", {"photo": SimpleUploadedFile("proof.txt", b"hello")})

    driver = RunDriver.resume(
        FileUploadingWizardViewSet,
        run.run_id,
        request=fabricate_request(session=client.session),
    )

    placement = driver.placements()["photo"]
    # The reference is what state holds, so it is JSON already and names
    # the same bytes the browser stored.
    assert placement.files["photo"]["name"] == "proof.txt"
    assert placement.answers["photo"].name == "proof.txt"

    # The call both agent adapters make on every tool call.
    described = driver.describe(json_safe=True)
    assert described.answers["photo"]["photo"] == placement.files["photo"]


def test_a_driver_can_open_the_file_a_person_uploaded(
    client, wizard_driver, isolated_media_root
):
    """The read a browser never needs and a caller often does.

    The reference says a file is there; only the bytes say whether it is
    the right one. Checking that is the sort of thing a wizard's own
    `clean()` cannot do and whatever is driving the run might.
    """
    run = wizard_driver("file-uploading-wizard").start()
    run.post_step("photo", {"photo": SimpleUploadedFile("proof.txt", b"hello")})

    driver = RunDriver.resume(
        FileUploadingWizardViewSet,
        run.run_id,
        request=fabricate_request(session=client.session),
    )

    opened = driver.open_file(driver.placements()["photo"].files["photo"])

    assert opened.read() == b"hello"
    assert opened.name == "proof.txt"
