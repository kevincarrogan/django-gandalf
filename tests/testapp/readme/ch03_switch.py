"""Chapter 3 — which kind of organisation. One case per outcome."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard

from . import ch02_branching as ch02
from .forms import CharityNumberForm, CompanyNumberForm, EmailForm, OrganisationTypeForm


def organisation_kind(context):
    """The selector: which case applies. It reads the answer and returns
    the case name — the same as `on_field("organisation-type",
    "organisation_type")`, written out."""
    step = context.run.path.find_step(name="organisation-type")
    return step.form.cleaned_data["organisation_type"]


#: Chapter 2's organisation arm, grown. `ch02.organisation_details` is
#: untouched — every call on a Wizard returns a new one.
organisation_details = ch02.organisation_details.step(
    OrganisationTypeForm, name="organisation-type"
).switch(
    organisation_kind,
    {
        "charity": Wizard().step(CharityNumberForm, name="charity-number"),
        "company": Wizard().step(CompanyNumberForm, name="company-number"),
    },
    # A community group has no number to give, so there is no default
    # arm: the walk continues past the switch.
)


class SwitchingApplicationViewSet(WizardViewSet):
    description = "Chapter 3: a switch with a case per kind of organisation."
    url_name = "readme-switch"
    template_name = "testapp/linear_wizard.html"
    wizard = ch02.applicant(organisation=organisation_details).step(
        EmailForm, name="contact"
    )

    def done(self, run):
        answers = MergeCleanedData().reduce(run.path)
        number = answers.get("charity_number") or answers.get("company_number")
        who = answers.get("organisation_name") or answers["occupation"]
        return HttpResponse(
            f"Application from {who}" + (f" ({number})" if number else "")
        )
