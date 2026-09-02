"""Chapter 4 — as many trustees as there are. The tree grows from an
answer the user has just given."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from . import ch02_branching as ch02, ch03_switch as ch03
from .forms import EmailForm, TrusteeCountForm, TrusteeForm


def build_trustee_steps(context):
    count = context.run.path.find_step(name="trustees").answer["trustees"]
    steps = Wizard()
    for index in range(count):
        steps = steps.step(TrusteeForm, name=f"trustee-{index}")
    return steps


organisation_details = ch03.organisation_details.step(
    TrusteeCountForm, name="trustees"
).expand(build_trustee_steps)


class ExpandingApplicationViewSet(WizardViewSet):
    description = "Chapter 4: one step per trustee, grown from the count."
    url_name = "readme-expand"
    template_name = "testapp/linear_wizard.html"
    wizard = ch02.applicant(organisation=organisation_details).step(
        EmailForm, name="contact"
    )

    def done(self, run):
        trustees = [
            step.answer["name"]
            for step in run.path
            if step.name and step.name.startswith("trustee-")
        ]
        return HttpResponse("Trustees: " + ", ".join(trustees))
