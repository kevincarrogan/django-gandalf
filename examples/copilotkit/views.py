"""The demo's views: an AG-UI endpoint, and a page to point at it.

Serving the protocol is `gandalf.contrib.agent.agui`'s job. What is left
here is what belongs to this demo rather than to any wizard — what the
page already knows about the customer, and somewhere to keep a transcript
once the stream has been watched and is gone.

The response streams, so this must be served over ASGI (see `asgi.py`).
"""

from django.shortcuts import render
from django.utils import timezone

from examples.copilotkit.agent import (
    build_agent,
    resolve_model,
)
from examples.copilotkit.transcripts import record
from examples.copilotkit.wizards import HybridQuoteViewSet
from gandalf.contrib.agent.agui import endpoint_for

agent = build_agent(HybridQuoteViewSet, resolve_model())


def run_instructions(run_input):
    """Turn what the page knows into instructions for this run.

    The AG-UI protocol carries page context in `RunAgentInput.context` —
    what CopilotKit's `useAgentContext` publishes — but pydantic-ai's
    adapter does not forward it to the model, so an agent that is *shown*
    the customer's profile still asks for it. Passing it as run-level
    instructions (which combine with the agent's own) is what closes that
    gap. Today's date goes in for the same reason: a model with no clock
    guesses at "the first of September".
    """
    return context_instructions(run_input.context or ())


def context_instructions(items):
    """The same, from the context items alone — so anything driving this
    agent without an HTTP request (an evaluation, a script) gives it what
    the browser would."""
    lines = [f"Today's date is {timezone.localdate().isoformat()}."]
    for item in items:
        lines.append(f"{item.description}: {item.value}")
    if len(lines) > 1:
        lines.append(
            "That is already known about them — use it, and never ask them "
            "for anything it answers."
        )
    return "\n".join(lines)


# The library serves the protocol; the demo supplies what is its own.
agent_endpoint = endpoint_for(agent, instructions=run_instructions, on_complete=record)


def index(request):
    """A pointer page, for anyone who lands on the Django port directly."""
    return render(request, "hybrid/index.html")
