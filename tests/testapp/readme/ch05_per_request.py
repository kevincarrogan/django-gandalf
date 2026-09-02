"""Chapter 5 — a wizard per request. The shape depends on something known
at the front door — who is signed in, which URL — not on an answer."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet

from . import ch02_branching as ch02, ch04_expand as ch04
from .forms import EmailForm, PortfolioForm, ReceivedOnForm


class PaperApplicationViewSet(WizardViewSet):
    description = "Chapter 5: a signed-in staff member is asked one thing more."
    url_name = "readme-paper"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, run):
        wizard = ch02.applicant(organisation=ch04.organisation_details)
        if self.request.user.is_staff:
            wizard = wizard.step(ReceivedOnForm, name="received-on")
        return wizard.step(EmailForm, name="contact")

    def done(self, run):
        answers = run.answers
        received = answers.get("received_on")
        return HttpResponse(
            f"Application from {answers['email']}"
            + (f", received on {received.isoformat()}" if received else "")
        )


class FundApplicationViewSet(WizardViewSet):
    description = "Chapter 5: the fund in the URL decides the shape."
    url_name = "readme-fund"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, run):
        wizard = ch02.applicant(organisation=ch04.organisation_details)
        if self.kwargs["fund"] == "arts":
            wizard = wizard.step(PortfolioForm, name="portfolio")
        return wizard.step(EmailForm, name="contact")

    def done(self, run):
        answers = run.answers
        return HttpResponse(
            f"Application to the {self.kwargs['fund']} fund from {answers['email']}"
        )
