"""The demo's task list: one application made of the parts it already had.

The other demos are one wizard each, and a wizard is not always the whole
thing. A real business insurance application is several: who you are, the
licence behind the cover, the vehicles, the cover itself — each answerable
in any order, each with its own check-your-answers page, and one submit at
the end that prices the lot.

Nothing here is a new domain. The four wizards are the ones already
mounted standalone, declared again as sections of a page rather than as
four separate errands, which is what makes this worth having: the *same*
declarations, read by a driver that sees a journey instead of a run.

Two things it exists to exercise that no other demo could.

**A gate.** `CoverSection` is `blocked()` until the identity check is
stashed, so the row reads *Cannot start yet* and its door refuses — both
doors, now that `check_door()` asks. An agent told to fill everything in
meets a rule the person's page has too, and has to work out that the way
past it is to do the other part first.

**A list beside a section.** The fleet is an `AddAnother` row, so
`add_to_list` and `remove_from_list` are exercised against a page rather
than against the hand-written toolset `fleet.py` had to be before there
was a `JourneyDriver`.
"""

from django.shortcuts import render

from examples.copilotkit.wizards import (
    HybridIdentityViewSet,
    HybridLicenceViewSet,
)
from examples.eventlog import DemoObserver, log_event
from examples.insurance import InsuranceQuoteViewSet, VehicleItem, quote_for
from gandalf.contrib.agent import AgentProfile
from gandalf.tasklists import (
    AddAnother,
    Section,
    SectionViewSet,
    TaskList,
    TaskListViewSet,
)
from tests.testapp.durable import ModelItemStore, ModelStorage


class ApplicationSection(SectionViewSet):
    """What every part of this application shares.

    The observer, so a section driven from the chat shows up in the event
    log beside one walked in the browser; and the template, so the pages
    look like the rest of the demo. Storage is set once on the page below
    and reaches every section from there.
    """

    template_name = "hybrid/step.html"

    def configure_wizard(self, wizard):
        return wizard.configure(
            template_name=self.template_name, observer_class=DemoObserver
        )


class IdentitySection(ApplicationSection):
    """Who they are. First because everything else waits on it."""

    wizard = HybridIdentityViewSet.wizard

    def run_done(self, run):
        """Record the name on the journey, where every other part can read
        it without walking this one again."""
        answer = run.path.find_step(name="name").answer
        self.get_journey_store().data["applicant"] = (
            f"{answer['first_name']} {answer['surname']}"
        )
        return super().run_done(run)


class LicenceSection(ApplicationSection):
    """The driving licence behind the cover — the part with a document."""

    wizard = HybridLicenceViewSet.wizard
    template_name = "hybrid/licence_step.html"


def fleet_values(store):
    """Every finished vehicle's value, read off the journey's own record.

    The vehicles are stashed under the fleet's key, one per item, so this
    is the same read the page makes to draw its rows — there is no second
    copy of the fleet to disagree with the first.
    """
    values = []
    for item_id in store.item_ids("fleet"):
        stash = store.get_stash(f"fleet:{item_id}")
        for entry in stash.get("state", []):
            answers = entry.get("step") or {}
            if "value" in answers:
                values.append(answers["value"])
    return values


class CoverSection(ApplicationSection):
    """What they want covered, and for how much.

    Blocked until the identity check is done, which is the rule this demo
    exists to show an agent meeting: there is no way round it and no tool
    that overrides it, so the only way through is to do the other part
    first and come back.
    """

    wizard = InsuranceQuoteViewSet.wizard

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("identity")

    def run_done(self, run):
        """Price it here, where the run is in hand and a walk has already
        been paid for. The page's submit renders what this worked out."""
        store = self.get_journey_store()
        store.data["quote"] = quote_for(
            run, vehicle_values=lambda _: fleet_values(store)
        )
        return super().run_done(run)


class Application(TaskList):
    identity = Section(
        IdentitySection, title="Confirm who you are", reopen_at="confirm"
    )
    licence = Section(LicenceSection, title="Your driving licence", reopen_at="confirm")
    fleet = AddAnother(
        VehicleItem,
        title="Your vehicles",
        item_title="registration",
        reopen_at="review",
    )
    cover = Section(CoverSection, title="What you want covered", reopen_at="confirm")


class ApplicationViewSet(TaskListViewSet):
    """The page. Durably stored, so the application an agent filled is the
    application the browser opens — the same handover the single wizards
    make, one level up."""

    url_name = "application"
    storage_class = ModelStorage
    journey_store_class = ModelItemStore
    task_list = Application
    template_name = "hybrid/application.html"
    section_template_name = "hybrid/step.html"
    add_another_template_name = "hybrid/fleet.html"
    remove_template_name = "hybrid/remove_item.html"

    agent = AgentProfile(
        purpose="a business insurance application",
        notes=(
            "This is several parts, not one form: fill each one by name. "
            "What you want covered cannot be started until they have "
            "confirmed who they are, so do that part first rather than "
            "telling them it is unavailable. Vehicles are a list — add one "
            "at a time, and never say the list is finished, because only "
            "they know whether there is another. You cannot submit the "
            "application; hand them the page and they will."
        ),
    )

    def journey_done(self, page, store):
        """The one irreversible thing, and the person presses it. The quote
        was worked out when they confirmed the cover, so this records the
        application and shows them what it came to."""
        quote = store.data["quote"]
        log_event("application", journey=self.get_journey(), **quote)
        return render(self.request, "hybrid/done.html", quote)
