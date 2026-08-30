"""Chapter 7 — check your answers. Editing is a link, and a summary page is
the same three questions asked of every answer."""

from django.http import HttpResponse

from gandalf.form_views import StepFormView
from gandalf.summary import Group, Hide, SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData

from . import ch02_branching as ch02, ch04_expand as ch04
from .forms import AddressForm, ConfirmForm, EmailForm


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


class AddressReviewStepView(ReviewStepView):
    """The same page, for a wizard with an address in it: four fields on one
    line, and the lookup token on none."""

    summary_fields = {
        "address": [
            Group("line_1", "line_2", "town", "postcode"),
            Hide("lookup_token"),
        ],
    }


def with_contact_and_review(wizard):
    """The tail every chapter from here shares: how to reach the applicant,
    where they are, and a look back over all of it."""
    return (
        wizard.step(EmailForm, name="contact", label="Email")
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
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
