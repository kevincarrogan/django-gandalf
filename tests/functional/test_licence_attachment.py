"""A file arriving in the chat, and what the agent may do with it.

Needs the `agents` dependency group (`just test-agents`); skips otherwise.

The half of the licence demo that is about the *channel* rather than the
wizard. A person drops a photograph into the conversation; the model is
shown it by pydantic-ai without anything here helping, and the tools are
handed the bytes without the model ever carrying them. This proves the
second half, which is the one with a rule attached: the agent places a
document somebody supplied, named by a handle, and cannot invent one.
"""

from base64 import b64encode

import pytest

pytest.importorskip("ag_ui")

from ag_ui.core import (  # noqa: E402
    BinaryInputContent,
    ImageInputContent,
    InputContentDataSource,
    InputContentUrlSource,
    UserMessage,
)

from examples.copilotkit.agent import (  # noqa: E402
    Attachment,
    WizardDeps,
    WizardState,
    attachments_from,
    build_agent,
)
from examples.licence import LicenceCheckViewSet  # noqa: E402
from gandalf.driver import RunDriver, fabricate_request  # noqa: E402

_SCAN = b"pretend-image-bytes"


def _message(*parts):
    return UserMessage(id="m1", role="user", content=list(parts))


def _image(data=_SCAN):
    """The current spelling: a typed part carrying inline data."""
    return ImageInputContent(
        type="image",
        source=InputContentDataSource(
            type="data", value=b64encode(data).decode(), mime_type="image/png"
        ),
    )


def test_a_file_in_the_chat_becomes_an_addressable_attachment():
    """The handle the model is told to use, and the bytes it never sees."""
    attachments = attachments_from([_message(_image())])

    assert list(attachments) == ["attachment-1"]
    attachment = attachments["attachment-1"]
    assert attachment.data == _SCAN
    assert attachment.media_type == "image/png"


def test_the_deprecated_binary_part_is_still_understood():
    """`BinaryInputContent` is the older spelling and warns, but a client
    that has not moved on yet still gets its file placed — the adapter
    reads both, so this should too."""
    with pytest.warns(DeprecationWarning):
        part = BinaryInputContent(
            type="binary",
            mime_type="image/png",
            data=b64encode(_SCAN).decode(),
            filename="licence.png",
        )

    attachment = attachments_from([_message(part)])["attachment-1"]

    assert attachment.data == _SCAN
    assert attachment.name == "licence.png"


def test_a_file_referenced_by_url_is_not_an_attachment():
    """Placing one would mean fetching whatever it points at, which is a
    different capability with a different argument attached to it."""
    part = ImageInputContent(
        type="image",
        source=InputContentUrlSource(
            type="url", value="https://example.com/licence.png", mime_type="image/png"
        ),
    )

    assert attachments_from([_message(part)]) == {}


def test_text_only_conversations_have_no_attachments():
    attachments = attachments_from([UserMessage(id="m1", role="user", content="hello")])

    assert attachments == {}


def _deps(run_id=None):
    state = WizardState(run_id=run_id)
    return WizardDeps(
        state=state,
        request=fabricate_request(),
        attachments={
            "attachment-1": Attachment(
                id="attachment-1",
                name="licence.png",
                media_type="image/png",
                data=_SCAN,
            )
        },
    )


def _attach_tool(agent):
    """The bound `attach_document`, called directly.

    Driving it through a scripted model would prove the model can be told
    to call a tool, which is not in doubt; what is worth pinning is what
    the tool does with a handle.
    """
    logged = next(t for t in agent.toolsets if hasattr(t, "wrapped"))
    return logged.wrapped.tools["attach_document"].function


def test_the_agent_places_a_file_it_was_given(isolated_media_root):
    """The whole point: bytes the person supplied, into the run, as the
    agent's own placement."""
    agent = build_agent(LicenceCheckViewSet, "test")
    driver = RunDriver.begin(LicenceCheckViewSet, request=fabricate_request())
    deps = _deps(run_id=driver.run_id)
    deps.request = driver.bound_wizard.request

    _attach_tool(agent)(_context(deps), "attachment-1", "scan")

    resumed = RunDriver.resume(LicenceCheckViewSet, driver.run_id, request=deps.request)
    placement = resumed.placements()["scan"]
    assert resumed.open_file(placement.files["scan"]).read() == _SCAN
    assert placement.metadata == {"unattended": True}


def test_a_wizard_with_no_file_step_has_no_attach_tool():
    """A tool an agent cannot use is one it can only misuse. The quote
    wizard has nowhere to put a document, so its agent is not offered a
    way to try."""
    from examples.insurance import InsuranceQuoteViewSet

    agent = build_agent(InsuranceQuoteViewSet, "test")

    logged = next(t for t in agent.toolsets if hasattr(t, "wrapped"))
    assert "attach_document" not in logged.wrapped.tools


def _context(deps):
    """The minimum `RunContext` the tool reads: just its deps."""

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.deps = deps
    return ctx
