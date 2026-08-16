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
    wizard's own pages, which do, keep full protection."""
    view = endpoint_for(build_agent(WalkCountingWizardViewSet, _model()))

    assert view.csrf_exempt is True
