"""The driver against the README wizards, end to end.

The unit suite proves the driver's mechanics; these tests prove that the
exact wizards the README shows can be driven start to `done()` without a
browser or a test client, and that the policies the README spells out do
what it says they do.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from gandalf.driver import ConfirmationRequired, RunDriver
from tests.testapp.readme.ch01_first_wizard import FirstApplicationViewSet
from tests.testapp.readme.ch02_branching import BranchingApplicationViewSet
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
    driver = RunDriver.begin(FirstApplicationViewSet)
    driver.submit({"full_name": "Ada"})
    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    with pytest.raises(ConfirmationRequired):
        driver.finish()


def test_what_was_recorded_about_a_placement_survives_a_stash(tmp_path):
    """A run can be lifted out of one store and put down in another. What
    was recorded about who answered what travels with it — otherwise every
    move would quietly relabel a person's answers as nobody's."""
    driver = RunDriver.begin(FirstApplicationViewSet)
    driver.submit({"name": "Ada"}, metadata={"placed_by": "person"})

    payload = driver.bound_wizard.stash()

    assert payload["state"][0]["meta"] == {"placed_by": "person"}


def test_an_agent_drives_the_signup_wizard_to_done():
    driver = RunDriver.begin(FirstApplicationViewSet, may_finish=True)

    assert driver.describe().step == "applicant"
    driver.submit({"full_name": "Ada"})
    result = driver.submit({"email": "ada@example.com"})

    assert result.status == "complete"
    assert driver.finish().content == (
        b"Application received from Ada <ada@example.com>"
    )


def test_an_agent_sees_validation_errors_and_recovers():
    driver = RunDriver.begin(FirstApplicationViewSet, may_finish=True)
    driver.submit({"full_name": "Ada"})

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
    driver = RunDriver.begin(BranchingApplicationViewSet, may_finish=True)
    driver.submit({"applying_as": "organisation"})

    driver.submit({"applying_as": "individual"}, step="applying_as")

    assert driver.describe().step == "about_you"


def test_a_driver_can_tell_its_own_answers_from_a_persons():
    """What the metadata is for. The driver marks its own placements, so a
    caller holding both kinds can tell them apart — which is what any
    "leave their answers alone" rule needs and could not have without it."""
    driver = RunDriver.begin(FirstApplicationViewSet)
    driver.submit({"full_name": "Ada"})

    assert _is_the_drivers_own(driver, "applicant")

    driver.submit(
        {"full_name": "Grace"}, step="applicant", metadata={"placed_by": "person"}
    )

    assert not _is_the_drivers_own(driver, "applicant")


def test_correcting_its_own_earlier_answer_is_never_refused():
    """Required rather than merely convenient: recovering from a rejected
    answer means replacing it, so a policy that refused every edit would
    break the retry loop it was never aimed at."""
    driver = RunDriver.begin(FirstApplicationViewSet)
    driver.submit({"full_name": "Ada"})

    result = driver.submit({"full_name": "Grace"}, step="applicant")

    assert result.status == "advanced"
    assert driver.answers()["applicant"] == {"full_name": "Grace"}


def test_an_agent_drives_the_branching_wizard_down_the_organisation_arm():
    driver = RunDriver.begin(BranchingApplicationViewSet, may_finish=True)

    driver.submit({"applying_as": "organisation"})

    assert driver.describe().step == "organisation"
    driver.submit({"organisation_name": "Ada Ltd"})
    result = driver.submit({"email": "ada@example.com"})
    assert result.status == "complete"
    assert driver.finish().content == b"Application from Ada Ltd <ada@example.com>"


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
        session=client.session,
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
        session=client.session,
    )

    opened = driver.open_file(driver.placements()["photo"].files["photo"])

    assert opened.read() == b"hello"
    assert opened.name == "proof.txt"


def test_the_driver_prefills_a_long_quote_wizard_from_a_profile():
    """The value case: a fourteen-ish step wizard where one prefill from a
    business profile crosses two branches and a grown fleet member,
    leaving only the confirmation for a human."""
    from examples.insurance import InsuranceQuoteViewSet

    driver = RunDriver.begin(InsuranceQuoteViewSet, may_finish=True)

    result = driver.prefill(
        {
            "company": {
                "name": "Analytical Engines Ltd",
                "company_type": "limited",
                "founded": "1837-12-10",
                "employees": "12",
            },
            "registration": {
                "companies_house_number": "AE123456",
                "vat_registered": "on",
            },
            "coverage": {
                "cover_types": ["property", "vehicles"],
                "excess": "500",
                "start_date": "2026-09-01",
            },
            "claims": {"had_claims": "no"},
            "contact": {"email": "ada@analyticalengines.example"},
        }
    )

    assert result.placed == [
        "company",
        "registration",
        "coverage",
        "claims",
        "contact",
    ]
    assert result.next_step == "confirm"
    driver.submit({"confirmed": "on"})
    response = driver.finish()
    # The fleet is priced at nothing, because a driver cannot add a vehicle:
    # the vehicles are a collection of separate runs, and this drives one.
    assert response.content.decode() == (
        "Quote for Analytical Engines Ltd: £670/year covering property, vehicles."
    )


def test_the_driver_walks_the_partnership_arm_and_its_partner_steps():
    """The nasty composite: an expansion nested inside a branch arm, then a
    claims branch — stepped through one answer at a time."""
    from examples.insurance import InsuranceQuoteViewSet

    driver = RunDriver.begin(InsuranceQuoteViewSet, may_finish=True)

    driver.submit(
        {
            "name": "Byron & Lovelace",
            "company_type": "partnership",
            "founded": "1833-06-05",
            "employees": "3",
        }
    )
    assert driver.describe().step == "partners"
    driver.submit({"partner_count": "2"})
    assert driver.describe().step == "partner-0"
    driver.submit({"full_name": "Ada Lovelace"})
    driver.submit({"full_name": "George Byron"})
    assert driver.describe().step == "coverage"
    driver.submit(
        {"cover_types": ["liability"], "excess": "250", "start_date": "2026-09-01"}
    )
    assert driver.describe().step == "claims"
    driver.submit({"had_claims": "yes"})
    assert driver.describe().step == "claims-detail"
    driver.submit({"description": "Difference engine fire", "total_value": "1000"})
    driver.submit({"email": "office@byronlovelace.example"})
    result = driver.submit({"confirmed": "on"})

    assert result.status == "complete"
    assert driver.finish().content.decode() == (
        "Quote for Byron & Lovelace: £530/year covering liability."
    )


def test_the_driver_reports_everything_a_profile_gets_wrong_at_once():
    """The point of checking before placing: one message to the customer,
    not one per failure. Two bad answers and three unanswered steps come
    back together — and the steps that depend on an unmade choice are not
    demanded at all."""
    from examples.insurance import InsuranceQuoteViewSet

    driver = RunDriver.begin(InsuranceQuoteViewSet, may_finish=True)

    result = driver.check(
        {
            "company": {
                "name": "Analytical Engines Ltd",
                "company_type": "limited company",  # the label, not the value
                "founded": "1837-12-10",
                "employees": "twelve",  # a word, not a number
            },
            "coverage": {
                "cover_types": ["property"],
                "excess": "500",
                "start_date": "next Tuesday",  # not a date
            },
        }
    )

    assert set(result.invalid) == {"company", "coverage"}
    assert set(result.invalid["company"]) == {"company_type", "employees"}
    assert set(result.invalid["coverage"]) == {"start_date"}
    assert result.missing == ["claims", "contact", "confirm"]
    # Registration only applies to a limited company, and the company step
    # has not been answered — so it is not something to ask about yet.
    assert "registration" not in result.missing
    assert "partners" not in result.missing


def test_the_fleet_is_where_the_driver_goes_quiet():
    """The boundary this example exists to show.

    Vehicles are a collection: a page the person grows, with one wizard run
    per item behind it. `RunDriver` drives a run. So the fleet is invisible
    to everything the driver offers — it is not a step, so the outline does
    not mention it, `check()` cannot ask for it, and `prefill` has nowhere
    to put it. An agent fills the quote and then has nothing to say.
    """
    from examples.insurance import InsuranceQuoteViewSet

    driver = RunDriver.begin(InsuranceQuoteViewSet, may_finish=True)

    named = [entry.get("step") for entry in driver.outline() if entry["kind"] == "step"]
    assert "fleet" not in named
    assert not any(name and name.startswith("vehicle") for name in named)

    # Handed vehicles anyway, the driver can only say it does not know them.
    result = driver.check(
        {
            "company": {
                "name": "Analytical Engines Ltd",
                "company_type": "limited",
                "founded": "1837-12-10",
                "employees": "12",
            },
            "vehicle-0": {"registration": "AE01 CAB", "value": "18000"},
        }
    )

    assert result.unknown == ["vehicle-0"]
    # And it never asks for one, because from here there is nothing to ask.
    assert "fleet" not in result.missing
