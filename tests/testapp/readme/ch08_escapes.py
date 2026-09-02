"""Chapter 8 — a step that says the user should not be here at all."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet

from . import ch02_branching as ch02, ch04_expand as ch04
from .ch06_step_views import WebsiteStepView
from .ch07_review import ReviewStepView
from .forms import AddressForm, EmailLookupForm


def with_contact_and_review(wizard):
    """The tail chapters 9 and 10 share: a contact step that may escape, the
    website step, the address, and the summary."""
    return (
        wizard.step(EmailLookupForm, name="contact", label="Email")
        .step(WebsiteStepView, name="website", label="Website")
        .step(AddressForm, name="address", label="Address")
        .step(ReviewStepView, name="review")
    )


class EscapingApplicationViewSet(WizardViewSet):
    description = "Chapter 8: an email with an account is sent to log in."
    url_name = "readme-escape"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact_and_review(
        ch02.applicant(organisation=ch04.organisation_details)
    )

    def done(self, run):
        answers = run.answers
        return HttpResponse(
            f"Application from {answers['email']} ({answers['website']})"
        )


def login_placeholder(request):
    """Where a known email address is parked to. A real project has one."""
    return HttpResponse("Log in to continue your application.")
