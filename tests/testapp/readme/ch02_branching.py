"""Chapter 2 — individuals and organisations. The first answer decides
which questions come next."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard, condition

from .forms import AboutYouForm, ApplyingAsForm, EmailForm, OrganisationForm


def is_organisation(context):
    applying_as = context.run.path.find_step(name="applying_as")
    return applying_as.form.cleaned_data["applying_as"] == "organisation"


#: The two arms, as wizards in their own right. Later chapters grow the
#: organisation arm without touching this one.
individual_details = Wizard().step(AboutYouForm, name="about_you")
organisation_details = Wizard().step(OrganisationForm, name="organisation")


def applicant(organisation=organisation_details, individual=individual_details):
    """Who is applying: the question, then the arm the answer selects."""
    return (
        Wizard()
        .step(ApplyingAsForm, name="applying_as")
        .branch(condition(is_organisation, organisation), default=individual)
    )


class BranchingApplicationViewSet(WizardViewSet):
    description = "Chapter 2: a branch on the first answer."
    url_name = "readme-branching"
    template_name = "testapp/linear_wizard.html"
    wizard = applicant().step(EmailForm, name="contact")

    def done(self, run):
        answers = MergeCleanedData().reduce(run.path)
        who = answers.get("organisation_name") or answers["occupation"]
        return HttpResponse(f"Application from {who} <{answers['email']}>")
