"""Chapter 13 — locked and hidden. One section waits on another; one is not
there until an answer says it should be."""

from gandalf.sections import HubView, Section, SectionMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .ch06_review import ReviewStepView
from .forms import MatchFundingForm, ProjectForm, RefereeForm

#: Applications above this ask where the rest of the money is coming from.
MATCH_FUNDING_THRESHOLD = 10_000


class GatedProjectSectionViewSet(SectionMixin, WizardViewSet):
    """Decides whether the match funding section exists. The amount is read
    off the path here — the one moment the run is readable and a walk has
    already been paid — and written to the journey's data."""

    description = "Chapter 13: the section whose answer reveals another."
    url_name = "readme-gated-project"
    template_name = "testapp/linear_wizard.html"
    section_key = "project"
    hub_url_name = "readme-gated"
    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def section_done(self, bound_wizard):
        project = bound_wizard.path.find_step(name="project")
        self.get_section_store().data["amount"] = int(
            project.form.cleaned_data["amount"]
        )
        return super().section_done(bound_wizard)


class RefereesSectionViewSet(SectionMixin, WizardViewSet):
    """Listed from the start but locked until the project is described: the
    row reads *Cannot start yet* and the door refuses it."""

    description = "Chapter 13: a section that unlocks when another is finished."
    url_name = "readme-gated-referees"
    template_name = "testapp/linear_wizard.html"
    section_key = "referees"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, section, store):
        return not store.has_stash("project")


class MatchFundingSectionViewSet(SectionMixin, WizardViewSet):
    """Hidden until the amount asked for crosses the threshold: not listed,
    not counted, and its door refuses a stale link."""

    description = "Chapter 13: a section that only exists above a threshold."
    url_name = "readme-gated-match-funding"
    template_name = "testapp/linear_wizard.html"
    section_key = "match_funding"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, request, section, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


class GatedHubView(HubView):
    description = "Chapter 13: a task list with a locked row and a hidden one."
    template_name = "testapp/readme_hub.html"
    url_name = "readme-gated"
    section_url_name = "readme-gated-section"
    sections = [
        Section(
            "project", GatedProjectSectionViewSet, title="Project", reopen_step="review"
        ),
        Section("match_funding", MatchFundingSectionViewSet, title="Match funding"),
        Section("referees", RefereesSectionViewSet, title="Referees"),
    ]
