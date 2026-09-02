"""Chapter 14 — locked and hidden. One section waits on another; one is not
there until an answer says it should be."""

from gandalf.tasklists import Section, SectionViewSet, TaskList, TaskListViewSet
from gandalf.wizard import Wizard

from .ch07_review import ReviewStepView
from .forms import MatchFundingForm, ProjectForm, RefereeForm


MATCH_FUNDING_THRESHOLD = 10_000


def record_amount(store, run):
    """The amount is read off the path here — the one moment the run is
    readable and a walk has already been paid — and written to the journey's
    data, where every other section reads it without a walk."""
    project = run.path.find_step(name="project")
    store.data["amount"] = int(project.form.cleaned_data["amount"])


class ProjectSection(SectionViewSet):
    """Decides whether the match funding section exists."""

    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def done(self, run):
        record_amount(self.get_journey_store(), run)
        return super().done(run)


class MatchFundingSection(SectionViewSet):
    """Not there until the amount asked for crosses the threshold: not
    listed, not counted, and its door refuses a stale link."""

    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


class RefereesSection(SectionViewSet):
    """Listed from the start but locked until the project is described: the
    row reads *Cannot start yet* and the door refuses it."""

    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("project")


class Gated(TaskList):
    project = Section(ProjectSection, title="Project", reopen_at="review")
    match_funding = Section(
        MatchFundingSection, title="Match funding", key="match-funding"
    )
    referees = Section(RefereesSection, title="Referees")


class GatedViewSet(TaskListViewSet):
    description = "Chapter 14: a task list with a locked row and a hidden one."
    template_name = "testapp/readme_task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-gated"
    task_list = Gated
