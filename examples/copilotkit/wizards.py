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
from examples.insurance import InsuranceQuoteViewSet, quote_for
from examples.licence import LicenceCheckViewSet
from tests.testapp.durable import ModelStorage


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
        quote = quote_for(bound_wizard)
        log_event("quote", run=bound_wizard.run_id, **quote)
        return render(self.request, "hybrid/done.html", quote)


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
