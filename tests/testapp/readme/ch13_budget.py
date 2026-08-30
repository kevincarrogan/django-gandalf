"""Chapter 13 — budget lines. A list the applicant grows, one wizard per
line, on a task list beside the project itself."""

from gandalf.tasklists import AddAnother, Section, TaskList, TaskListViewSet
from gandalf.wizard import Wizard

from .ch07_review import ReviewStepView
from .forms import BudgetLineForm, ProjectForm


project = (
    Wizard()
    .step(ProjectForm, name="project", label="Project")
    .step(ReviewStepView, name="review")
)

budget_line = (
    Wizard()
    .step(BudgetLineForm, name="line", label="Budget line")
    .step(ReviewStepView, name="review")
)


class Project(TaskList):
    project = Section(project, title="Project", reopen_at="review")
    # An add-another row is an entry like any other: the row links straight
    # at its page and reads its own status.
    budget = AddAnother(
        budget_line,
        title="Budget",
        item_name="Budget line",
        # The answer that names a row, cached when the line finishes.
        item_title=("line", "item"),
        min_items=1,
        reopen_at="review",
        template_name="testapp/budget.html",
        remove_template_name="testapp/budget_remove.html",
    )


class ProjectViewSet(TaskListViewSet):
    description = "Chapter 13: a task list whose second row is an add-another."
    template_name = "testapp/readme_hub.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-project"
    task_list = Project
