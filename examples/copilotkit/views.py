"""The demo's views: an AG-UI endpoint, and a page to point at it.

Serving the protocol is `gandalf.contrib.agent.agui`'s job. What is left
here is what belongs to this demo rather than to any wizard — what the
page already knows about the customer, and somewhere to keep a transcript
once the stream has been watched and is gone.

The response streams, so this must be served over ASGI (see `asgi.py`).
"""

from functools import partial

from django.shortcuts import render
from django.utils import timezone

from examples.copilotkit.agent import build_agent, resolve_model
from examples.copilotkit.transcripts import record
from examples.copilotkit.wizards import (
    HybridIdentityViewSet,
    HybridLicenceViewSet,
    HybridQuoteViewSet,
)
from gandalf.contrib.agent.agui import endpoint_for

agent = build_agent(HybridQuoteViewSet, resolve_model())
licence_agent = build_agent(HybridLicenceViewSet, resolve_model())
identity_agent = build_agent(HybridIdentityViewSet, resolve_model())


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
# The attachments a chat carries are the library's business too — it
# reads them off the same messages the model is about to be shown.
_chat = partial(record, source="chat", model=resolve_model())

agent_endpoint = endpoint_for(agent, instructions=run_instructions, on_complete=_chat)
licence_endpoint = endpoint_for(
    licence_agent, instructions=run_instructions, on_complete=_chat
)
identity_endpoint = endpoint_for(
    identity_agent, instructions=run_instructions, on_complete=record
)


# The same quote wizard as `/agent/`, and the same tools. What differs is
# one sentence: this agent is told it may draw a form instead of asking in
# chat. The form itself is the browser's — the tool arrives with the run
# input, because AG-UI carries the client's tools and pydantic-ai's adapter
# hands them to the model like any other. Nothing in Django renders it, and
# nothing here knows what is on it.
COLLECTING = """\
You have two ways to ask for something, and choosing between them is part
of the job.

Chat is a queue: one question, one answer. That suits a person who knows
what they are doing and wants to say it in a sentence.

`collect_with_a_form` draws a form in the conversation instead — you decide
the fields, their order, their wording, and how each one is asked. Reach for
it when several answers are wanted together, when picking from options beats
describing something, or when somebody has said that going back and forth is
hard for them.

Ask people how they would like to be asked, and believe them. Somebody who
says the words are unfamiliar wants a form that explains them; somebody who
says typing is slow wants things to pick from; somebody who says they want it
over with wants one form with everything on it. Fit what you draw to what
they told you, rather than to a house style.

The answers come back under the names you chose, so use the wizard's own
field names when you mean to place them straight away. Collecting is not
placing: put what comes back into the run with the ordinary tools, and read
the errors if any of it does not hold."""


def adaptive_instructions(run_input):
    return f"{run_instructions(run_input)}\n\n{COLLECTING}"


adaptive_agent = build_agent(HybridQuoteViewSet, resolve_model())
adaptive_endpoint = endpoint_for(
    adaptive_agent, instructions=adaptive_instructions, on_complete=_chat
)


def index(request):
    """A pointer page, for anyone who lands on the Django port directly."""
    return render(request, "hybrid/index.html")
