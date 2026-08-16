"""Drive a wizard with a language model.

    pip install django-gandalf[agent] "pydantic-ai-slim[openai]"

The extra brings `pydantic-ai` and the AG-UI transport; **the provider is
yours to choose** and yours to install. Nothing here names one, and
`build_agent` takes whatever pydantic-ai takes — a `"provider:model"`
string or a `Model` instance.

    from gandalf.contrib.agent import AgentProfile, build_agent

    class QuoteViewSet(WizardViewSet):
        wizard = ...
        agent = AgentProfile(purpose="a business insurance quote")

    agent = build_agent(QuoteViewSet, "openai:gpt-5.2")

What you get is a `pydantic_ai.Agent` whose tools are the driver: it can
read the journey before starting, check a bag of answers without placing
any, fill what it holds, correct itself, and hand the run back. It cannot
conclude one — see `toolset` for why that is not an oversight.
"""

from gandalf.contrib.agent.deps import (
    Attachment,
    WizardDeps,
    WizardState,
    attachments_from,
)
from gandalf.contrib.agent.profile import AgentProfile
from gandalf.contrib.agent.prompt import build_instructions, profile_for
from gandalf.contrib.agent.toolset import accepts_documents, build_agent, build_toolset

__all__ = [
    "AgentProfile",
    "Attachment",
    "WizardDeps",
    "WizardState",
    "accepts_documents",
    "attachments_from",
    "build_agent",
    "build_instructions",
    "build_toolset",
    "profile_for",
]
