"""Show the agent a photograph and see what it makes of it.

    just licence-demo path/to/licence.jpg

The browser demo is the same journey with a camera on the front. This is
the version you can run over a folder of images and read the output of,
which is what makes the reading *checkable*: the model's job here is to
transcribe four fields off a picture, and the only way to know whether it
did is to look at what came out beside what went in.

It is deliberately not a scored scenario in `examples/scenarios.py`. The
eight there are measured against the quote wizard and compared run to
run; this one has no fixture to compare against, because the right answer
depends on which photograph you hand it. Point it at your own and read
the table. Everything a scored scenario would need is here — the image
reaches the model, the attachment reaches the tools — so writing one is
adding assertions rather than plumbing.

Costs a real model call, and an image is worth roughly a thousand tokens
of it.
"""

import os
import sys

import django


def _setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "examples.copilotkit.settings")
    django.setup()


_setup()

import mimetypes  # noqa: E402
from pathlib import Path  # noqa: E402

from pydantic_ai import BinaryContent  # noqa: E402

from examples.copilotkit.agent import (  # noqa: E402
    Attachment,
    WizardDeps,
    WizardState,
    build_agent,
    resolve_model,
)
from examples.copilotkit.views import context_instructions  # noqa: E402
from examples.copilotkit.wizards import (  # noqa: E402
    HybridIdentityViewSet,
    HybridLicenceViewSet,
)
from examples.costs import dollars  # noqa: E402
from gandalf.driver import RunDriver, fabricate_request  # noqa: E402

PROMPT = "Here is a photo of my driving licence. Please fill in the check for me."

#: The two ways a photograph can be useful, one command apart. `check`
#: keeps it — there is a file step, and the agent attaches the image to
#: the run. `identity` never wanted it: same four fields, no file step, no
#: attach tool, and the picture is only ever *read*. If the second works
#: and the first does not, the reading is fine and the storing is broken;
#: if neither does, the model could not read the card.
WIZARDS = {
    "check": HybridLicenceViewSet,
    "identity": HybridIdentityViewSet,
}


def read_licence(path: Path, model: str, viewset_class):
    """One run: hand the agent the photograph and let it work."""
    data = path.read_bytes()
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"

    agent = build_agent(viewset_class, model)
    deps = WizardDeps(
        state=WizardState(),
        request=fabricate_request(),
        # The same bytes reach the model and the tools by different roads:
        # the model is shown the picture, the tools are given a handle to
        # it. Over HTTP the endpoint does this from the incoming message;
        # here there is no message, so it is done by hand.
        attachments={
            "attachment-1": Attachment(
                id="attachment-1",
                name=path.name,
                media_type=media_type,
                data=data,
            )
        },
    )

    result = agent.run_sync(
        [PROMPT, BinaryContent(data=data, media_type=media_type)],
        deps=deps,
        instructions=context_instructions(()),
    )
    return result, deps


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: just licence-demo <path to a licence photo> "
            f"[{' | '.join(WIZARDS)}]"
        )
    path = Path(sys.argv[1])
    if not path.is_file():
        raise SystemExit(f"No such file: {path}")
    which = sys.argv[2] if len(sys.argv) > 2 else "check"
    if which not in WIZARDS:
        raise SystemExit(f"Unknown wizard {which!r}; pick one of {', '.join(WIZARDS)}.")
    viewset_class = WIZARDS[which]

    model = resolve_model()
    if model == "test":
        raise SystemExit(
            "Reading a photograph needs a real model. Put ANTHROPIC_API_KEY "
            "in .env, or set GANDALF_AGENT_MODEL."
        )

    result, deps = read_licence(path, model, viewset_class)

    print(f"\nShowed {path.name} to {model}, driving the {which!r} wizard.\n")
    print(result.output.strip() or "(the agent said nothing)")

    run_id = deps.state.run_id
    if run_id is None:
        print("\nNo run was started, so there is nothing to check.")
        return

    driver = RunDriver.resume(viewset_class, run_id, request=deps.request)
    print("\nWhat it read off the picture:\n")
    for step, placement in driver.placements().items():
        for field, value in placement.answers.items():
            if field in placement.files:
                value = f"<{placement.files[field]['name']}>"
            print(f"    {step:<9} {field:<16} {value}")

    described = driver.describe()
    print(f"\nThe run stops at: {described.step or 'nothing — it is complete'}")
    # Which is the point. Four transcribed fields and a confirmation that
    # is not the agent's to give — a misread character looks exactly like
    # a correctly read one.
    print(f"Hand back at:     {driver.bound_wizard.entry_url('confirm')}")

    inputs, outputs = result.usage.input_tokens, result.usage.output_tokens
    price = dollars(model, inputs, outputs)
    cost = f", ${price:.4f}" if price is not None else ""
    print(f"\n{inputs} in, {outputs} out{cost}.")


if __name__ == "__main__":
    sys.exit(main())
