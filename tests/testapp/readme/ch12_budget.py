"""Chapter 12 — budget lines. A list the applicant grows, one wizard per
line, on a task list beside the project itself."""

from gandalf.collections import Collection
from gandalf.hubs import Hub, HubViewSet
from gandalf.wizard import Wizard

from .ch06_review import ReviewStepView
from .forms import BudgetLineForm, ProjectForm


project = (
    Wizard()
    .step(ProjectForm, name="project", label="Project")
    .step(ReviewStepView, name="review")
)

budget = Collection(
    Wizard()
    .step(BudgetLineForm, name="line", label="Budget line")
    .step(ReviewStepView, name="review"),
    item_name="Budget line",
    # The answer that names a row, cached when the line finishes.
    item_title=("line", "item"),
    min_items=1,
    reopen="review",
    template_name="testapp/budget.html",
    remove_template_name="testapp/budget_remove.html",
)


class ProjectHubViewSet(HubViewSet):
    description = "Chapter 12: a task list whose second row is a collection."
    template_name = "testapp/readme_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-project"
    hub = (
        Hub()
        .member("project", project, title="Project", reopen="review")
        # A collection is a member like any other: the row links straight
        # at its page and reads its own status.
        .collection("budget", budget, title="Budget")
    )
