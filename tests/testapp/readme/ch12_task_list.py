"""Chapter 12 — a task list. The application becomes several wizards the
applicant can do in any order."""

from gandalf.tasklists import Section, TaskList, TaskListViewSet
from gandalf.wizard import Wizard

from .ch07_review import AddressReviewStepView, ReviewStepView
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


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details", reopen_at="review")
    address = Section(address, title="Address", reopen_at="review")


class GrantApplicationViewSet(TaskListViewSet):
    description = "Chapter 12: a task list over two independent sections."
    template_name = "testapp/readme_task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-task-list"
    task_list = GrantApplication
