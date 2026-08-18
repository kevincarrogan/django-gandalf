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
from typing import Any, cast

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user
from django.http import HttpRequest, HttpResponseBase, StreamingHttpResponse
from pydantic_ai import Agent
from pydantic_ai.ui import SSE_CONTENT_TYPE
from pydantic_ai.ui.ag_ui import AGUIAdapter

from gandalf.contrib.agent.deps import WizardDeps, WizardState, attachments_from
from gandalf.context import WizardContext, WizardSession


def _ensure_addressable(session: Any) -> None:
    """Give the session a key now, while a cookie can still be sent.

    A session key reaches the browser on a `Set-Cookie` header, and
    `SessionMiddleware` writes that header when the view returns — which
    here is before the stream has produced a single event. A visitor
    whose first act is to open the chat has no key yet, so a run the
    agent saved under one created mid-stream would be saved under a key
    nobody could ever ask for: the same run lost, one step further along.

    Creating it up front puts the key in the response the browser is
    already reading, and every write the tools make lands under it.
    Nothing is stored for a session that stays unused beyond the empty
    record, and a visitor who already has a key — anyone signed in — does
    not come through here at all.
    """
    if session.session_key is None:
        session.create()


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

    The agent is given the browser's session, so the shipped
    `SessionStorage` shows it the runs the person themselves started. One
    setting has to hold for that: `SESSION_ENGINE` must keep the session
    server-side (`db`, `cache`, `cached_db`, `file`). A cookie session is
    written by a response header, and this response's headers are long
    gone by the time a tool answers a step — reads work, writes do not
    survive the request. Storage that scopes by `actor` rather than by
    session is unaffected either way.
    """

    async def view(request: HttpRequest) -> HttpResponseBase:
        # Resolve the user before streaming: the driver runs the wizard as
        # this person, and lazy user resolution is not safe to touch from
        # the event loop.
        user = await sync_to_async(get_user)(request)
        # Same reason, one step further: the session's cookie can only go
        # out with the headers, and those leave before the first tool runs.
        await sync_to_async(_ensure_addressable)(request.session)
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
        #
        # The session is the browser's own, which is what lets the agent
        # see a run the person started under the shipped `SessionStorage`
        # rather than a throwaway one nobody will ever read. It is the
        # same trust as `actor`: this is already running as them.
        #
        # The session and not the request, though. `context.request` says
        # a browser is driving *this walk*, and what is here is a POST to
        # a chat endpoint — wrong path, JSON body, no form token — which
        # is not the request a step's view should be dispatched with.
        # Its absence is also how `WizardContext` knows to write the
        # session back itself: see `persist()`, and note that a
        # cookie-backed session cannot be, because this response streams.
        #
        # Touching `request.session` here loads nothing — the middleware
        # attached the store, and reading a key is what opens it, which
        # the tools do from a worker thread rather than the event loop.
        deps = WizardDeps(
            state=WizardState(),
            context=WizardContext(
                actor=user,
                # Cast as `WizardContext.session` casts: django-stubs
                # gives `SessionBase.get` overloads that no protocol
                # written with a default argument can match.
                session=cast(WizardSession, request.session),
            ),
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
