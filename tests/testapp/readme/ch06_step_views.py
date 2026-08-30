"""Chapter 6 — a step with a view of its own."""

from django.http import HttpResponse

from gandalf.form_views import StepFormView
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData

from . import ch02_branching as ch02, ch04_expand as ch04
from .forms import EmailForm, WebsiteForm


class WebsiteStepView(StepFormView):
    form_class = WebsiteForm
    template_name = "testapp/other_linear_wizard.html"

    def get_initial(self):
        initial = super().get_initial()  # the stored answer, on a revisit
        contact = self.request.wizard.path.find_step(name="contact")
        if contact is not None and "website" not in initial:
            domain = contact.form.cleaned_data["email"].partition("@")[2]
            initial["website"] = f"https://{domain}"
        return initial


def with_contact(wizard):
    return wizard.step(EmailForm, name="contact", label="Email").step(
        WebsiteStepView, name="website", label="Website"
    )


class WebsiteApplicationViewSet(WizardViewSet):
    description = "Chapter 6: a step view that prefills from an earlier answer."
    url_name = "readme-step-view"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact(ch02.applicant(organisation=ch04.organisation_details))

    def done(self, run):
        answers = MergeCleanedData().reduce(run.path)
        return HttpResponse(
            f"Application from {answers['email']} ({answers['website']})"
        )
