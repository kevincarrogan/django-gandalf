"""Chapter 11 — a task list. The application becomes several wizards the
applicant can do in any order."""

from gandalf.hubs import Hub, HubViewSet
from gandalf.wizard import Wizard

from .ch06_review import AddressReviewStepView, ReviewStepView
from .forms import AddressForm, ApplicantForm, EmailForm


contact = (
    Wizard()
    .step(ApplicantForm, name="name", label="Your name")
    .step(EmailForm, name="email", label="Email")
    # A review step is what makes re-opening safe: without it, one
    # successful edit walks straight through to done() again.
    .step(ReviewStepView, name="review")
)

address = (
    Wizard()
    .step(AddressForm, name="address", label="Address")
    .step(AddressReviewStepView, name="review")
)


class GrantHubViewSet(HubViewSet):
    description = "Chapter 11: a task list over two independent members."
    template_name = "testapp/readme_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-hub"
    hub = (
        Hub()
        .member("contact", contact, title="Contact details", reopen="review")
        .member("address", address, title="Address", reopen="review")
    )
