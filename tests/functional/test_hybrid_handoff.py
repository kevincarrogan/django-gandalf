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
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.urls import reverse  # noqa: E402
from pytest_django.asserts import assertContains, assertRedirects  # noqa: E402

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

from examples.copilotkit import settings as hybrid_settings  # noqa: E402
from examples.copilotkit.agent import build_agent  # noqa: E402
from examples.copilotkit.wizards import (  # noqa: E402
    HybridLicenceViewSet,
    HybridQuoteViewSet,
)
from gandalf.context import WizardContext
from gandalf.contrib.agent import Attachment, WizardDeps, WizardState  # noqa: E402
from gandalf.driver import RunDriver  # noqa: E402
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
    driver = RunDriver.begin(HybridQuoteViewSet, actor=customer)
    result = driver.prefill(PROFILE_ANSWERS)
    assert result.next_step == "confirm"
    return driver


def test_the_person_lands_on_their_answers_and_can_change_any_of_them(
    client, customer, filled_run
):
    client.force_login(customer)

    response = client.get(filled_run.run.entry_url("confirm"))

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
    confirm_url = filled_run.run.entry_url("confirm")
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
    response = client.get(filled_run.run.entry_url("confirm"))
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
    agent = RunDriver.resume(HybridQuoteViewSet, run_id, actor=customer)
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


# --- A step somebody answered is theirs, whole -------------------------
#
# The demo's edit rule. The library refuses nothing — `contrib.agent` hands
# out who placed each answer and stops there, because whose an answer is is
# a question about a domain rather than about wizards — so the rule lives in
# the wrapper this demo puts round the toolset, and is proved through the
# demo's own agent rather than by calling the wrapper directly.


COMPANY = {
    "name": "Analytical Engines Ltd",
    "company_type": "limited",
    "founded": "1837-12-10",
    "employees": "12",
}


def _scripted_model(calls):
    """A model that plays `(tool, args)` in order, then stops talking. What
    is under test is what the call does to the run, not that a model can be
    told to make one."""
    queue = iter(calls)

    def respond(messages, info):
        try:
            name, args = next(queue)
        except StopIteration:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart(name, args)])

    return FunctionModel(respond)


def _agent_turn(customer, calls, viewset_class=HybridQuoteViewSet, attachments=None):
    """One turn of the demo's agent — its wrapping included, since the rule
    under test lives there rather than in a tool."""
    if attachments is None:
        attachments = {}
    agent = build_agent(viewset_class, "test")
    deps = WizardDeps(
        state=WizardState(),
        context=WizardContext(actor=customer),
        attachments=attachments,
    )
    with agent.override(model=_scripted_model(calls)):
        return agent.run_sync("Put the employee count up to twenty.", deps=deps)


@pytest.fixture
def committed_customer(transactional_db):
    """The agent's tools run in a worker thread, so the run they read has to
    be committed rather than held open in a test transaction."""
    return get_user_model().objects.create(username="demo")


@pytest.fixture
def their_run(hybrid, committed_customer):
    """A run carrying one answer the person made themselves — which is what
    `metadata={}` says: a browser records nothing about a placement."""
    driver = RunDriver.begin(HybridQuoteViewSet, actor=committed_customer)
    driver.submit(COMPANY, metadata={})
    return driver


def test_the_agent_cannot_overwrite_an_answer_the_person_made(
    committed_customer, their_run
):
    """Submitting a form affirms everything on it, so an agent changing one
    field of somebody's step re-affirms the rest on their behalf."""
    result = _agent_turn(
        committed_customer,
        [
            ("resume_run", {"run_id": their_run.run_id}),
            ("edit_step", {"step": "company", "data": {"employees": "20"}}),
        ],
    )

    # Nothing was placed: the answer is the one they gave.
    assert their_run.answers()["company"]["employees"] == 12
    # And the agent is redirected rather than blocked — it is told where
    # they can make the change themselves.
    said = repr(result.all_messages())
    assert "answered this step themselves" in said
    assert _step_url(their_run.run_id, "company") in said


def test_the_agent_may_still_correct_its_own_earlier_answer(hybrid, committed_customer):
    """The case the rule must not catch: recovering from an answer it got
    wrong means replacing one of its own, and every retry loop needs it."""
    driver = RunDriver.begin(HybridQuoteViewSet, actor=committed_customer)
    driver.submit(COMPANY)

    _agent_turn(
        committed_customer,
        [
            ("resume_run", {"run_id": driver.run_id}),
            ("edit_step", {"step": "company", "data": {"employees": "20"}}),
        ],
    )

    assert driver.answers()["company"]["employees"] == 20


def test_the_agent_cannot_put_a_document_over_the_one_the_person_gave(
    hybrid, committed_customer, isolated_media_root
):
    """The same rule through the other door that places an answer.

    An attachment names a step just as an edit does, and a photograph put
    over somebody's own re-affirms their step exactly the way changing a
    field of it would — with the added cost that a placement replaces the
    metadata beside it, so an unguarded attach would relabel their answer as
    the agent's and open every later edit to it.
    """
    driver = RunDriver.begin(HybridLicenceViewSet, actor=committed_customer)
    driver.submit(
        {},
        files={"scan": SimpleUploadedFile("theirs.png", b"theirs", "image/png")},
        metadata={},
    )

    result = _agent_turn(
        committed_customer,
        [
            ("resume_run", {"run_id": driver.run_id}),
            (
                "attach_document",
                {"attachment_id": "attachment-1", "field": "scan", "step": "scan"},
            ),
        ],
        viewset_class=HybridLicenceViewSet,
        attachments={
            "attachment-1": Attachment(
                id="attachment-1",
                name="mine.png",
                media_type="image/png",
                data=b"mine",
            )
        },
    )

    placement = driver.placements()["scan"]
    assert driver.open_file(placement.files["scan"]).read() == b"theirs"
    # And it is still theirs: the placement was refused, so nothing
    # relabelled it.
    assert placement.metadata == {}
    assert "answered this step themselves" in repr(result.all_messages())


def test_the_agent_is_told_the_rule_rather_than_only_refused_by_it():
    """A refusal it can predict is one it can explain. Told nothing, the
    agent learns the rule by trying and reports a tool that said no; told
    it, it says what it would change and hands over the link — which is
    what the rule is for, and is only ever done well by an agent that knew
    before it opened its mouth.

    The wrapper says it, so the words and the rule cannot drift apart: take
    the wrapper away and the sentence goes with it.
    """
    seen = []

    def respond(messages, info):
        seen.append(repr(messages))
        return ModelResponse(parts=[TextPart("noted")])

    agent = build_agent(HybridQuoteViewSet, "test")
    with agent.override(model=FunctionModel(respond)):
        agent.run_sync("Hello", deps=WizardDeps(state=WizardState()))

    assert seen
    # The rule...
    assert "theirs to change" in seen[0]
    # ...and the half of it that keeps the agent useful.
    assert "your own" in seen[0]
