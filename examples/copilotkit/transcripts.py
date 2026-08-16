"""Keep a record of what an agent actually did, so a demo run can be read
back afterwards.

The chat is a stream: it renders and it is gone. That is fine for watching
and useless for judging, and the questions worth asking after a run are all
about things the stream does not keep — how many times it went back to the
person, whether it checked before asking, whether it said "wizard" out
loud, what it spent. So every completed run is written to `runs/` as one
JSON file: the raw messages, the tool calls in order, and the usage.

This is deliberately dumb. It records; it does not score. Scoring belongs
in an eval harness that can run scenarios repeatedly, and this is the
material that would feed one.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from pydantic_core import to_json

TRANSCRIPT_DIR = pathlib.Path("runs")


def _parts(messages, kind):
    for message in messages:
        for part in message.get("parts", []):
            if part.get("part_kind") == kind:
                yield message, part


def summarise(messages):
    """The few things worth seeing without reading the whole transcript."""
    tool_calls = [
        {"tool": part.get("tool_name"), "args": part.get("args")}
        for _, part in _parts(messages, "tool-call")
    ]
    said = [
        part.get("content")
        for message, part in _parts(messages, "text")
        if message.get("kind") == "response"
    ]
    asked = [text for text in said if isinstance(text, str) and "?" in text]
    machinery = sorted(
        {
            word
            for text in said
            if isinstance(text, str)
            # "form" and "step" are ordinary English for somebody filling
            # in an insurance application — "confirm it in the form", "the
            # next step" — and flagging them punished perfectly good
            # writing. What gives the game away is this library's own
            # vocabulary.
            for word in (
                "wizard",
                "schema",
                "prefill",
                "outline",
                "validation",
                "run id",
                "json",
            )
            if word in text.lower()
        }
    )
    return {
        "tool_calls": tool_calls,
        "tool_call_names": [call["tool"] for call in tool_calls],
        "replies_to_the_person": said,
        "replies_containing_a_question": len(asked),
        "machinery_words_said_out_loud": machinery,
    }


def record(result, source="chat", **about):
    """Write one completed run to `runs/`. Returns the path.

    `source` says what produced it and `about` carries anything else worth
    knowing — the scenario it came from, the model that ran it. Both land
    in the file, because a transcript that cannot say what it is is a pile
    of JSON rather than evidence.

    That was not a hypothesis. `runs/` held a browser session and an
    evaluation run side by side with nothing to tell them apart, and an
    attempt to read the rates out of it counted somebody's manual testing
    as scenario results.
    """
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    messages = json.loads(to_json(result.all_messages()))
    usage = result.usage
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = TRANSCRIPT_DIR / f"{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                **about,
                "usage": {
                    "requests": usage.requests,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "tool_calls": usage.tool_calls,
                },
                "summary": summarise(messages),
                "messages": messages,
            },
            indent=2,
            default=str,
        )
    )
    return path
