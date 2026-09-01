"""Chapter 12 — a task list. The application becomes several wizards the
applicant can do in any order."""

from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin
from gandalf.tasklists import Section, TaskList, TaskListViewSet
from gandalf.wizard import Wizard

from .ch07_review import AddressReviewStepView
from .forms import AddressForm, ApplicantForm, ConfirmForm, EmailForm


class ReviewStepView(SummaryMixin, StepFormView):
    """Check your answers, for a wizard with nothing in it that needs
    shaping. A review view is configured for the wizard it sits in, so a
    section without an address carries no `summary_fields` at all."""

    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


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


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details", reopen_at="review")
    address = Section(address, title="Address", reopen_at="review")


class GrantApplicationViewSet(TaskListViewSet):
    description = "Chapter 12: a task list over two independent sections."
    template_name = "testapp/readme_task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-task-list"
    task_list = GrantApplication
