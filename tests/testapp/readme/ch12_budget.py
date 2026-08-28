"""Chapter 12 — budget lines. A list the applicant grows, one wizard per
line, on a task list beside the project itself."""

from gandalf.collections import CollectionView, ItemMemberMixin
from gandalf.hubs import HubView, Member, WizardMemberMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .ch06_review import ReviewStepView
from .forms import BudgetLineForm, ProjectForm


class BudgetLineViewSet(ItemMemberMixin, WizardViewSet):
    description = "Chapter 12: one budget line of a collection the applicant grows."
    url_name = "readme-budget-line"
    template_name = "testapp/linear_wizard.html"
    collection_key = "budget"
    hub_url_name = "readme-budget"
    # The answer that names a row. Cached when the line finishes, so the
    # page reads a string and a row still costs no walk.
    item_title_step = "line"
    item_title_field = "item"
    wizard = (
        Wizard()
        .step(BudgetLineForm, name="line", label="Budget line")
        .step(ReviewStepView, name="review")
    )


class BudgetCollectionView(CollectionView):
    description = "Chapter 12: the budget — add, change and remove lines."
    template_name = "testapp/budget.html"
    remove_template_name = "testapp/budget_remove.html"
    url_name = "readme-budget"
    member_key = "budget"
    item_viewset = BudgetLineViewSet
    item_name = "Budget line"
    item_reopen_step = "review"
    min_items = 1
    hub_url_name = "readme-project-hub"


class ProjectMemberViewSet(WizardMemberMixin, WizardViewSet):
    description = "Chapter 12: the project member beside the budget."
    url_name = "readme-project"
    template_name = "testapp/linear_wizard.html"
    member_key = "project"
    hub_url_name = "readme-project-hub"
    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )


class ProjectHubView(HubView):
    description = "Chapter 12: a task list whose second row is a collection."
    template_name = "testapp/readme_hub.html"
    url_name = "readme-project-hub"
    member_url_name = "readme-project-hub-member"
    members = [
        Member("project", ProjectMemberViewSet, title="Project", reopen_step="review"),
        # A collection is a hub, and a hub is a member: the row links
        # straight at its page and reads its own status.
        Member("budget", BudgetCollectionView, title="Budget"),
    ]
