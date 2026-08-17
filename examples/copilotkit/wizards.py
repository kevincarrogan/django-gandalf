"""The hybrid demo's wizard: mounted at real URLs, stored durably.

Two changes to `examples.insurance.InsuranceQuoteViewSet`, and they are
exactly what a handover needs. `url_name` gives the run addressable step
URLs, so the agent can hand a person a link. `storage_class` moves the run
out of a browser session into the database, so the run the agent filled is
the run the browser opens — the same run id, the same answers, the same
walk, whichever door it is reached through.
"""

from django.shortcuts import render

from examples.eventlog import DemoObserver, log_event
from gandalf.contrib.agent import AgentProfile
from examples.insurance import (
    InsuranceQuoteViewSet,
    VehicleCollectionView,
    VehicleItemViewSet,
    quote_for,
)
from examples.identity import IdentityCheckViewSet
from examples.licence import LicenceCheckViewSet
from tests.testapp.durable import ModelCollectionStore, ModelStorage


class HybridQuoteViewSet(InsuranceQuoteViewSet):
    url_name = "quote"
    storage_class = ModelStorage
    template_name = "hybrid/step.html"

    def configure_wizard(self, wizard):
        """Watch this wizard, whichever door it is driven through."""
        return wizard.configure(
            template_name=self.template_name, observer_class=DemoObserver
        )

    def done(self, bound_wizard):
        """Fires once, from whichever side confirmed — and in this demo
        that is always the human, on the review page."""
        quote = quote_for(bound_wizard, vehicle_values=fleet_values)
        log_event("quote", run=bound_wizard.run_id, **quote)
        return render(self.request, "hybrid/done.html", quote)


class AdaptiveQuoteViewSet(HybridQuoteViewSet):
    """The same quote, for the agent that can reach the fleet.

    It exists for one sentence. `InsuranceQuoteViewSet`'s profile tells an
    agent it cannot add a vehicle and must never try, which is true of every
    agent holding only `RunDriver` — and false of this one, which has the
    collection's own verbs. Left in place the two would contradict each
    other, and a rule a model can find on both sides of is one it will
    break: this demo has already lost a boundary that way once, and the
    lesson written down then was that the tool's description and the prompt
    must not disagree.

    Everything else is inherited, `url_name` included, so a handover link
    still points at the same pages.
    """

    agent = AgentProfile(
        purpose="a business insurance quote",
        notes=(
            "Vehicles are not steps of this quote — they are a list of their "
            "own — but you can add to that list, with `get_the_fleet` and "
            "`add_a_vehicle`. Add one whenever they tell you about it. What "
            "you cannot do is say the fleet is finished: only they know "
            "whether there is another, so ask them and hand over the page."
        ),
    )


class HybridVehicleItemViewSet(VehicleItemViewSet):
    """One vehicle, kept where somebody other than this browser can find it.

    Both stores are swapped, which is what a durable collection needs:
    `storage_class` for the run itself and `section_store_class` for the
    registry that says the run exists. Swapping one gives you durable
    answers nobody can find, or an index into runs that have expired.
    """

    storage_class = ModelStorage
    section_store_class = ModelCollectionStore


class HybridVehicleCollectionView(VehicleCollectionView):
    """The fleet page, over the same two stores.

    This is what lets an agent add a vehicle at all. It drives a fabricated
    request — no browser, no session, and this demo's sessions live in a
    signed cookie, so there is nothing it could share even in principle.
    Scoped to the *user* instead, both sides see one fleet.
    """

    section_store_class = ModelCollectionStore
    item_viewset = HybridVehicleItemViewSet


def fleet_values(context):
    """Every finished vehicle's value, read off the collection itself.

    The session copy `examples.insurance` keeps is the right shape for a
    demo with no database and the wrong one here: an agent writes it to a
    request the browser will never see. The collection already holds the
    answers durably — a finished section stashes its own state — so this
    reads them from there and there is no second copy to disagree.
    """
    page = HybridVehicleCollectionView()
    page.setup(context.http_request())
    store = page.get_collection_store()
    values = []
    for item_id in page.get_item_ids():
        stash = store.get_stash(page.item_section_key(item_id))
        if not stash:
            continue
        for entry in stash.get("state", []):
            answers = entry.get("step") or {}
            if "value" in answers:
                values.append(answers["value"])
    return values


class HybridLicenceViewSet(LicenceCheckViewSet):
    """The licence check, mounted and stored the way the quote is.

    Same two changes and the same reason: addressable step URLs so the
    agent can hand back a link, and durable storage so the run it filled
    is the run the browser opens. The scan the agent attached is on that
    run, so the person sees their own photograph above the details it was
    read from.
    """

    url_name = "licence"
    storage_class = ModelStorage
    template_name = "hybrid/licence_step.html"

    def configure_wizard(self, wizard):
        return wizard.configure(
            template_name=self.template_name, observer_class=DemoObserver
        )


class HybridIdentityViewSet(IdentityCheckViewSet):
    """The document-free check, mounted and stored like the others.

    Worth having beside `HybridLicenceViewSet` rather than instead of it:
    they ask for the same four things and differ only in whether the run
    keeps the photograph. One proves a document can be *stored*; this one
    proves it only ever had to be *read*.
    """

    url_name = "identity"
    storage_class = ModelStorage
    template_name = "hybrid/identity_step.html"

    def configure_wizard(self, wizard):
        return wizard.configure(
            template_name=self.template_name, observer_class=DemoObserver
        )
