"""What a wizard costs an agent — before anybody spends anything.

Two different currencies, and it helps to keep them apart.

The *runtime* cost is what gandalf itself does: validations, walks,
queries. `just bench` measures ours, and anyone can measure their own —
`step_dispatcher_class` and `cursor_walker_class` are pluggable, so a
counting wrapper needs no cooperation from the library (see
`benchmarks/instrumentation.py`).

The *token* cost is what an agent pays to be told what the wizard is. That
one is a property of the wizard rather than the model: fourteen steps with
rich schemas weigh more to describe than three plain ones, and every single
turn of every conversation pays it. `outline()` is public, so the weight is
measurable directly — and `count_tokens` is free and exact, which is why
this asks Anthropic rather than guessing from bytes.

    just agent-cost

Nothing here generates a single token.
"""

import os

import django


def _setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "examples.copilotkit.settings")
    django.setup()


_setup()

import json  # noqa: E402
import sys  # noqa: E402

import anthropic  # noqa: E402

from examples.copilotkit.agent import resolve_model  # noqa: E402
from examples.copilotkit.wizards import HybridQuoteViewSet  # noqa: E402
from gandalf.driver import RunDriver, fabricate_request  # noqa: E402

#: Dollars per million tokens, list price. Deliberately not the introductory
#: rate that is live as this is written — a number that quietly becomes an
#: underestimate on a date nobody remembers is worse than one that is
#: honest today and stays honest.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def dollars(model, input_tokens, output_tokens):
    """What that many tokens cost, or None for a model we have no price for."""
    prices = PRICES.get(model.split(":")[-1])
    if prices is None:
        return None
    return input_tokens * prices[0] / 1e6 + output_tokens * prices[1] / 1e6


def _label(entry):
    """What to call an outline entry. It is a tree, not a list of steps —
    a branch weighs what all of its arms weigh, because an agent is told
    about every arm it might end up in."""
    if entry["kind"] == "step":
        return entry["step"]
    if entry["kind"] == "switch":
        return f"switch on {entry['decided_by']} ({len(entry['cases'])} cases)"
    arms = len(entry["arms"])
    return f"branch ({arms} arm{'s' if arms != 1 else ''})"


def _steps(entries):
    """Every step in the tree, however deeply an arm buries it."""
    for entry in entries:
        if entry["kind"] == "step":
            yield entry["step"]
        for arm in entry.get("arms", []) + entry.get("cases", []):
            yield from _steps(arm["steps"])
        yield from _steps(entry.get("default") or [])


def weigh(viewset_class, model):
    """The token weight of describing `viewset_class`, entry by entry."""
    client = anthropic.Anthropic()
    bare = model.split(":")[-1]

    def count(payload):
        return client.messages.count_tokens(
            model=bare,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        ).input_tokens

    outline = RunDriver.outline_for(viewset_class, request=fabricate_request())
    weights = [(_label(entry), count(entry)) for entry in outline]
    return count(outline), weights, list(_steps(outline))


def main():
    model = resolve_model()
    if model == "test":
        raise SystemExit("Counting tokens needs a key. Put ANTHROPIC_API_KEY in .env.")

    total, weights, steps = weigh(HybridQuoteViewSet, model)
    print(f"Describing this wizard to {model}: {total} tokens\n")
    for name, weight in sorted(weights, key=lambda pair: -pair[1]):
        print(f"    {weight:>5}  {name}")

    price = dollars(model, total, 0)
    print(f"\n{len(steps)} steps across {len(weights)} top-level entries.")
    if price is not None:
        # Read once per turn, so a conversation of N turns pays it N times.
        print(
            f"Reading the outline costs ${price:.4f}; ten turns of it, ${price * 10:.3f}."
        )


if __name__ == "__main__":
    sys.exit(main())
