"""Read back what happened: `just agent-log`.

Prints the most recent run as a script — what was said, what was called,
what it cost — followed by the wizard-side events the transcript cannot
see. Enough to answer the questions that come up while working on this
("did it check before asking?", "how many times did it go back to them?",
"did it say *wizard* out loud?") without standing up an evaluation suite
to ask them formally.
"""

from __future__ import annotations

import json
import sys

from examples.eventlog import RUN_DIR, read_events

WRAP = 100


def _wrap(text, indent="    "):
    text = " ".join(str(text).split())
    lines = []
    while len(text) > WRAP:
        cut = text.rfind(" ", 0, WRAP)
        cut = cut if cut > 0 else WRAP
        lines.append(text[:cut])
        text = text[cut:].lstrip()
    lines.append(text)
    return "\n".join(indent + line for line in lines)


def transcripts():
    return sorted(RUN_DIR.glob("2*.json"))


def show_run(path):
    run = json.loads(path.read_text())
    summary = run["summary"]
    usage = run["usage"]

    print(f"\n=== {path.name} ===")
    print(f"    {usage['requests']} model requests · ", end="")
    print(
        f"{usage['input_tokens']} in / {usage['output_tokens']} out tokens · ", end=""
    )
    print(f"{usage['tool_calls']} tool calls")

    print("\n-- what it did --")
    for call in summary["tool_calls"]:
        args = json.dumps(call["args"], default=str)
        print(f"    {call['tool']}({args[:120]})")

    print("\n-- what it said --")
    for reply in summary["replies_to_the_person"]:
        print(_wrap(reply))
        print()

    print("-- worth noticing --")
    print(
        f"    replies containing a question: {summary['replies_containing_a_question']}"
    )
    machinery = summary["machinery_words_said_out_loud"]
    print(f"    machinery words said out loud: {', '.join(machinery) or 'none'}")
    checked = "check_answers" in summary["tool_call_names"]
    print(f"    checked before asking: {'yes' if checked else 'no'}")


def show_events(limit):
    events = read_events(limit)
    if not events:
        return
    print("\n-- events (agent and person) --")
    for event in events:
        detail = {
            key: value
            for key, value in event.items()
            if key not in {"at", "kind", "args", "returned"}
        }
        print(
            f"    {event['at'][11:19]}  {event['kind']:<16} {json.dumps(detail, default=str)[:110]}"
        )


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    found = transcripts()
    if not found:
        print("No runs recorded yet. Have a conversation at http://localhost:5173")
        print("and the agent's side of it lands in runs/.")
    for path in found[-count:]:
        show_run(path)
    show_events(limit=40)


main()
