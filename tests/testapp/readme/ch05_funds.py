"""Chapter 5 — different funds, different questions. The shape depends on
the request, not on an answer."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData

from . import ch02_branching as ch02, ch04_expand as ch04
from .forms import EmailForm, PortfolioForm


class FundApplicationViewSet(WizardViewSet):
    description = "Chapter 5: the fund in the URL decides the shape."
    url_name = "readme-fund"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, bound_wizard):
        wizard = ch02.applicant(organisation=ch04.organisation_details)
        if self.kwargs["fund"] == "arts":
            wizard = wizard.step(PortfolioForm, name="portfolio")
        return wizard.step(EmailForm, name="contact")

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"Application to the {self.kwargs['fund']} fund from {answers['email']}"
        )
