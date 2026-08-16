"""One append-only log of what happened, for working on this and judging it.

An agent run leaves almost no trace by itself: the chat is a stream, the
tool calls happen inside somebody else's loop, and the only durable thing
is the wizard state at the end. That is enough to see *that* it worked and
useless for seeing *how*.

So everything interesting writes one line here — every tool the agent
calls and what came back, every vehicle the person adds or removes, every
quote produced — to `runs/events.jsonl`, and to the console as it happens.
Tail it while you work; read it back afterwards with `just agent-log`.

Deliberately not an evaluation suite. It records facts; deciding whether
they are good facts is a separate job, and this is the material that job
would read.
"""

from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone
from typing import Any

from gandalf.observers import WizardObserver

RUN_DIR = pathlib.Path("runs")
EVENT_LOG = RUN_DIR / "events.jsonl"

logger = logging.getLogger("gandalf.demo")


def _short(value: Any, limit: int = 300) -> Any:
    """Arguments and results can be whole wizard outlines; keep the log
    readable and let the transcript hold the full version."""
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    return text[:limit] + "…"


def log_event(kind: str, **fields: Any) -> None:
    """Record one thing that happened, to the file and to the console."""
    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **{name: _short(value) for name, value in fields.items()},
    }
    RUN_DIR.mkdir(exist_ok=True)
    with EVENT_LOG.open("a") as handle:
        handle.write(json.dumps(event, default=str) + "\n")
    logger.info("%s %s", kind, json.dumps(event, default=str)[:400])


def read_events(limit: int | None = None) -> list[dict[str, Any]]:
    """Every recorded event, oldest first; the last `limit` when given."""
    if not EVENT_LOG.exists():
        return []
    events = [json.loads(line) for line in EVENT_LOG.read_text().splitlines() if line]
    return events if limit is None else events[-limit:]


class DemoObserver(WizardObserver):
    """The library hook, used for the demo's own observability.

    Every answer placed in a run lands here — whoever placed it. That is
    the point worth testing: the agent goes through `RunDriver` and the
    person goes through a browser, and neither had to be instrumented
    separately for both to show up in one stream.

    And now the stream says which was which. `metadata` is what the
    placement claimed about itself: `None` from a browser, because a form
    post makes no such claim, and `{"unattended": True}` from the agent,
    which marks its own. Reading the log back afterwards, that one key is
    the difference between knowing a step was answered twice and knowing
    the person changed what the agent had put there.
    """

    def submission(self, step, accepted, metadata):
        log_event(
            "submission",
            run=self.run_id,
            step=(step.context or {}).get("name"),
            accepted=accepted,
            unattended=bool((metadata or {}).get("unattended")),
        )

    def run_completed(self):
        log_event("run_completed", run=self.run_id)
