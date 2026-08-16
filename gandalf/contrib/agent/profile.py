"""What a wizard tells an agent about itself."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    """What an agent should be told about one wizard, declared in one place.

    Attach it to a `WizardViewSet` as `agent`, beside the attributes
    Django reads:

        class QuoteViewSet(WizardViewSet):
            wizard = ...
            template_name = "quote/step.html"
            agent = AgentProfile(
                purpose="a business insurance quote",
                notes="Vehicles are added on the fleet page, not here.",
            )

    One attribute rather than several loose ones, and a named type rather
    than bare strings, because the alternative is what this replaced:
    `agent_purpose` and `agent_notes` sitting on a Django view class,
    read by `getattr` somewhere else entirely, with nothing on the class
    to say what reads them or what happens if they are absent. They were
    indistinguishable from `template_name` at a glance and behaved
    nothing like it.

    `purpose` completes the sentence "you are helping someone with —",
    so it is a noun phrase and not an instruction: *"a business insurance
    quote"*, *"confirming somebody's identity"*. It is the only domain
    knowledge in the prompt, which is what lets the rest of it stay true
    of any wizard.

    `notes` is for what the wizard cannot say about itself. A wizard
    describes its own steps, so an agent already knows those; what it
    cannot know is that something the person needs lives on a different
    page, or that one document happens to answer four of the questions.
    That is the application's knowledge and this is where it goes.

    Absent entirely is fine. A wizard with no profile gets a prompt that
    says it is helping with "this application", which is honest and
    useless in equal measure — enough to drive a wizard, not enough to
    talk about one.
    """

    purpose: str
    notes: str | None = None
