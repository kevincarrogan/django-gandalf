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

**Declaring a profile costs nothing.** `AgentProfile` imports at the top
of this module and everything else waits until it is asked for, so a
viewset can carry one in an environment that has never installed the
extra. That matters more than it sounds: a profile is a *declaration*,
sitting on a Django class that a production deployment imports to serve
ordinary forms. Making that deployment install an AI SDK to render a page
would be exactly the coupling the extra exists to avoid.
"""

from typing import TYPE_CHECKING, Any

from gandalf.contrib.agent.profile import AgentProfile

if TYPE_CHECKING:
    from gandalf.contrib.agent.deps import (
        Attachment,
        WizardDeps,
        WizardState,
        attachments_from,
    )
    from gandalf.contrib.agent.prompt import build_instructions, profile_for
    from gandalf.contrib.agent.toolset import (
        accepts_documents,
        build_agent,
        build_toolset,
    )

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

#: Which module each lazy name comes from. `prompt` needs nothing beyond
#: Django, but it is here too so that the rule is "everything but the
#: profile is deferred" rather than a list somebody has to keep true.
_LAZY = {
    "Attachment": "deps",
    "WizardDeps": "deps",
    "WizardState": "deps",
    "attachments_from": "deps",
    "build_instructions": "prompt",
    "profile_for": "prompt",
    "accepts_documents": "toolset",
    "build_agent": "toolset",
    "build_toolset": "toolset",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
