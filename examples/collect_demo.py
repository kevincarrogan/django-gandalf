"""Say something to the adaptive agent and see how it decides to ask back.

    just collect-demo "I'd rather just talk than type all this out."
    just collect-demo "yeah so it's analytical engines limited um we..." heard

The browser demo (`#adaptive`) is this with a chat around it. This is the
version you can run over a sentence and read the output of, which is what
makes the *decision* checkable: the agent has three ways to collect
something — keep talking, draw a form, or ask out loud — and the only way
to know which it picked, and what it drew, is to look.

Pass `heard` as a second argument to hand the sentence over as a
**transcript** instead: the demo pretends `ask_out_loud` was called and
answered with it, which is what the browser sends once somebody stops
speaking. That is the half worth checking most often, because it is where
a rough transcript has to come back as a form with the right things in it.
No microphone and no browser involved.

The frontend tools are declared here exactly as `GeneratedForm.jsx` and
`VoiceAnswer.jsx` declare them, because that is what the browser puts in
the run input and the whole point is to exercise the same path. They are
spelled out as JSON Schema rather than imported, since the originals are
zod and live in the other language.

Costs one real model call.
"""

import os
import sys

import django


def _setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "examples.copilotkit.settings")
    django.setup()


_setup()

import asyncio  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402

from django.test import AsyncClient  # noqa: E402

from examples.copilotkit.agent import resolve_model  # noqa: E402
from examples.costs import dollars  # noqa: E402

OPTION = {
    "type": "object",
    "required": ["value", "label"],
    "properties": {
        "value": {"type": "string"},
        "label": {"type": "string"},
        "description": {"type": "string"},
    },
}

FORM_TOOL = {
    "name": "collect_with_a_form",
    "description": "Draw a form and show it to the person, instead of asking in chat.",
    "parameters": {
        "type": "object",
        "required": ["fields"],
        "properties": {
            "title": {"type": "string"},
            "intro": {"type": "string"},
            "submitLabel": {"type": "string"},
            "speak": {"type": "boolean"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "label", "control"],
                    "properties": {
                        "name": {"type": "string"},
                        "label": {"type": "string"},
                        "help": {"type": "string"},
                        "control": {
                            "type": "string",
                            "enum": [
                                "text",
                                "longtext",
                                "number",
                                "date",
                                "email",
                                "tel",
                                "choice",
                                "multichoice",
                                "yesno",
                            ],
                        },
                        "options": {"type": "array", "items": OPTION},
                        "required": {"type": "boolean"},
                        "placeholder": {"type": "string"},
                        "value": {"type": "string"},
                        "dictate": {"type": "boolean"},
                    },
                },
            },
        },
    },
}

VOICE_TOOL = {
    "name": "ask_out_loud",
    "description": "Ask a question and let the person answer by speaking.",
    "parameters": {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {"type": "string"},
            "hint": {"type": "string"},
            "speak": {"type": "boolean"},
        },
    },
}

CALL_ID = "call-said-out-loud"


def _messages(said, *, as_transcript):
    """The conversation to send.

    A transcript arrives as the *result* of a tool call, which is what the
    browser posts once somebody stops speaking: the assistant asked, the
    person answered, and the run continues from there. Sending it as a plain
    user message would be a different thing entirely — the agent would have
    no reason to treat it as speech it has to read back.
    """
    if not as_transcript:
        return [{"id": "1", "role": "user", "content": said}]
    return [
        {"id": "1", "role": "user", "content": "I'd rather talk than type."},
        {
            "id": "2",
            "role": "assistant",
            "content": "",
            "toolCalls": [
                {
                    "id": CALL_ID,
                    "type": "function",
                    "function": {
                        "name": "ask_out_loud",
                        "arguments": json.dumps(
                            {
                                "question": "Tell me about your business and the cover you want."
                            }
                        ),
                    },
                }
            ],
        },
        {
            "id": "3",
            "role": "tool",
            "toolCallId": CALL_ID,
            "content": json.dumps({"transcript": said}),
        },
    ]


async def _collect(messages):
    """Post one run to the demo's own endpoint and read the event stream.

    Through the endpoint rather than the agent directly, because the tools
    being exercised are the *browser's* — they only reach the model by way
    of the run input, and calling the agent in-process would skip the thing
    under test.
    """
    body = {
        "threadId": str(uuid.uuid4()),
        "runId": str(uuid.uuid4()),
        "state": {},
        "context": [],
        "forwardedProps": {},
        "tools": [FORM_TOOL, VOICE_TOOL],
        "messages": messages,
    }
    response = await AsyncClient().post(
        "/adaptive-agent/", data=json.dumps(body), content_type="application/json"
    )
    stream = "".join([chunk.decode() async for chunk in response.streaming_content])

    calls, arguments, spoken, usage = [], {}, [], {}
    for line in stream.splitlines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        kind = event.get("type")
        if kind == "TOOL_CALL_START":
            calls.append((event["toolCallName"], event["toolCallId"]))
            arguments[event["toolCallId"]] = ""
        elif kind == "TOOL_CALL_ARGS":
            arguments[event["toolCallId"]] += event.get("delta", "")
        elif kind == "TEXT_MESSAGE_CONTENT":
            spoken.append(event.get("delta", ""))
        elif kind == "RUN_FINISHED":
            usage = (event.get("result") or {}).get("usage") or {}
    return calls, arguments, "".join(spoken), usage


def _print_form(form):
    print(f"    title:  {form.get('title') or '—'}")
    if form.get("intro"):
        print(f"    intro:  {form['intro']}")
    # The two that only matter to somebody who cannot read or type easily,
    # and the two this demo has never yet caught the model setting itself.
    print(f"    reads itself aloud: {bool(form.get('speak'))}")
    print()
    for field in form.get("fields", []):
        marks = "".join(
            [
                " 🎤" if field.get("dictate") else "",
                " *" if field.get("required") else "",
            ]
        )
        print(
            f"    [{field.get('control', '?'):<11}]{marks:<4} {field.get('label', '')}"
        )
        if field.get("help"):
            print(f"                     ↳ {field['help']}")
        if field.get("value") is not None:
            print(f"                     = {field['value']!r}")
        for option in field.get("options") or []:
            note = f"  — {option['description']}" if option.get("description") else ""
            print(
                f"                       · {option['value']!r}: {option['label']}{note}"
            )


def _print_question(question):
    print(f"    question: {question.get('question', '')}")
    if question.get("hint"):
        print(f"    hint:     {question['hint']}")
    print(f"    reads it aloud: {question.get('speak') is not False}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            'Say something to it: just collect-demo "I would rather talk."\n'
            'Add "heard" as a second argument to send it as a transcript instead.'
        )
    said = sys.argv[1]
    as_transcript = len(sys.argv) > 2 and sys.argv[2].lower() == "heard"

    model = resolve_model()
    if model == "test":
        raise SystemExit(
            "Deciding how to ask needs a real model — the canned one calls "
            "every tool it is offered, which answers nothing. Put "
            "ANTHROPIC_API_KEY in .env, or set GANDALF_AGENT_MODEL."
        )

    calls, arguments, spoken, usage = asyncio.run(
        _collect(_messages(said, as_transcript=as_transcript))
    )

    heading = "They said, out loud" if as_transcript else "They typed"
    print(f"\n{heading}:\n    {said}\n")
    print(f"{model} reached for: {', '.join(name for name, _ in calls) or 'nothing'}\n")

    if spoken.strip():
        print("What it said back:\n")
        print("    " + spoken.strip().replace("\n", "\n    ") + "\n")

    for name, call_id in calls:
        try:
            payload = json.loads(arguments.get(call_id) or "")
        except ValueError:
            continue
        if name == "collect_with_a_form":
            print("It drew a form:\n")
            _print_form(payload)
            print()
        elif name == "ask_out_loud":
            print("It asked out loud:\n")
            _print_question(payload)
            print()

    inputs = usage.get("inputTokens") or usage.get("input_tokens") or 0
    outputs = usage.get("outputTokens") or usage.get("output_tokens") or 0
    if inputs or outputs:
        price = dollars(model, inputs, outputs)
        cost = f", ${price:.4f}" if price is not None else ""
        print(f"{inputs} in, {outputs} out{cost}.")


if __name__ == "__main__":
    sys.exit(main())
