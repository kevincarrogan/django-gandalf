"""Chapter 7 — a step with a view of its own, and a step that says the
user should not be here at all."""

from django.http import HttpResponse

from gandalf.form_views import StepFormView
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData

from . import ch02_branching as ch02, ch04_expand as ch04
from .ch06_review import AddressReviewStepView
from .forms import AddressForm, EmailLookupForm, WebsiteForm


class WebsiteStepView(StepFormView):
    form_class = WebsiteForm
    template_name = "testapp/other_linear_wizard.html"

    def get_initial(self):
        initial = super().get_initial()
        contact = self.request.wizard.path.find_step(name="contact")
        domain = contact.form.cleaned_data["email"].partition("@")[2]
        initial["website"] = f"https://{domain}"
        return initial


def with_contact_and_review(wizard):
    return (
        wizard.step(EmailLookupForm, name="contact", label="Email")
        .step(WebsiteStepView, name="website", label="Website")
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class LookedUpApplicationViewSet(WizardViewSet):
    description = "Chapter 7: a step view that prefills, and an escape to log in."
    url_name = "readme-step-view"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact_and_review(
        ch02.applicant(organisation=ch04.organisation_details)
    )

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"Application from {answers['email']} ({answers['website']})"
        )


def login_placeholder(request):
    """Where a known email address is parked to. A real project has one."""
    return HttpResponse("Log in to continue your application.")
