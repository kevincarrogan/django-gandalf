"""The demo's task list, driven and then handed over.

The handover one level up. `test_hybrid_handoff` proves it for one wizard:
an agent fills the run, the person opens the same run in a browser, changes
what is wrong and confirms. An application is four of those on a page, and
what is new is everything that belongs to the *page* rather than to a run —
which parts there are, which one is waiting on another, and a submit that
only the person presses.

No model is called. Reaching the demo's page imports the module that serves
it, which needs the `agents` dependency group (`just test-agents`).
"""

from http import HTTPStatus

import pytest

pytest.importorskip("pydantic_ai")

from django.contrib.auth import get_user_model  # noqa: E402
from django.urls import reverse  # noqa: E402
from pytest_django.asserts import assertContains  # noqa: E402

from examples.copilotkit import settings as hybrid_settings  # noqa: E402
from examples.copilotkit.application import ApplicationViewSet  # noqa: E402
from gandalf.contrib.agent import WizardDeps, WizardState  # noqa: E402
from gandalf.contrib.agent import build_journey_toolset  # noqa: E402
from gandalf.driver import JourneyDriver  # noqa: E402
from gandalf.viewsets import DoorRefused  # noqa: E402

IDENTITY = {
    "name": {"first_name": "Ada", "surname": "Lovelace"},
    "date-of-birth": {"date_of_birth": "1815-12-10"},
    "licence-number": {"licence_number": "LOVEL812105AL9AB"},
    "address": {
        "address_line_1": "12 Analytical Way",
        "town": "London",
        "postcode": "SW1A 1AA",
    },
}


@pytest.fixture
def hybrid(settings):
    settings.ROOT_URLCONF = "examples.copilotkit.urls"
    settings.TEMPLATES = hybrid_settings.TEMPLATES
    return settings


@pytest.fixture
def customer(db):
    return get_user_model().objects.create(username="demo")


@pytest.fixture
def journey(hybrid, customer):
    return JourneyDriver.begin(ApplicationViewSet, actor=customer)


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


def _tools(journey):
    toolset = build_journey_toolset(ApplicationViewSet)
    tools = {name: tool.function for name, tool in toolset.tools.items()}
    ctx = _Ctx(
        WizardDeps(
            state=WizardState(journey_id=journey.journey_id),
            context=journey.context,
            attachments={},
        )
    )
    return tools, ctx


def test_the_agent_sees_the_same_four_parts_the_page_shows(journey):
    tools, ctx = _tools(journey)

    result = tools["get_application"](ctx)

    assert [row["key"] for row in result.return_value["rows"]] == [
        "identity",
        "licence",
        "fleet",
        "cover",
    ]


def test_the_part_waiting_on_another_is_refused_until_that_one_is_done(journey):
    """The rule this demo exists for. There is no tool that overrides it,
    so the only way through is to do the other part first — which is what
    the person's page tells them too."""
    tools, ctx = _tools(journey)

    with pytest.raises(Exception, match="finished first"):
        tools["get_part"](ctx, "cover")


def test_filling_the_part_it_waits_on_opens_it(journey, customer):
    tools, ctx = _tools(journey)
    tools["fill_part"](ctx, "identity", IDENTITY)

    # Filling is not finishing: the person confirms the part, and only then
    # does the gate open.
    identity = journey.section("identity", may_finish=True)
    identity.submit({"confirmed": True})
    identity.finish()

    assert tools["get_part"](ctx, "cover").return_value["step"] == "company"


def test_a_vehicle_goes_on_the_list_one_at_a_time(journey):
    """One call, one vehicle. It reads as *Vehicle 1* until the person
    confirms it — an item takes its title from its own answers when it is
    finished, and finishing is theirs — but the answers are on it."""
    tools, ctx = _tools(journey)

    result = tools["add_to_list"](
        ctx, "fleet", {"vehicle": {"registration": "AE 1837", "value": "12000"}}
    )

    assert len(journey.items("fleet").rows) == 1
    assert result.return_value["part"]["answers"]["vehicle"] == {
        "registration": "AE 1837",
        "value": 12000,
    }


def test_the_agent_cannot_submit_the_application(journey):
    """`journey_done()` prices it and records it, so the person presses
    that button. The toolset has no tool for it at all — there is nothing
    to refuse, which is the strongest form of the rule."""
    tools, _ = _tools(journey)

    assert not {name for name in tools if "submit" in name}


def test_the_page_the_agent_hands_over_is_the_page_the_person_opens(
    client, customer, journey
):
    tools, ctx = _tools(journey)
    tools["fill_part"](ctx, "identity", IDENTITY)
    url = tools["handoff"](ctx).return_value["handoff_url"]

    client.force_login(customer)
    response = client.get(url)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, "Business insurance application")
    # The part the agent filled reads as theirs to confirm, and the one
    # waiting on it says so rather than offering a link.
    assertContains(response, "tag--incomplete")
    assertContains(response, "tag--blocked")


def test_the_page_refuses_its_own_button_until_every_part_is_confirmed(
    client, customer, journey
):
    client.force_login(customer)

    response = client.get(journey.url)

    assertContains(response, "disabled")
    assert not journey.is_complete


def test_a_part_the_page_will_not_open_refuses_the_driver_as_well(journey):
    with pytest.raises(DoorRefused):
        journey.section("cover")


def test_the_application_is_one_the_browser_can_reach_by_url(client, customer, journey):
    """Durably stored and scoped to the person, so what the agent filled is
    what they open — the same guarantee the single wizards make."""
    tools, ctx = _tools(journey)
    tools["fill_part"](ctx, "identity", IDENTITY)

    client.force_login(customer)
    response = client.get(reverse("application"))

    assert response.status_code == HTTPStatus.OK
