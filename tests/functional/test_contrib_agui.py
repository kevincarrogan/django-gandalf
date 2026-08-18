"""The AG-UI endpoint, exercised as a real Django request.

Needs the `agent` extra; skips otherwise.

A scripted `FunctionModel` stands in for the LLM, because the AG-UI
adapter always streams and a plain function is not enough. What is proved
here is the wiring — a POST in, encoded events out, run in the database —
rather than anything about a model.
"""

import asyncio
import json
import types

import pytest

pytest.importorskip("ag_ui")

from ag_ui.core import RunAgentInput, UserMessage  # noqa: E402
from django.test import AsyncClient, override_settings  # noqa: E402
from django.urls import path  # noqa: E402
from pydantic_ai.models.function import DeltaToolCall, FunctionModel  # noqa: E402

from gandalf.contrib.agent import build_agent  # noqa: E402
from gandalf.contrib.agent.agui import endpoint_for  # noqa: E402
from gandalf.driver import RunDriver  # noqa: E402
from gandalf.testing import stored_runs  # noqa: E402
from tests.testapp.views import WalkCountingWizardViewSet  # noqa: E402


def _model(reply="Started."):
    """A model that starts a run and then says something."""
    calls = {"n": 0}

    async def stream(messages, info):
        calls["n"] += 1
        if calls["n"] == 1:
            yield {0: DeltaToolCall(name="start_run", json_args="{}")}
        else:
            yield reply

    return FunctionModel(stream_function=stream)


def _resuming_model(run_id):
    """A model that picks up the run it is told about, and nothing else."""

    async def stream(messages, info):
        if not any(part.part_kind == "tool-return" for part in messages[-1].parts):
            yield {
                0: DeltaToolCall(
                    name="resume_run", json_args=json.dumps({"run_id": run_id})
                )
            }
        else:
            yield "Picked it up."

    return FunctionModel(stream_function=stream)


def _urlconf(view):
    module = types.ModuleType("tests._agui_urlconf")
    module.urlpatterns = [path("agent/", view)]
    return module


def _payload(text="hello"):
    return RunAgentInput(
        thread_id="t1",
        run_id="r1",
        state={},
        messages=[UserMessage(id="m1", role="user", content=text)],
        tools=[],
        context=[],
        forwarded_props={},
    ).model_dump_json(by_alias=True)


@pytest.fixture
def agui_client():
    view = endpoint_for(build_agent(WalkCountingWizardViewSet, _model()))
    with override_settings(ROOT_URLCONF=_urlconf(view)):
        yield AsyncClient()


async def _post(client):
    response = await client.post(
        "/agent/", data=_payload(), content_type="application/json"
    )
    body = b"".join([chunk async for chunk in response.streaming_content]).decode()
    return response, body


def test_a_post_streams_ag_ui_events(agui_client):
    response, body = asyncio.run(_post(agui_client))

    assert response.status_code == 200
    assert "text/event-stream" in response["content-type"]
    assert "RUN_STARTED" in body
    assert "TOOL_CALL_START" in body


def test_the_run_the_agent_started_is_a_real_one(agui_client):
    """The point of hosting this in Django: one process, one database, so
    the run an agent creates is the run a browser can open."""
    _, body = asyncio.run(_post(agui_client))

    snapshots = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ") and "STATE_SNAPSHOT" in line
    ]

    assert snapshots
    assert snapshots[-1]["snapshot"]["run_id"]
    assert snapshots[-1]["snapshot"]["step"] == "first"


def test_the_run_the_agent_started_is_in_the_browsers_own_session(agui_client):
    """The shipped storage is session-backed, so a chat that could not
    reach the browser's session could only ever fill a run nobody would
    open. The endpoint hands the agent the session the request arrived on
    — and, because the response streams, the run is written back as the
    tool makes it rather than left for a middleware that has already run."""
    asyncio.run(_post(agui_client))

    runs = stored_runs(agui_client)

    assert len(runs) == 1


def test_the_agent_picks_up_a_run_the_person_started(agui_client):
    """The other direction, and the handover the design is for: somebody
    fills a step in the form, then asks the chat to carry on with it."""
    # Reading `.session` off the client creates one and cookies it, which
    # is the browser this test is standing in for.
    driver = RunDriver.begin(WalkCountingWizardViewSet, session=agui_client.session)
    driver.submit({"name": "Ada"})

    view = endpoint_for(
        build_agent(WalkCountingWizardViewSet, _resuming_model(driver.run_id))
    )
    with override_settings(ROOT_URLCONF=_urlconf(view)):
        _, body = asyncio.run(_post(agui_client))

    snapshot = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ") and "STATE_SNAPSHOT" in line
    ][-1]["snapshot"]
    assert snapshot["run_id"] == driver.run_id
    assert snapshot["answers"]["first"] == {"name": "Ada"}
    # Not a copy of one: the agent is walking the run itself, so where it
    # leaves the run is where the person finds it.
    assert snapshot["step"] == "second"


def test_page_context_can_be_turned_into_run_instructions():
    """The gap this closes: AG-UI carries page context, and pydantic-ai's
    adapter does not forward it, so an agent that is *shown* somebody's
    details still asks for them."""
    seen = []

    def instructions(run_input):
        seen.append(run_input.thread_id)
        return "Today is Tuesday."

    view = endpoint_for(
        build_agent(WalkCountingWizardViewSet, _model()), instructions=instructions
    )
    with override_settings(ROOT_URLCONF=_urlconf(view)):
        asyncio.run(_post(AsyncClient()))

    assert seen == ["t1"]


def test_the_endpoint_is_exempt_from_csrf():
    """A chat posts JSON from a script, so it carries no form token — the
    wizard's own pages, which do, keep full protection. What stands in for
    the token is checked below: the origin, the content type, and the
    method."""
    view = endpoint_for(build_agent(WalkCountingWizardViewSet, _model()))

    assert view.csrf_exempt is True


async def _post_raw(client, **extra):
    """A POST that may be refused, so the body is never streamed — reading
    `streaming_content` off a plain response raises."""
    return await client.post(
        "/agent/", data=_payload(), content_type="application/json", **extra
    )


def test_a_cross_origin_post_is_refused(agui_client):
    """The exemption turns off Django's own origin check, and this endpoint
    is worth attacking: its tools answer, edit and read the run belonging to
    whoever's cookie the browser attached. `SameSite=Lax` is the only thing
    standing in the way otherwise, and a project that relaxes it — SSO, an
    embedded widget — would never know it had.
    """
    response = asyncio.run(
        _post_raw(agui_client, headers={"origin": "https://evil.example"})
    )

    assert response.status_code == 403


def test_a_same_origin_post_is_served(agui_client):
    """The other half of the check: a browser on the site's own origin sends
    an `Origin` header too, and must be served."""
    response = asyncio.run(
        _post_raw(agui_client, headers={"origin": "http://testserver"})
    )

    assert response.status_code == 200


def test_an_origin_the_project_trusts_is_served(agui_client):
    """The way out for a chat served from somewhere else — a separate front
    end, a dev server proxying in. The endpoint reads the setting the rest of
    the site already answers to rather than inventing one of its own, so a
    deployment says this once and everything believes it."""
    with override_settings(CSRF_TRUSTED_ORIGINS=["https://chat.example.com"]):
        response = asyncio.run(
            _post_raw(agui_client, headers={"origin": "https://chat.example.com"})
        )

    assert response.status_code == 200


def test_a_post_that_does_not_claim_json_is_refused(agui_client):
    """An HTML form can only post three content types and JSON is not among
    them, so requiring it is what makes a cross-site POST need a preflight —
    which nothing here answers. It is the check that holds when a permissive
    CORS policy has undone the origin one."""
    response = asyncio.run(
        agui_client.post("/agent/", data=_payload(), content_type="text/plain")
    )

    assert response.status_code == 415


def test_a_get_is_refused(agui_client):
    """One POST in, a stream of events out — nothing else is a request to
    this endpoint."""
    response = asyncio.run(agui_client.get("/agent/"))

    assert response.status_code == 405


def test_a_refused_post_is_turned_away_before_a_session_is_minted(agui_client):
    """The guards come first or they cost what they were meant to save: the
    endpoint creates a session for anyone who asks — that is what makes an
    anonymous visitor's run addressable — so refusing afterwards would leave
    a session record behind for every rejected request."""
    response = asyncio.run(
        _post_raw(agui_client, headers={"origin": "https://evil.example"})
    )

    assert response.status_code == 403
    assert "sessionid" not in response.cookies
