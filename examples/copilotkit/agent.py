"""The demo's agent: `gandalf.contrib.agent`, plus what is demo-specific.

Almost everything that used to be here is now in the library. What is
left is the three things a demo wants and a library should not have an
opinion about: which model to talk to, that every tool call is written to
an event log, and the fact that both are wired the same way for every
wizard in this project.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.toolsets import WrapperToolset

from examples.eventlog import log_event
from gandalf.contrib.agent import WizardDeps, build_agent as build_wizard_agent
from gandalf.viewsets import WizardViewSet


def resolve_model() -> str:
    """The demo's model: whatever is configured, else a real one if a key
    is present, else pydantic-ai's canned `test` model so the wiring runs
    anywhere.

    Anthropic is this demo's choice and nothing more — `contrib` names no
    provider, and `GANDALF_AGENT_MODEL` takes any string pydantic-ai
    understands.
    """
    configured = os.environ.get("GANDALF_AGENT_MODEL")
    if configured:
        return configured
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic:claude-sonnet-5"
    return "test"


class LoggedToolset(WrapperToolset[WizardDeps]):
    """Every tool call, recorded as it happens.

    Wrapping rather than logging inside each tool: there is one place a
    call goes through, the tools stay about the wizard, and a tool added
    later is instrumented for free. This is what `build_agent`'s `wrap`
    hook exists for — the library has no business writing to this demo's
    event log, and this has no business reimplementing its tools.
    """

    async def call_tool(self, name, tool_args, ctx, tool):
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as error:
            log_event(
                "tool",
                tool=name,
                args=tool_args,
                outcome=type(error).__name__,
                detail=str(error),
            )
            raise
        value = getattr(result, "return_value", result)
        log_event("tool", tool=name, args=tool_args, outcome="ok", returned=value)
        return result


def build_agent(
    viewset_class: type[WizardViewSet], model: Any
) -> Agent[WizardDeps, str]:
    """The library's agent for `viewset_class`, with this demo's logging."""
    return build_wizard_agent(viewset_class, model, wrap=LoggedToolset)
