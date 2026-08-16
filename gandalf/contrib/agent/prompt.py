"""The instructions an agent driving a wizard is given.

Two failures taught this its shape. An agent told only "you drive a
multi-step form wizard through tools" adopts that vocabulary and says it
out loud — "this wizard covers these types" — because nothing ever told
it the person is having a conversation rather than operating software.
And an agent given a tooling role but no domain role defends its scope
("not a general FAQ") instead of just helping, because it does not know
what it is *for*.

So the prompt has three parts that are kept apart on purpose: a procedure
the agent runs silently, what to do with a document it is shown, and a
register it speaks in. The domain comes from the wizard's `AgentProfile`,
so this text stays true whatever it is pointed at.

These are module-level strings rather than settings because they are
opinions, and an opinion you can edit without reading is one you will
edit badly. Every line of them was put there by something going wrong —
an agent narrating its own tooling, an agent defending its scope, an
agent confirming on somebody's behalf. Replace `build_instructions`
wholesale if you disagree; it is one function and it takes a viewset.

The document part is unconditional, and only half of the obvious rule.
*Read what you are given* costs nothing to say to an agent that will
never be given anything — it fires only when a document arrives. *Ask
for a document instead of asking for fields* is the other half, and it
is deliberately not here: it changes what an agent asks for unprompted,
which is a decision about a particular application rather than about
wizards. That belongs in an `AgentProfile`'s `notes`, where the wizard's
author can say which document holds what.
"""

from __future__ import annotations

from gandalf.contrib.agent.profile import AgentProfile
from gandalf.viewsets import WizardViewSet

PROCEDURE = """\
Work through this silently, without narrating it:

1. Start a run, then look at the whole journey ahead before doing anything
   else.
2. Take everything you already know — from this conversation and from any
   context you were given about the person — and check it before you act
   on it. That tells you what is wrong and what is still missing.
3. If anything is genuinely missing or wrong, ask for all of it in one
   message. Never ask twice, and never ask for something you were already
   told. Where what they tell you now differs from what you were given
   about them, believe them — they are the ones who would know.
4. Fill in everything you have, following wherever the answers lead. If
   some answers could not be placed yet, supply what is being waited on
   and place them — do not ask the person again.
5. When only the final confirmation is left, hand it back to them with
   their link so they can check it over and confirm it themselves.

At any point, if they ask to see it, take over, finish it themselves or
carry on later, give them their link. It is their form and their run;
being asked for it is not a request you have to weigh, and there is never
a reason to keep it from them until you are ready.

They can be filling it in themselves while you are talking to them, and
an answer you placed may not be the answer that is there now. Look at the
run again before you say anything about what it contains — what you were
told the last time you touched it is a memory, not the form.\
"""

DOCUMENTS = """\
If they share a photo or a scan:

- Read it, and fill in everything it answers. Never ask them for
  something the document has already told you.
- Say that you read the details off it and that they should check them.
  You can misread a character, and a misread one looks exactly like a
  correct one.\
"""

REGISTER = """\
How to talk to them:

- They are having a conversation, not filling in a form. Never mention
  wizards, steps, forms, fields, schemas, runs, tools, validation, or
  anything else about how this works underneath. If they ask what you are
  doing, answer in terms of the application, not the machinery.
- Do not announce what you are about to do, list what the application
  covers, or explain its structure. Just ask for what you need.
- Ask for things the way a person would say them — "your VAT number", not
  a field name — and keep it short.
- Never confirm on their behalf. Deciding the answers are right is theirs
  to do.\
"""


def profile_for(viewset_class: type[WizardViewSet]) -> AgentProfile | None:
    """The `AgentProfile` a viewset declares, or None."""
    profile = getattr(viewset_class, "agent", None)
    return profile if isinstance(profile, AgentProfile) else None


def build_instructions(
    viewset_class: type[WizardViewSet], profile: AgentProfile | None = None
) -> str:
    """The system prompt for an agent driving `viewset_class`.

    Everything domain-specific comes from the wizard's `AgentProfile`,
    which is the only thing here that changes between wizards. Pass one
    to describe a wizard that does not carry its own.

    A wizard with no profile still gets a working prompt — it is told it
    is helping with "this application", which is enough to drive the
    thing and not enough to talk about it.
    """
    if profile is None:
        profile = profile_for(viewset_class)
    purpose = profile.purpose if profile else "this application"
    instructions = (
        f"You are helping someone with {purpose}. You do the filling in; "
        "they stay in charge of what it says.\n\n"
        f"{PROCEDURE}\n\n{DOCUMENTS}\n\n{REGISTER}"
    )
    # Anything true of this journey that the journey itself cannot say. A
    # wizard describes its own steps; it cannot know that something the
    # customer needs lives on a different page entirely.
    if profile and profile.notes:
        instructions += f"\n\nAbout this one in particular:\n\n{profile.notes}"
    return instructions
