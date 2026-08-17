"""The identity check: a wizard filled from a document it never keeps.

Needs the `agents` dependency group (`just test-agents`); skips otherwise.

The case with nothing to do with uploads. `IdentityCheckViewSet` has no
`FileField`, so there is nowhere to put a document and no tool to put one
anywhere — and it is still the wizard a photograph is most useful to,
because the four things printed on a driving licence are exactly what its
five pages ask for.
"""

import pytest

pytest.importorskip("ag_ui")

from examples.copilotkit.agent import build_agent  # noqa: E402
from examples.identity import IdentityCheckViewSet  # noqa: E402
from gandalf.driver import RunDriver, fabricate_request  # noqa: E402


def _agent_tools(agent):
    """The wizard's tools, through however many wrappers the demo has put
    round them — it wraps for logging and again for its edit rule, and how
    many layers there are is not what this is about."""
    toolset = next(t for t in agent.toolsets if hasattr(t, "wrapped"))
    while hasattr(toolset, "wrapped"):
        toolset = toolset.wrapped
    return toolset.tools


def test_a_wizard_with_no_file_step_still_reads_and_fills(isolated_media_root):
    """The case that has nothing to do with uploads.

    `IdentityCheckViewSet` has no `FileField`, so there is nowhere to put
    a document and no tool to put one anywhere. The four fields printed on
    the card are still ordinary strings, and that is all the agent has to
    submit.
    """
    agent = build_agent(IdentityCheckViewSet, "test")
    assert "attach_document" not in _agent_tools(agent)

    driver = RunDriver.begin(IdentityCheckViewSet, request=fabricate_request())
    result = driver.prefill(
        {
            "name": {"first_name": "Ada", "surname": "Carrogan"},
            "date-of-birth": {"date_of_birth": "1986-08-16"},
            "licence-number": {"licence_number": "CARRO806161K99AB"},
            "address": {
                "address_line_1": "12 Analytical Way",
                "town": "London",
                "postcode": "N1 1AA",
            },
        }
    )

    # Four pages a person would have typed, filled in one pass from what
    # one photograph said, and stopping where it should.
    assert result.placed == ["name", "date-of-birth", "licence-number", "address"]
    assert result.next_step == "confirm"
    assert not result.complete
    assert all(not p.files for p in driver.placements().values())
