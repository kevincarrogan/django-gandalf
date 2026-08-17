"""What an agent carries between tool calls, and the files it was handed.

`WizardDeps` is the dependency object a `pydantic-ai` agent built here
runs with. It holds three things and each is there for a different
reason.

`state` is what the browser sees. pydantic-ai's AG-UI adapter syncs a
non-optional `state` field with the client, so every tool that moves the
run can leave the page re-rendered behind it.

`context` is what the run is driven *in*. A wizard's storage is scoped
by it — a durable backend reads `context.actor` — so the runs an agent
creates belong to the person it is working for rather than to nobody.

`attachments` are the files already in the conversation, held here rather
than passed through the model. That is the whole of the rule an agent
placing a document has to obey: it relays something a person supplied,
named by a handle, rather than writing content of its own choosing into
somebody's run.
"""

from __future__ import annotations

from base64 import b64decode
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ag_ui.core import BinaryInputContent, EventType, StateSnapshotEvent
from pydantic import BaseModel

from gandalf.context import WizardContext


class WizardState(BaseModel):
    """What the browser sees; snapshotted to the frontend on every change."""

    run_id: str | None = None
    step: str | None = None
    step_schema: dict[str, Any] | None = None
    outline: list[dict[str, Any]] | None = None
    answers: dict[str, dict[str, Any]] = {}
    complete: bool = False
    handoff_url: str | None = None


@dataclass(frozen=True)
class Attachment:
    """A file the person put in the chat, held where a tool can name it.

    The model is shown the picture — pydantic-ai turns an AG-UI image part
    into model content on its own — but it is never handed the bytes to
    pass around. It refers to this by `id`, and the tool does the placing.
    That is the whole of the rule: an agent relays a document somebody
    supplied, rather than writing content of its own choosing into a run.
    """

    id: str
    name: str
    media_type: str
    data: bytes


def attachments_from(messages: Iterable[Any]) -> dict[str, Attachment]:
    """Every file in the conversation so far, keyed by a handle.

    Ids are positional rather than taken from the filename: a filename is
    optional in the protocol, is not unique, and is the person's to
    choose. `attachment-1` is stable within a turn and is what the model
    is told to use.

    A part that references a URL rather than carrying data is skipped —
    placing it would mean fetching whatever it points at, which is a
    different capability with a different argument attached to it.
    """
    found: dict[str, Attachment] = {}
    for message in messages:
        if getattr(message, "role", None) != "user":
            continue
        content = message.content
        if not content or isinstance(content, str):
            continue
        for part in content:
            attachment = _as_attachment(part, len(found) + 1)
            if attachment is not None:
                found[attachment.id] = attachment
    return found


def _as_attachment(part: Any, index: int) -> Attachment | None:
    identifier = f"attachment-{index}"
    if isinstance(part, BinaryInputContent):
        if not part.data:
            return None
        return Attachment(
            id=identifier,
            name=part.filename or "",
            media_type=part.mime_type,
            data=b64decode(part.data),
        )
    # The typed parts — image, document, audio, video — carry a source that
    # is either inline data or a URL, and no name of their own.
    source = getattr(part, "source", None)
    if source is None or source.type != "data":
        return None
    return Attachment(
        id=identifier,
        name="",
        media_type=source.mime_type,
        data=b64decode(source.value),
    )


@dataclass
class WizardDeps:
    """Shared state, plus the environment the run is driven in.

    A dataclass with a non-optional `state` field is what pydantic-ai's
    AG-UI adapter needs to sync state with the client. The context rides
    along because the wizard's storage is scoped by it — the demo's
    durable backend reads `context.actor`, so the runs an agent creates
    belong to the person it is working for.

    `attachments` is what the person shared in the chat this turn, held
    here rather than passed through the model — see `Attachment`.
    """

    state: WizardState
    context: WizardContext = field(default_factory=WizardContext)
    attachments: dict[str, Attachment] = field(default_factory=dict)


def _snapshot(state: WizardState) -> StateSnapshotEvent:
    return StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=state)
