"""What the demo's wizards tell an agent about themselves.

Needs the `agents` group; skips otherwise.

The machinery — reading a profile, building a prompt, deciding whether a
wizard can take a document — belongs to `gandalf.contrib.agent` and is
tested there. What is left here is the part that is this demo's: that
each of its three wizards says something sensible and different, and that
the difference lands where it should.
"""

import pytest

pytest.importorskip("pydantic_ai")

from examples.identity import IdentityCheckViewSet  # noqa: E402
from examples.insurance import InsuranceQuoteViewSet  # noqa: E402
from examples.licence import LicenceCheckViewSet  # noqa: E402
from gandalf.contrib.agent import (  # noqa: E402
    accepts_documents,
    build_instructions,
    build_toolset,
    profile_for,
)

WIZARDS = (InsuranceQuoteViewSet, LicenceCheckViewSet, IdentityCheckViewSet)


def test_every_demo_wizard_says_what_it_is_for():
    """A wizard with no profile still works and is told it is helping with
    "this application", which is no way to introduce yourself."""
    for viewset_class in WIZARDS:
        profile = profile_for(viewset_class)
        assert profile is not None, viewset_class.__name__
        assert profile.purpose


def test_every_agent_is_told_what_to_do_with_a_document():
    """Unconditional, because it only fires when one arrives — including
    for the quote wizard, which has nowhere to put a file and can still be
    handed a photograph of a certificate."""
    for viewset_class in WIZARDS:
        assert "share a photo or a scan" in build_instructions(viewset_class)


def test_asking_for_a_document_is_left_to_the_wizard():
    """The other half of the rule stays out of the shared prompt: it
    changes what an agent volunteers, and the quote agent should not start
    asking for certificates of incorporation because a licence demo wanted
    a shortcut."""
    assert "driving licence" in build_instructions(IdentityCheckViewSet)
    assert "driving licence" not in build_instructions(InsuranceQuoteViewSet)


def test_only_the_wizard_with_a_file_step_can_be_handed_a_document():
    """Derived from the wizard rather than declared beside it, so the two
    cannot disagree. The identity check asks for the same four things as
    the licence check and keeps none of them."""
    assert accepts_documents(LicenceCheckViewSet) is True
    assert accepts_documents(IdentityCheckViewSet) is False
    assert accepts_documents(InsuranceQuoteViewSet) is False

    assert "attach_document" in build_toolset(LicenceCheckViewSet).tools
    assert "attach_document" not in build_toolset(IdentityCheckViewSet).tools
