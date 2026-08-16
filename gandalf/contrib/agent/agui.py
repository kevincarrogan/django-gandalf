"""Serve an agent over AG-UI, from Django itself.

pydantic-ai's adapter has a framework-agnostic path — parse the body,
build the adapter, stream the encoded events — which is what lets an
agent live inside a Django project rather than beside it. One process,
one origin, one database: the run the agent fills is the run the browser
opens, and the handover is a link rather than an export.

The response streams, so this must be served over ASGI.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user
from django.http import HttpRequest, HttpResponseBase, StreamingHttpResponse
from pydantic_ai import Agent
from pydantic_ai.ui import SSE_CONTENT_TYPE
from pydantic_ai.ui.ag_ui import AGUIAdapter

from gandalf.contrib.agent.deps import WizardDeps, WizardState, attachments_from
from gandalf.driver import fabricate_request


def endpoint_for(
    agent: Agent[WizardDeps, Any],
    *,
    instructions: Callable[[Any], str] | None = None,
    on_complete: Callable[..., Any] | None = None,
) -> Callable[[HttpRequest], Any]:
    """A Django view serving `agent`: one POST in, a stream of events out.

    A factory rather than a class-based view because there is nothing to
    override — what varies between two of these is which agent they were
    built against, and that is an argument.

    `instructions` is handed the `RunAgentInput` and returns anything the
    model should be told for this run only. The AG-UI protocol carries
    page context in `RunAgentInput.context`, and pydantic-ai's adapter
    does not forward it to the model, so an agent that is *shown* the
    customer's profile still asks for it. This is where that gap closes.

    `on_complete` receives the finished run. The stream is watched once
    and gone, so anything wanting to keep what was said has to ask here.
    """

    async def view(request: HttpRequest) -> HttpResponseBase:
        # Resolve the user before streaming: the driver runs the wizard as
        # this person, and lazy user resolution is not safe to touch from
        # the event loop.
        user = await sync_to_async(get_user)(request)
        run_input = AGUIAdapter.build_run_input(request.body)
        adapter = AGUIAdapter(
            agent=agent,
            run_input=run_input,
            accept=request.headers.get("accept"),
        )
        # Fresh state per request: the adapter writes the client's state
        # into these deps, so a shared instance would leak one chat into
        # another. The attachments are read off the same messages the
        # model is about to be shown — it sees the picture, and the tools
        # get the bytes, without either passing through the other.
        deps = WizardDeps(
            state=WizardState(),
            request=fabricate_request(user=user),
            attachments=attachments_from(run_input.messages),
        )
        return StreamingHttpResponse(
            adapter.encode_stream(
                adapter.run_stream(
                    deps=deps,
                    instructions=instructions(run_input) if instructions else None,
                    on_complete=on_complete,
                )
            ),
            content_type=SSE_CONTENT_TYPE,
        )

    # Set rather than decorated: `csrf_exempt` wraps the view in a *sync*
    # function, which would leave this coroutine unawaited. A chat posts
    # JSON from a script, so it carries no form token — the wizard's own
    # pages, which do, keep full CSRF protection.
    view.csrf_exempt = True  # type: ignore[attr-defined]
    return view
