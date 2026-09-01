"""Chapter 7 — check your answers. Editing is a link, and a summary page is
the same three questions asked of every answer."""

from django.http import HttpResponse

from gandalf.form_views import StepFormView
from gandalf.summary import Group, Hide, SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData

from . import ch02_branching as ch02, ch04_expand as ch04
from .forms import AddressForm, ConfirmForm, EmailForm


class AddressStepView(StepFormView):
    """The address step, saying how its own answers read: four fields on one
    line, and the token that looked them up on none. Said here rather than on
    a review page, because the step is what knows an address is an address."""

    form_class = AddressForm
    template_name = "testapp/linear_wizard.html"
    summary_fields = [
        Group("line_1", "line_2", "town", "postcode"),
        Hide("lookup_token"),
    ]


class ReviewStepView(SummaryMixin, StepFormView):
    """Check your answers. It names no steps and shapes nothing: the address
    reads as one line because `AddressForm` says so, so the same review view
    serves every wizard from here on."""

    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


def with_contact_and_review(wizard):
    """The tail every chapter from here shares: how to reach the applicant,
    where they are, and a look back over all of it."""
    return (
        wizard.step(EmailForm, name="contact", label="Email")
        .step(AddressStepView, name="address", label="Address")
        .step(ReviewStepView, name="review")
    )


class ReviewedApplicationViewSet(WizardViewSet):
    description = (
        "Chapter 7: edit links, a check-your-answers page, and dormant memory."
    )
    url_name = "readme-review"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact_and_review(
        ch02.applicant(organisation=ch04.organisation_details)
    )

    def done(self, run):
        answers = MergeCleanedData().reduce(run.path)
        who = answers.get("organisation_name") or answers["occupation"]
        return HttpResponse(f"Application from {who} confirmed")
