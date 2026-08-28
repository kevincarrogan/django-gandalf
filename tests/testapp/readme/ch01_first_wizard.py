"""Chapter 1 — a first wizard. Two questions in a row, and something that
happens once when both are answered."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard

from .forms import ApplicantForm, EmailForm


class FirstApplicationViewSet(WizardViewSet):
    description = "Chapter 1: two steps in a row, and a done() that runs once."
    url_name = "readme-first"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(ApplicantForm, name="applicant").step(EmailForm, name="contact")
    )

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"Application received from {answers['full_name']} <{answers['email']}>"
        )
