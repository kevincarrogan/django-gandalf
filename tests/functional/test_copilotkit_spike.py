"""The AG-UI stream the browser chat consumes, driven deterministically.

Needs the `agents` dependency group (`just test-agents`); skips otherwise.
A scripted streaming `FunctionModel` stands in for the LLM (the AG-UI
adapter always streams, so a plain `FunctionModel` function is not
enough). What is proved here is the wiring: real AG-UI events out,
including the state snapshots the wizard panel renders from, for the
whole value story — outline the fourteen-step insurance wizard, prefill
everything a business profile answers in one call, stop for a human.
"""

import asyncio
import json

import pytest

pytest.importorskip("ag_ui")

from ag_ui.core import Context, RunAgentInput, UserMessage  # noqa: E402
from pydantic_ai.models.function import DeltaToolCall, FunctionModel  # noqa: E402
from django.utils import timezone  # noqa: E402
from pydantic_ai.ui.ag_ui import AGUIAdapter  # noqa: E402

from examples.copilotkit.agent import build_agent  # noqa: E402
from gandalf.contrib.agent import WizardDeps, WizardState  # noqa: E402
from examples.copilotkit.views import run_instructions  # noqa: E402
from examples.insurance import InsuranceQuoteViewSet  # noqa: E402

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


def _scripted_stream_model(calls):
    """A streaming model that plays `calls` (tool name, args) in order,
    then says it has finished."""
    queue = iter(calls)

    async def stream(messages, info):
        try:
            tool_name, args = next(queue)
        except StopIteration:
            yield "finished"
            return
        yield {0: DeltaToolCall(name=tool_name, json_args=json.dumps(args))}

    return FunctionModel(stream_function=stream)


def _run_agui(agent, model, prompt, context=()):
    """POST-equivalent: one AG-UI run, returned as its encoded event stream.

    Mirrors the Django view, including the run-level instructions it
    builds — that is where page context is injected."""
    run_input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        state={},
        messages=[UserMessage(id="1", content=prompt)],
        tools=[],
        context=list(context),
        forwarded_props=None,
    )

    async def collect():
        adapter = AGUIAdapter(
            agent=agent, run_input=run_input, accept="text/event-stream"
        )
        with agent.override(model=model):
            deps = WizardDeps(state=WizardState())
            return "".join(
                [
                    chunk
                    async for chunk in adapter.encode_stream(
                        adapter.run_stream(
                            deps=deps, instructions=run_instructions(run_input)
                        )
                    )
                ]
            )

    return asyncio.run(collect())


def test_the_ag_ui_stream_carries_wizard_state_snapshots():
    agent = build_agent(InsuranceQuoteViewSet, "test")
    model = _scripted_stream_model(
        [
            ("start_run", {}),
            ("get_outline", {}),
            ("prefill", {"answers": PROFILE_ANSWERS}),
        ]
    )

    body = _run_agui(
        agent,
        model,
        "Get me a quote: property and vehicle cover, £500 excess, "
        "starting 1 September.",
    )

    # The shared-state channel the browser panel renders from.
    assert "STATE_SNAPSHOT" in body
    # One prefill placed the whole profile: both branches and the grown
    # fleet member show up in the streamed snapshots.
    for step in PROFILE_ANSWERS:
        assert step in body
    # It stops at the confirmation rather than answering it.
    assert "confirm" in body
    assert "RUN_FINISHED" in body


def test_page_context_reaches_the_model():
    """The bug this guards: AG-UI carries the page's context, but
    pydantic-ai's adapter does not forward it, so an agent shown the
    customer's profile still asked for the customer's name. The view turns
    that context into run-level instructions; this proves the model sees
    it."""
    seen = []

    async def stream(messages, info):
        seen.append(repr(messages))
        yield "noted"

    agent = build_agent(InsuranceQuoteViewSet, "test")
    profile = json.dumps({"company_name": "Analytical Engines Ltd", "employees": 12})

    _run_agui(
        agent,
        FunctionModel(stream_function=stream),
        "Get me a quote.",
        context=[Context(description="The customer's business profile", value=profile)],
    )

    assert seen
    assert "Analytical Engines Ltd" in seen[0]
    assert "business profile" in seen[0]


def test_the_run_instructions_tell_the_model_todays_date():
    """A model with no clock guessed 2025 for "1 September"."""
    run_input = RunAgentInput(
        thread_id="t",
        run_id="r",
        state={},
        messages=[UserMessage(id="1", content="hi")],
        tools=[],
        context=[],
        forwarded_props=None,
    )

    assert timezone.localdate().isoformat() in run_instructions(run_input)


def test_the_suite_never_reaches_a_real_model():
    """No test calls an LLM for real. This pins the guard that keeps it
    that way when a developer has an API key in their environment."""
    from examples.copilotkit.agent import resolve_model

    assert resolve_model() == "test"
