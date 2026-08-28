"""Chapter 13 — locked and hidden. One member waits on another; one is not
there until an answer says it should be."""

from gandalf.hubs import HubView, Member, RunMemberMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .ch06_review import ReviewStepView
from .forms import MatchFundingForm, ProjectForm, RefereeForm

#: Applications above this ask where the rest of the money is coming from.
MATCH_FUNDING_THRESHOLD = 10_000


class GatedProjectMemberViewSet(RunMemberMixin, WizardViewSet):
    """Decides whether the match funding member exists. The amount is read
    off the path here — the one moment the run is readable and a walk has
    already been paid — and written to the journey's data."""

    description = "Chapter 13: the member whose answer reveals another."
    url_name = "readme-gated-project"
    template_name = "testapp/linear_wizard.html"
    member_key = "project"
    hub_url_name = "readme-gated"
    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def run_done(self, bound_wizard):
        project = bound_wizard.path.find_step(name="project")
        self.get_journey_store().data["amount"] = int(
            project.form.cleaned_data["amount"]
        )
        return super().run_done(bound_wizard)


class RefereesMemberViewSet(RunMemberMixin, WizardViewSet):
    """Listed from the start but locked until the project is described: the
    row reads *Cannot start yet* and the door refuses it."""

    description = "Chapter 13: a member that unlocks when another is finished."
    url_name = "readme-gated-referees"
    template_name = "testapp/linear_wizard.html"
    member_key = "referees"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, member, store):
        return not store.has_stash("project")


class MatchFundingMemberViewSet(RunMemberMixin, WizardViewSet):
    """Hidden until the amount asked for crosses the threshold: not listed,
    not counted, and its door refuses a stale link."""

    description = "Chapter 13: a member that only exists above a threshold."
    url_name = "readme-gated-match-funding"
    template_name = "testapp/linear_wizard.html"
    member_key = "match_funding"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


class GatedHubView(HubView):
    description = "Chapter 13: a task list with a locked row and a hidden one."
    template_name = "testapp/readme_hub.html"
    url_name = "readme-gated"
    member_url_name = "readme-gated-member"
    members = [
        Member(
            "project", GatedProjectMemberViewSet, title="Project", reopen_step="review"
        ),
        Member("match_funding", MatchFundingMemberViewSet, title="Match funding"),
        Member("referees", RefereesMemberViewSet, title="Referees"),
    ]
