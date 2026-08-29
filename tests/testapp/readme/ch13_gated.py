"""Chapter 13 — locked and hidden. One member waits on another; one is not
there until an answer says it should be."""

from gandalf.hubs import Hub, HubViewSet
from gandalf.wizard import Wizard

from .ch06_review import ReviewStepView
from .forms import MatchFundingForm, ProjectForm, RefereeForm


MATCH_FUNDING_THRESHOLD = 10_000


def record_amount(store, bound_wizard):
    """The amount is read off the path here — the one moment the run is
    readable and a walk has already been paid — and written to the journey's
    data, where every other member reads it without a walk."""
    project = bound_wizard.path.find_step(name="project")
    store.data["amount"] = int(project.form.cleaned_data["amount"])


project = (
    Wizard()
    .step(ProjectForm, name="project", label="Project")
    .step(ReviewStepView, name="review")
)

match_funding = Wizard().step(MatchFundingForm, name="source", label="Match funding")

referees = Wizard().step(RefereeForm, name="referee", label="Referee")


class GatedHubViewSet(HubViewSet):
    description = "Chapter 13: a task list with a locked row and a hidden one."
    template_name = "testapp/readme_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-gated"
    hub = (
        Hub()
        .member(
            "project", project, title="Project", reopen="review", done=record_amount
        )
        # Not there until the amount asked for crosses the threshold: not
        # listed, not counted, and its door refuses a stale link.
        .member(
            "match_funding",
            match_funding,
            title="Match funding",
            hidden=lambda store: store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD,
        )
        # Listed from the start but locked until the project is described:
        # the row reads *Cannot start yet* and the door refuses it.
        .member(
            "referees",
            referees,
            title="Referees",
            blocked=lambda store: not store.has_stash("project"),
        )
    )
