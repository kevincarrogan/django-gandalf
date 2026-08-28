"""Chapter 11 — a task list. The application becomes several wizards the
applicant can do in any order."""

from gandalf.sections import HubView, Section, SectionMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .ch06_review import AddressReviewStepView, ReviewStepView
from .forms import AddressForm, ApplicantForm, EmailForm


class ContactSectionViewSet(SectionMixin, WizardViewSet):
    description = "Chapter 11: the contact section of the task list."
    url_name = "readme-hub-contact"
    template_name = "testapp/linear_wizard.html"
    section_key = "contact"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        # A review step is what makes re-opening safe: without it, one
        # successful edit walks straight through to done() again.
        .step(ReviewStepView, name="review")
    )


class AddressSectionViewSet(SectionMixin, WizardViewSet):
    description = "Chapter 11: the address section of the task list."
    url_name = "readme-hub-address"
    template_name = "testapp/linear_wizard.html"
    section_key = "address"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class GrantHubView(HubView):
    description = "Chapter 11: a task list over two independent sections."
    template_name = "testapp/readme_hub.html"
    url_name = "readme-hub"
    section_url_name = "readme-hub-section"
    sections = [
        # `reopen_step` lands a finished section back on its review page, so
        # re-entering shows the answers with a change link each rather than
        # dropping the user at step one.
        Section(
            "contact",
            ContactSectionViewSet,
            title="Contact details",
            reopen_step="review",
        ),
        Section(
            "address", AddressSectionViewSet, title="Address", reopen_step="review"
        ),
    ]
