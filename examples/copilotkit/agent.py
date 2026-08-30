"""The demo's agent: `gandalf.contrib.agent`, plus what is demo-specific.

Almost everything that used to be here is now in the library. What is
left is the three things a demo wants and a library should not have an
opinion about: which model to talk to, that every tool call is written to
an event log, whose answers the agent may change — and the fact that all
three are wired the same way for every wizard in this project.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from pydantic_ai import Agent
from pydantic_ai.toolsets import CombinedToolset, WrapperToolset

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


THEIR_ANSWERS = """\
A step the person answered themselves is theirs to change, not yours.
Anything you placed you may still change — correcting your own answers is
expected, and one that failed validation is fixed by replacing it. An
answer of theirs stays as they left it, and putting a document on one of
their steps counts as changing it. When something they answered needs to
change, tell them what you would change and why, and give them the link to
that step so they can do it themselves."""


@dataclass
class TheirAnswersToolset(WrapperToolset[WizardDeps]):
    """A step somebody answered themselves is theirs, whole.

    Submitting a form affirms everything on it, so an agent changing one
    field of somebody's step re-affirms the rest in their name. This
    refuses any call that would place something at such a step — an edit or
    a document, since both are placements — and hands back the link to it
    instead: the agent says what it would put there and lets them do it.

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

    async def get_instructions(self, ctx):
        """Say the rule as well as enforce it.

        A refusal an agent can predict is one it can explain. Told nothing,
        it learns the rule by being refused and reports a tool that said
        no; told it, it does the thing the rule is for — says what it would
        change and hands over the link — first time.

        Said here rather than in the demo's other instructions so that the
        words and the rule cannot drift apart: they are the same object,
        and taking the wrapper away takes the sentence with it. The library
        cannot say it, because the library has no such rule.
        """
        inherited = await super().get_instructions(ctx)
        if inherited is None:
            return THEIR_ANSWERS
        if isinstance(inherited, Sequence) and not isinstance(inherited, str):
            return [*inherited, THEIR_ANSWERS]
        return [inherited, THEIR_ANSWERS]

    async def call_tool(self, name, tool_args, ctx, tool):
        # Asked of the step a call names rather than of the tool's name,
        # because naming a step is what placing an answer at one looks
        # like: `edit_step` does it, and so does `attach_document`, where a
        # photograph put over somebody's own is the same act as changing a
        # field of their step — and worse, since a placement replaces the
        # metadata beside it and would relabel their answer as the agent's.
        # A call naming no step can only place at the cursor, which is by
        # definition a step nobody has answered.
        step = tool_args.get("step") if tool_args else None
        if step is not None:
            # Off the event loop, because reading the run is ordinary
            # Django and Django refuses to be ordinary in an async context.
            # The tools this wraps are sync for the same reason; they are
            # only spared this because pydantic-ai calls them in a thread.
            refusal = await sync_to_async(self._refusal)(ctx, step)
            if refusal is not None:
                return refusal
        return await super().call_tool(name, tool_args, ctx, tool)

    def _refusal(self, ctx, step):
        """What to say instead of placing this, or None to allow it."""
        run_id = ctx.deps.state.run_id
        if run_id is None:
            # Whatever is wrong with a call made against no run, the tool
            # says it better than a policy can.
            return None
        driver = RunDriver.resume(self.viewset_class, run_id, context=ctx.deps.context)
        placement = driver.placements().get(step)
        if placement is None or placement.metadata.get("unattended"):
            return None
        return {
            "refused": True,
            "step": step,
            "reason": (
                "They answered this step themselves, so it is theirs whole: "
                "submitting a form affirms every field on it, and placing "
                "anything on it now would re-affirm the rest in their name. "
                "Nothing was changed."
            ),
            "instead": (
                "Tell them what you would put there and why, and give them "
                "this link as a markdown link so they can do it themselves."
            ),
            "change_url": driver.run.entry_url(step),
        }


def build_agent(
    viewset_class: type[WizardViewSet], model: Any, extra: Any = None
) -> Agent[WizardDeps, str]:
    """The library's agent for `viewset_class`, with this demo's logging and
    its edit rule.

    `extra` is a toolset of this demo's own, for a wizard that needs a verb
    the library does not have — the fleet, which is a second collection of
    runs rather than a step of this one. It goes *beside* the wizard tools
    rather than inside the wrapper: the rule the wrapper enforces is about
    re-affirming a step somebody answered, and a tool that touches a
    different run entirely has no step here to re-affirm.
    """

    def wrap(toolset):
        # Logging outermost, so a refused call is written to the event log
        # like any other; the rule inside it, next to the call it refuses.
        wrapped = LoggedToolset(TheirAnswersToolset(toolset, viewset_class))
        if extra is None:
            return wrapped
        return CombinedToolset([wrapped, extra])

    return build_wizard_agent(viewset_class, model, wrap=wrap)
