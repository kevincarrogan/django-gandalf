"""Tools for a collection, so the fleet stops being where the agent goes quiet.

`gandalf.driver` drives one run. A collection is many runs behind one page —
each vehicle is its own wizard, minted with its own id — so an agent holding
`RunDriver` can fill a quote and cannot add a van. `examples/insurance.py`
says so in a comment, and the demo's `AgentProfile` says so out loud, which
is the honest thing to do about a limit and no substitute for lifting it.

Lifting it needs no new library API. A collection page is an ordinary Django
view, and its four verbs — add, change, remove, declare done — are ordinary
methods on it: `add_item()` mints and registers an id, `get_item_ids()` is
the registry, `get_member_rows()` is what the person would see. Set the view
up against a fabricated request and they all answer. What the item id then
buys is a URL kwarg, and `RunDriver.begin(ItemViewSet, item=…)` already takes
those — so filling one vehicle is the same driver doing the same thing it
does for any wizard.

Two decisions worth naming, because neither is forced by the code.

**It finishes what it adds.** Everywhere else this demo stops short of
confirming, and that rule is about the *quote*: `done()` is where the price
is struck and only the person may strike it. A vehicle is not that. Its
`run_done` writes a registration and a value onto the person's own list,
which they can see and remove, and which commits them to nothing — and an
item left unfinished is worse than not added, because it has no title, shows
as *not started*, and prices as zero. Half a vehicle is not a smaller
version of a vehicle.

**It never says the fleet is complete.** That is `declare_done`, the answer
to *any more to add?*, and it is the one thing here that storage genuinely
cannot infer — nobody but the person knows whether there is another van. So
there is no tool for it, and the agent hands over the page instead.

Everything it adds is marked `{"unattended": True}` like any other placement,
so the fleet page and the demo's edit rule can tell whose a row is.
"""

from typing import Any

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset

from examples.copilotkit.wizards import (
    HybridVehicleCollectionViewSet,
    HybridVehicleItemViewSet,
)
from gandalf.contrib.agent import WizardDeps
from gandalf.driver import RunDriver, outline_steps

FLEET_RULE = """\
Vehicles are not steps of the quote. They are a list of their own, one run
per vehicle, and you have tools for it: `get_the_fleet` to see what is on it
and what a vehicle needs, `add_a_vehicle` to put one on.

Use them when somebody tells you about a vehicle, and when they have asked
for vehicle cover — a quote with vehicle cover and an empty fleet prices as
though they had none, which is not what they asked for and does not look
wrong until the number arrives.

You cannot say the fleet is finished. Only they know whether there is
another one, so when you have added what they told you about, ask whether
that is all of them and give them the fleet page.\
"""


def fleet_tools() -> FunctionToolset[WizardDeps]:
    """The collection verbs an agent is allowed."""
    toolset: FunctionToolset[WizardDeps] = FunctionToolset()

    def _page(ctx: RunContext[WizardDeps]) -> HybridVehicleCollectionViewSet:
        # A collection page is a Django view and still wants a request; the
        # context makes one on demand, which is the point of it — the walk
        # no longer needs a browser but a `TemplateView` never stopped being
        # one.
        page = HybridVehicleCollectionViewSet()
        page.setup(ctx.deps.context.http_request())
        return page

    def _fleet(page: HybridVehicleCollectionViewSet) -> dict[str, Any]:
        collection = page.get_collection()
        return {
            "vehicles": [
                {
                    "item_id": page.item_id_for(row.member),
                    "title": str(row.title),
                    "status": str(row.status),
                    "change_url": page.get_item_url(page.item_id_for(row.member)),
                }
                for row in page.get_member_rows()
            ],
            "count": collection.count,
            # Theirs to answer, so it is reported and never set here.
            "they_have_said_that_is_all": collection.is_complete,
            "fleet_page": page.get_page_url(),
        }

    @toolset.tool
    def get_the_fleet(ctx: RunContext[WizardDeps]) -> dict[str, Any]:
        """What is on the fleet, and what one vehicle needs.

        The schema is the item wizard's own, so send `add_a_vehicle`
        exactly what it asks for. `they_have_said_that_is_all` is the
        person's answer to *any more to add?* — you cannot set it."""
        page = _page(ctx)
        schemas = {
            entry["step"]: entry["schema"]
            for entry in outline_steps(RunDriver.outline_for(HybridVehicleItemViewSet))
            if entry.get("schema")
        }
        return {**_fleet(page), "a_vehicle_needs": schemas}

    @toolset.tool
    def add_a_vehicle(
        ctx: RunContext[WizardDeps], answers: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Put one vehicle on the fleet. `answers` is keyed by the item
        wizard's step names, the way `prefill` is — `{"vehicle": {...}}`.

        One call is one vehicle. Adding it finishes it, so it counts
        towards the quote and shows on their page under its registration;
        an unfinished one prices as nothing. Say what you added."""
        page = _page(ctx)
        page.add_item()
        item_id = page.get_item_ids()[-1]

        driver = RunDriver.begin(
            HybridVehicleItemViewSet,
            item=item_id,
            # The conversation's own context, addressing this vehicle. Url
            # kwargs named beside a context used to be dropped, which made
            # this the one call that had to reach for the actor instead;
            # `WizardContext.addressing` means it no longer does.
            context=ctx.deps.context,
            may_finish=True,
        )
        result = driver.prefill(answers)
        if result.errors:
            # The item is registered but empty, which reads on their page as
            # a half-added vehicle. Take it back off rather than leave one.
            page.remove_item(item_id)
            raise ModelRetry(
                f"That vehicle did not validate, so nothing was added: "
                f"{result.errors}. Fix it and call add_a_vehicle again."
            )

        # The item's own review step, which is a confirmation of a row on a
        # list rather than of a price. See the module docstring.
        described = driver.describe()
        if described.step is not None:
            driver.submit({"confirmed": True}, step=described.step)
        driver.finish()

        return {
            "added": item_id,
            "answers": driver.answers(json_safe=True),
            **_fleet(_page(ctx)),
        }

    return toolset
