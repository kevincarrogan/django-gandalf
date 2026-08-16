"""The handover: an agent fills the run, a person finishes it.

The point of the hybrid demo, proved without a browser or a model. The
agent's side is the driver over durable storage; the person's side is the
ordinary Django wizard, reached at the run's own URL. They are the same
run — the same id, the same answers, the same walk — so the person can
change what the agent got wrong and confirm, and `done()` fires once, on
their submission.

Nothing here calls a model, but reaching the demo's wizards imports the
module that serves them, which needs the `agents` dependency group
(`just test-agents`). Under the default groups these skip, like the two
spike suites beside them.
"""

from http import HTTPStatus

import pytest

pytest.importorskip("pydantic_ai")

from django.contrib.auth import get_user_model  # noqa: E402
from django.urls import reverse  # noqa: E402
from pytest_django.asserts import assertContains, assertRedirects  # noqa: E402

from examples.copilotkit import settings as hybrid_settings  # noqa: E402
from examples.copilotkit.wizards import HybridQuoteViewSet  # noqa: E402
from gandalf.driver import RunDriver, fabricate_request  # noqa: E402
from tests.testapp.models import WizardRun  # noqa: E402

PROFILE_ANSWERS = {
    "company": {
        "name": "Analytical Engines Ltd",
        "company_type": "limited",
        "founded": "1837-12-10",
        "employees": "12",
    },
    "registration": {"companies_house_number": "AE123456", "vat_registered": "on"},
    "coverage": {
        "cover_types": ["property", "vehicles"],
        "excess": "500",
        "start_date": "2026-09-01",
    },
    "claims": {"had_claims": "no"},
    "contact": {"email": "ada@analyticalengines.example"},
}


@pytest.fixture
def hybrid(settings):
    """The demo's URLconf and templates, over the test database."""
    settings.ROOT_URLCONF = "examples.copilotkit.urls"
    settings.TEMPLATES = hybrid_settings.TEMPLATES
    return settings


@pytest.fixture
def customer(db):
    return get_user_model().objects.create(username="demo")


@pytest.fixture
def filled_run(hybrid, customer):
    """What the agent leaves behind: a run filled from the profile, parked
    on the check-your-answers step."""
    driver = RunDriver.begin(
        HybridQuoteViewSet, request=fabricate_request(user=customer)
    )
    result = driver.prefill(PROFILE_ANSWERS)
    assert result.next_step == "confirm"
    return driver


def test_the_person_lands_on_their_answers_and_can_change_any_of_them(
    client, customer, filled_run
):
    client.force_login(customer)

    response = client.get(filled_run.bound_wizard.entry_url("confirm"))

    assert response.status_code == HTTPStatus.OK
    assertContains(response, "Check your answers")
    # Everything the agent filled is on the page...
    assertContains(response, "Analytical Engines Ltd")
    assertContains(response, "AE123456")
    # ...each with a way to change it.
    assertContains(response, "Change Your company")
    assertContains(response, "Change Cover")


def test_an_edit_by_the_person_survives_into_the_quote(client, customer, filled_run):
    client.force_login(customer)
    run_id = filled_run.run_id
    confirm_url = filled_run.bound_wizard.entry_url("confirm")
    company_url = reverse(
        "quote-step", kwargs={"run_id": run_id, "gandalf_step": "company"}
    )

    # The agent said twelve employees; the person knows it is twenty.
    edited = client.post(
        company_url,
        data={
            "name": "Analytical Engines Ltd",
            "company_type": "limited",
            "founded": "1837-12-10",
            "employees": "20",
        },
    )

    # The run re-routes from the edit and lands back where it was: every
    # later answer still holds, so nothing else has to be re-entered.
    assertRedirects(edited, confirm_url)
    assertContains(client.get(confirm_url), "20")

    confirmed = client.post(confirm_url, data={"confirmed": "on"})

    assert confirmed.status_code == HTTPStatus.OK
    # 250 base + 20 employees + 2 covers: the person's number, not the
    # agent's. The fleet adds nothing until they list one.
    assertContains(confirmed, "750")
    assertContains(confirmed, "Analytical Engines Ltd")
    assert WizardRun.objects.get(pk=run_id).completed


def test_the_run_the_agent_filled_is_the_run_the_browser_opens(
    client, customer, filled_run
):
    """No export, no copy: one row, reached through two different doors."""
    client.force_login(customer)

    stored = WizardRun.objects.get(pk=filled_run.run_id)

    assert stored.owner == customer
    assert not stored.completed
    response = client.get(filled_run.bound_wizard.entry_url("confirm"))
    assertContains(response, "copilot filled this in for you")


def _step_url(run_id, step):
    return reverse("quote-step", kwargs={"run_id": run_id, "gandalf_step": step})


def test_control_passes_back_and_forth_between_the_agent_and_the_form(
    client, customer, hybrid
):
    """Neither side owns the run. The person starts it, the agent picks it
    up, the person changes their mind in a way that re-routes the whole
    journey, the agent fills the new route, and the person finishes."""
    client.force_login(customer)

    # 1. The person starts it themselves, in the browser.
    started = client.get(reverse("quote"), follow=True)
    run_id = str(WizardRun.objects.get(owner=customer).pk)
    assert started.status_code == HTTPStatus.OK
    client.post(
        _step_url(run_id, "company"),
        data={
            "name": "Analytical Engines Ltd",
            "company_type": "limited",
            "founded": "1837-12-10",
            "employees": "12",
        },
    )

    # 2. They hand over: the agent resumes the run they began.
    agent = RunDriver.resume(
        HybridQuoteViewSet, run_id, request=fabricate_request(user=customer)
    )
    assert agent.describe().step == "registration"
    assert agent.answers()["company"]["name"] == "Analytical Engines Ltd"

    agent.prefill(
        {
            "registration": {
                "companies_house_number": "AE123456",
                "vat_registered": "on",
            },
            "coverage": {
                "cover_types": ["property"],
                "excess": "500",
                "start_date": "2026-09-01",
            },
            "claims": {"had_claims": "no"},
            "contact": {"email": "ada@analyticalengines.example"},
        }
    )
    assert agent.describe().step == "confirm"

    # 3. Back to the person, who changes the one answer that re-routes
    #    everything: a partnership takes a different arm entirely.
    client.post(
        _step_url(run_id, "company"),
        data={
            "name": "Byron & Lovelace",
            "company_type": "partnership",
            "founded": "1833-06-05",
            "employees": "12",
        },
    )

    # 4. The same agent instance sees it — no stale copy of the run.
    assert agent.describe().step == "partners"

    agent.submit({"partner_count": "2"})
    agent.prefill(
        {
            "partner-0": {"full_name": "Ada Lovelace"},
            "partner-1": {"full_name": "George Byron"},
        }
    )

    # Everything answered after the fork survived the re-route.
    answers = agent.answers()
    assert answers["coverage"]["excess"] == "500"
    assert answers["contact"]["email"] == "ada@analyticalengines.example"
    assert agent.describe().step == "confirm"

    # 5. The person has the last word.
    confirmed = client.post(_step_url(run_id, "confirm"), data={"confirmed": "on"})

    assert confirmed.status_code == HTTPStatus.OK
    assertContains(confirmed, "Byron &amp; Lovelace")
    assert WizardRun.objects.get(pk=run_id).completed


def test_an_answer_returns_when_the_person_changes_their_mind_back(
    client, customer, filled_run
):
    """The agent fills a limited company, the person switches to a
    partnership and back again in the browser, and the registration
    answer the agent gave is still there — dormant, not discarded."""
    client.force_login(customer)
    run_id = filled_run.run_id
    company = {
        "name": "Analytical Engines Ltd",
        "founded": "1837-12-10",
        "employees": "12",
    }

    client.post(
        _step_url(run_id, "company"), data={**company, "company_type": "partnership"}
    )
    assert filled_run.describe().step == "partners"

    client.post(
        _step_url(run_id, "company"), data={**company, "company_type": "limited"}
    )

    assert filled_run.answers()["registration"]["companies_house_number"] == "AE123456"
    assert filled_run.describe().step == "confirm"
