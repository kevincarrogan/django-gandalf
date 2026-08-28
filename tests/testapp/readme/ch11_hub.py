"""Chapter 11 — a task list. The application becomes several wizards the
applicant can do in any order."""

from gandalf.hubs import HubView, Member, WizardMemberMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .ch06_review import AddressReviewStepView, ReviewStepView
from .forms import AddressForm, ApplicantForm, EmailForm


class ContactMemberViewSet(WizardMemberMixin, WizardViewSet):
    description = "Chapter 11: the contact member of the task list."
    url_name = "readme-hub-contact"
    template_name = "testapp/linear_wizard.html"
    member_key = "contact"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        # A review step is what makes re-opening safe: without it, one
        # successful edit walks straight through to done() again.
        .step(ReviewStepView, name="review")
    )


class AddressMemberViewSet(WizardMemberMixin, WizardViewSet):
    description = "Chapter 11: the address member of the task list."
    url_name = "readme-hub-address"
    template_name = "testapp/linear_wizard.html"
    member_key = "address"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class GrantHubView(HubView):
    description = "Chapter 11: a task list over two independent members."
    template_name = "testapp/readme_hub.html"
    url_name = "readme-hub"
    member_url_name = "readme-hub-member"
    members = [
        # `reopen_step` lands a finished member back on its review page, so
        # re-entering shows the answers with a change link each rather than
        # dropping the user at step one.
        Member(
            "contact",
            ContactMemberViewSet,
            title="Contact details",
            reopen_step="review",
        ),
        Member("address", AddressMemberViewSet, title="Address", reopen_step="review"),
    ]
