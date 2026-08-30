"""Drive the three ported `django-formtools` wizards end to end.

`docs/learn/coming-from-django-formtools.md` claims a `form_list` maps onto
`.step()` calls and a `condition_dict` onto `.branch()`. Snippets can only
show that the mapping is legible. These drive real wizards from three
shipping projects (`tests/testapp/from_formtools/`) through the test client,
so the claim is something that runs.

Each module's docstring names what upstream has to do by hand. The tests
here are arranged around those: the two exclusive predicates that become one
branch, the earlier answer a later form is built from, and the check that
consumes what it checks.
"""

from html import unescape

import pytest

from tests.testapp.from_formtools import two_factor


ORGANISERS = {
    "form-TOTAL_FORMS": "1",
    "form-INITIAL_FORMS": "0",
    "form-MIN_NUM_FORMS": "1",
    "form-MAX_NUM_FORMS": "10",
    "form-0-email": "ada@example.com",
    "form-0-first_name": "Ada",
}


# --- Django Girls: a condition_dict as branches -----------------------------


def test_a_first_time_organiser_is_asked_about_themselves(wizard_driver):
    run = wizard_driver("formtools-djangogirls").start()

    response = run.post_steps(
        [
            ("previous-event", {"has_organised_before": "no", "previous_event": ""}),
            ("application", {"about_you": "A developer", "why": "To teach"}),
            ("organisers", ORGANISERS),
            ("workshop-type", {"remote": "in-person"}),
            ("workshop", {"city": "Lisbon", "venue": "A hall by the river"}),
        ]
    )

    assert response.content.decode() == (
        "Application from ada@example.com for Lisbon, 1 organiser(s)"
    )


def test_a_returning_organiser_skips_the_application_step(wizard_driver):
    """Upstream's one true skip, and the only one of its three conditions
    that stays a skip here."""
    run = wizard_driver("formtools-djangogirls").start()

    response = run.post_step(
        "previous-event",
        {"has_organised_before": "yes", "previous_event": "Lisbon 2019"},
    )

    assert response["Location"] == run.step_url("organisers")


def test_the_workshop_question_has_exactly_one_answer(wizard_driver):
    """The pair of opposite predicates upstream has to keep in step. One
    branch with two arms cannot show both forms or neither."""
    run = wizard_driver("formtools-djangogirls").start()
    run.post_steps(
        [
            (
                "previous-event",
                {"has_organised_before": "yes", "previous_event": "Lisbon 2019"},
            ),
            ("organisers", ORGANISERS),
        ]
    )

    remote = run.post_step("workshop-type", {"remote": "remote"})

    assert remote["Location"] == run.step_url("workshop-remote")

    in_person = run.post_step("workshop-type", {"remote": "in-person"})

    assert in_person["Location"] == run.step_url("workshop")


def test_a_formset_step_stores_and_replays_like_any_other(wizard_driver):
    """The organisers step. Nothing about it is special: `.step()` took a
    `FormView`, and the stored submission is the POST the browser sent."""
    run = wizard_driver("formtools-djangogirls").start()
    run.post_steps(
        [
            (
                "previous-event",
                {"has_organised_before": "yes", "previous_event": "Lisbon 2019"},
            ),
            (
                "organisers",
                {
                    **ORGANISERS,
                    "form-TOTAL_FORMS": "2",
                    "form-1-email": "grace@example.com",
                    "form-1-first_name": "Grace",
                },
            ),
            ("workshop-type", {"remote": "remote"}),
        ]
    )

    response = run.post_step(
        "workshop-remote", {"city": "Lisbon", "tools": "Zoom"}, follow=True
    )

    assert response.content.decode() == (
        "Application from ada@example.com for Lisbon, 2 organiser(s)"
    )


# --- Squest: a later form built from an earlier answer ----------------------


def test_the_survey_is_built_from_the_instance_step(wizard_driver):
    run = wizard_driver("formtools-squest").start()

    run.post_step("instance", {"name": "reporting-db", "quota_scope": "research"})
    page = unescape(run.get_step("survey").content.decode())

    # Both values read off the named step, not out of storage by position.
    assert "Research team may request up to 4 for reporting-db." in page


def test_the_survey_enforces_the_scope_it_was_built_for(wizard_driver):
    run = wizard_driver("formtools-squest").start()
    run.post_step("instance", {"name": "reporting-db", "quota_scope": "research"})

    refused = run.post_step("survey", {"cpus": "8"})

    assert refused["Location"] == run.step_url("survey")
    assert run.get_step("survey").context["form"].errors == {
        "cpus": ["Ensure this value is less than or equal to 4."]
    }

    accepted = run.post_step("survey", {"cpus": "4"}, follow=True)

    assert accepted.content.decode() == (
        "Requested reporting-db for research with 4 CPUs"
    )


def test_changing_the_scope_rebuilds_the_survey_against_the_new_one(wizard_driver):
    """The reason to read an answer rather than cache it: the form is built
    per dispatch, so an edit upstream of it lands immediately."""
    run = wizard_driver("formtools-squest").start()
    run.post_step("instance", {"name": "reporting-db", "quota_scope": "research"})

    run.post_step("instance", {"name": "reporting-db", "quota_scope": "platform"})

    accepted = run.post_step("survey", {"cpus": "8"}, follow=True)

    assert accepted.content.decode() == (
        "Requested reporting-db for platform with 8 CPUs"
    )


# --- two-factor: a shape per request, and a consuming check -----------------


@pytest.fixture(autouse=True)
def _fresh_devices():
    two_factor.SPENT.clear()
    two_factor.VERIFICATIONS.clear()
    yield
    two_factor.SPENT.clear()
    two_factor.VERIFICATIONS.clear()


def code_on(run, step):
    """The code the page is showing, as a person reading their phone would."""
    page = unescape(run.get_step(step).content.decode())
    return page.split("Your code is <strong>")[1].split("<")[0]


def test_the_registry_decides_which_steps_exist(wizard_driver):
    run = wizard_driver("formtools-two-factor").start()

    run.post_step("welcome", {})
    response = run.post_step("method", {"method": "sms"})

    assert response["Location"] == run.step_url("sms")

    response = run.post_step("method", {"method": "generator"})

    assert response["Location"] == run.step_url("generator")


def test_one_registered_method_asks_nothing(wizard_driver):
    """Upstream deletes the step and writes the answer it would have given
    into its own answer store. Here the step is never declared."""
    run = wizard_driver("formtools-two-factor-single").start()

    response = run.post_step("welcome", {})

    assert response["Location"] == run.step_url("generator")


def test_the_code_is_verified_once_however_many_requests_replay_it(wizard_driver):
    run = wizard_driver("formtools-two-factor").start()
    run.post_steps([("welcome", {}), ("method", {"method": "generator"})])

    code = code_on(run, "generator")

    run.post_step("generator", {"code": code})
    response = run.post_step("name", {"name": "My phone"}, follow=True)

    # Two dispatches of the code step on the POST that made it, and one on
    # every request after. One verification.
    assert two_factor.VERIFICATIONS == [code]
    assert response.content.decode() == (
        "set up via ['welcome', 'method', 'generator', 'name'], verified 1 time(s)"
    )


def test_the_code_survives_the_steps_that_follow_it(wizard_driver):
    """Naming the device comes after the code, which is where a wizard
    without proofs cannot go: every request from here replays the code."""
    run = wizard_driver("formtools-two-factor").start()
    run.post_steps(
        [
            ("welcome", {}),
            ("method", {"method": "sms"}),
            ("sms", {"number": "+44 7700 900000"}),
        ]
    )

    advanced = run.post_step("validation", {"code": code_on(run, "validation")})

    assert advanced["Location"] == run.step_url("name")

    response = run.post_step("name", {"name": "My phone"}, follow=True)

    assert "verified 1 time(s)" in response.content.decode()


def test_changing_the_number_makes_the_code_be_verified_again(wizard_driver):
    """The proof is scoped to the answers behind it, so a different phone
    number is a different claim — and the code already spent cannot carry
    the new one."""
    run = wizard_driver("formtools-two-factor").start()
    run.post_steps(
        [
            ("welcome", {}),
            ("method", {"method": "sms"}),
            ("sms", {"number": "+44 7700 900000"}),
        ]
    )
    run.post_step("validation", {"code": code_on(run, "validation")})

    parked = run.post_step("sms", {"number": "+44 7700 900999"})

    assert parked["Location"] == run.step_url("validation")
    assert len(two_factor.VERIFICATIONS) == 1
    assert "voided by a change" in unescape(run.get_step("validation").content.decode())
