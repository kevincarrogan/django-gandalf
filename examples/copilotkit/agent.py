"""The demo's agent: `gandalf.contrib.agent`, plus what is demo-specific.

Almost everything that used to be here is now in the library. What is
left is the three things a demo wants and a library should not have an
opinion about: which model to talk to, that every tool call is written to
an event log, and the fact that both are wired the same way for every
wizard in this project.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from pydantic_ai import Agent
from pydantic_ai.toolsets import WrapperToolset

from examples.eventlog import log_event
from gandalf.contrib.agent import WizardDeps, build_agent as build_wizard_agent
from gandalf.driver import RunDriver
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


@dataclass
class TheirAnswersToolset(WrapperToolset[WizardDeps]):
    """A step somebody answered themselves is theirs, whole.

    Submitting a form affirms everything on it, so an agent changing one
    field of somebody's step re-affirms the rest in their name. This
    refuses that edit and hands back the link to the step instead: the
    agent says what it would change and lets them change it.

    An answer the *agent* placed it may still replace, whatever else the
    rule says — that is how it recovers from one that failed validation.
    `RunDriver` marks its own placements `{"unattended": True}`, which is
    the whole of what this asks.

    It is this demo's rule and not the library's: `gandalf.contrib.agent`
    records who placed each answer and refuses nothing, because whose an
    answer is is a question about a domain. `build_agent`'s `wrap` hook is
    where a domain answers it. The cost is one read of the run before the
    tool makes its own; a rule that has to be right is worth a walk.
    """

    viewset_class: type[WizardViewSet]

    async def call_tool(self, name, tool_args, ctx, tool):
        if name == "edit_step":
            # Off the event loop, because reading the run is ordinary
            # Django and Django refuses to be ordinary in an async context.
            # The tools this wraps are sync for the same reason; they are
            # only spared this because pydantic-ai calls them in a thread.
            refusal = await sync_to_async(self._refusal)(ctx, tool_args.get("step"))
            if refusal is not None:
                return refusal
        return await super().call_tool(name, tool_args, ctx, tool)

    def _refusal(self, ctx, step):
        """What to say instead of making this edit, or None to allow it."""
        run_id = ctx.deps.state.run_id
        if run_id is None or step is None:
            # No run or no step named: whatever is wrong with the call, the
            # tool says it better than a policy can.
            return None
        driver = RunDriver.resume(self.viewset_class, run_id, request=ctx.deps.request)
        placement = driver.placements().get(step)
        if placement is None or placement.metadata.get("unattended"):
            return None
        return {
            "refused": True,
            "step": step,
            "reason": (
                "They answered this step themselves, so it is theirs whole: "
                "submitting a form affirms every field on it, and changing "
                "one would re-affirm the rest in their name. Nothing was "
                "changed."
            ),
            "instead": (
                "Tell them what you would change and why, and give them this "
                "link as a markdown link so they can change it themselves."
            ),
            "change_url": driver.bound_wizard.entry_url(step),
        }


def build_agent(
    viewset_class: type[WizardViewSet], model: Any
) -> Agent[WizardDeps, str]:
    """The library's agent for `viewset_class`, with this demo's logging and
    its edit rule."""

    def wrap(toolset):
        # Logging outermost, so a refused call is written to the event log
        # like any other; the rule inside it, next to the call it refuses.
        return LoggedToolset(TheirAnswersToolset(toolset, viewset_class))

    return build_wizard_agent(viewset_class, model, wrap=wrap)
