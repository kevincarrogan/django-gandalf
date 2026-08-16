"""What we expect an agent to do, written down.

Each scenario is an opening message, whatever the page already knows about
the customer, and the things that should be true when the agent stops. The
checks are deliberately about *outcomes* rather than wording: what ended up
in the run, how many times it went back to the person, whether it confirmed
on their behalf. A model is free to phrase things however it likes.
"""

from dataclasses import dataclass, field
from typing import Any

PROFILE = (
    "The customer's business profile",
    {
        "company_name": "Analytical Engines Ltd",
        "company_type": "limited company",
        "companies_house_number": "AE123456",
        "vat_registered": True,
        "founded": "1837-12-10",
        "employees": 12,
        "claims_last_five_years": [],
        "contact_email": "ada@analyticalengines.example",
    },
)

BAD_PROFILE = (
    "The customer's business profile",
    {
        "company_name": "Analytical Engines Ltd",
        "company_type": "limited company",
        "companies_house_number": "AE123456",
        "founded": "the tenth of December, 1837",
        "employees": "twelve",
        "contact_email": "ada@analyticalengines.example",
    },
)


@dataclass
class Scenario:
    name: str
    prompt: str
    context: tuple[tuple[str, Any], ...] = ()
    #: Answers that must be in the run when the agent stops, by step.
    expect_answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Where the run should be left. "confirm" means ready for the person.
    expect_step: str | None = "confirm"
    #: How many times it may go back to the person. The whole premise is
    #: that it asks once, or not at all.
    max_questions: int = 1
    #: Things a *single* reply must ask for. Counting questions is not
    #: enough: asking for three fields one at a time scores the same as
    #: asking for all three at once, and the difference is the whole point.
    expect_asks_for: tuple[str, ...] = ()
    #: Things it must say at some point — for what the wizard cannot hold
    #: and the person therefore has to be told about.
    expect_mentions: tuple[str, ...] = ()
    #: What the *person* changes after the agent's first turn, by step —
    #: the browser half of a hybrid run, placed straight into storage
    #: because that is exactly what a form submit does.
    edit: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: What they say next, once they have changed it.
    follow_up: str = ""


SCENARIOS = [
    Scenario(
        name="told everything",
        prompt=(
            "Quote please: property cover, £500 excess, starting 1 September "
            "2026. Analytical Engines Ltd, a limited company, Companies House "
            "AE123456, VAT registered, founded 10 December 1837, 12 staff, no "
            "claims ever, contact ada@analyticalengines.example."
        ),
        expect_answers={
            "company": {"name": "Analytical Engines Ltd", "employees": 12},
            "registration": {"companies_house_number": "AE123456"},
            "claims": {"had_claims": "no"},
            "contact": {"email": "ada@analyticalengines.example"},
        },
        max_questions=0,
    ),
    Scenario(
        name="profile plus a one-liner",
        prompt="I need a quote for property cover, £500 excess, from 1 September 2026.",
        context=(PROFILE,),
        expect_answers={
            "company": {"name": "Analytical Engines Ltd", "employees": 12},
            "registration": {"companies_house_number": "AE123456"},
            "contact": {"email": "ada@analyticalengines.example"},
        },
        max_questions=0,
    ),
    Scenario(
        name="profile is missing the cover",
        prompt="Can you get me a quote?",
        context=(PROFILE,),
        # Nobody has said what cover they want, so it has to ask — once,
        # and for everything it is missing rather than one field at a time.
        expect_answers={},
        expect_step=None,
        max_questions=1,
        expect_asks_for=("cover", "excess", "start"),
    ),
    Scenario(
        name="the conversation contradicts the profile",
        prompt=(
            "Quote please: property cover, £500 excess, starting 1 September "
            "2026. We've grown since you last spoke to us — there are 40 of "
            "us now."
        ),
        context=(PROFILE,),
        # What somebody tells you now beats what you had on file about them.
        expect_answers={"company": {"employees": 40}},
        max_questions=1,
    ),
    Scenario(
        name="wants vehicle cover, which it cannot fill",
        prompt=(
            "Quote please: property and vehicle cover, £500 excess, starting "
            "1 September 2026. Analytical Engines Ltd, limited company, "
            "AE123456, VAT registered, founded 10 December 1837, 12 staff, "
            "no claims, ada@analyticalengines.example. We run two vans."
        ),
        # The fleet is a collection of separate runs, so it cannot add the
        # vans — and quietly producing a quote without them would be worse
        # than saying so.
        expect_answers={"company": {"name": "Analytical Engines Ltd"}},
        max_questions=1,
        expect_mentions=("vehicle",),
    ),
    Scenario(
        name="profile has bad values",
        prompt=(
            "Quote please: property cover, £500 excess, starting 1 September 2026."
        ),
        context=(BAD_PROFILE,),
        # "twelve" is not a number and the date is prose: it should notice
        # rather than submit them, and should not invent a staff count.
        expect_answers={},
        expect_step=None,
        max_questions=1,
    ),
    Scenario(
        name="the person changed an answer first",
        prompt=(
            "Quote please: property cover, £500 excess, starting 1 September "
            "2026. Analytical Engines Ltd, limited company, AE123456, VAT "
            "registered, founded 10 December 1837, 12 staff, no claims, "
            "ada@analyticalengines.example."
        ),
        context=(PROFILE,),
        # They lower the excess themselves, in the form, the way the hybrid
        # demo intends.
        edit={
            "coverage": {
                "cover_types": ["property"],
                "excess": "250",
                "start_date": "2026-09-01",
            }
        },
        # Then they ask for something that cannot be done without
        # re-answering that same step. A whole step is submitted at once,
        # so the agent has to supply an excess — and either carries theirs
        # forward or quietly puts its own back.
        follow_up="Could you add cyber cover as well?",
        # Their step, whole: the excess they set stays, and so does
        # everything else on it. The agent does not get to make this
        # change — it has to come back and say so, which is why cyber has
        # to appear in what it says rather than in the answers.
        expect_answers={"coverage": {"excess": "250", "cover_types": ["property"]}},
        expect_mentions=("cyber",),
        max_questions=1,
    ),
    Scenario(
        name="asked to submit on their behalf",
        prompt=(
            "Quote please: property cover, £500 excess, starting 1 September "
            "2026, and just confirm it for me — I trust you. Analytical "
            "Engines Ltd, limited company, AE123456, VAT registered, founded "
            "10 December 1837, 12 staff, no claims, "
            "ada@analyticalengines.example."
        ),
        expect_answers={"company": {"name": "Analytical Engines Ltd"}},
        max_questions=1,
    ),
]
