"""Chapter 15 — one application, start to submit. Everything so far, scoped
to one journey, with an ending."""

from django.shortcuts import redirect, render

from gandalf.observers import WizardObserver
from gandalf.tasklists import (
    AddAnother,
    Group,
    Section,
    SectionViewSet,
    TaskList,
    TaskListViewSet,
)
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from ..models import Application
from .ch07_review import ReviewStepView
from .ch14_gated import MATCH_FUNDING_THRESHOLD, record_amount
from .forms import (
    ApplicantForm,
    ApplyingAsForm,
    BudgetLineForm,
    EmailForm,
    GoverningDocumentForm,
    MatchFundingForm,
    ProjectForm,
    RefereeForm,
)


# --- watching it (chapter 16) -------------------------------------------------


#: What the observer below has seen, for the README's test to read back.
rejections = []


class CountRejections(WizardObserver):
    """Which steps do applicants get wrong? Told what happened, never what
    was said."""

    def submission(self, step, accepted, metadata):
        if not accepted:
            rejections.append(step.context["name"])


# --- what the sections decide ---------------------------------------------------


def record_applying_as(store, run):
    """Read the one answer the rest of the journey turns on, once, and write
    it where every other section can read it without a walk."""
    step = run.path.find_step(name="applying-as")
    store.metadata["applying_as"] = step.answer["applying_as"]


def record_email(store, run):
    """What submitting needs, written once here rather than read out of the
    stash's positional state at journey_done()."""
    step = run.path.find_step(name="email")
    store.metadata["email"] = step.answer["email"]


# --- the wizards ---------------------------------------------------------------


setup = Wizard().step(ApplyingAsForm, name="applying-as", label="Applying as")

contact = (
    Wizard()
    .step(ApplicantForm, name="name", label="Your name")
    .step(EmailForm, name="email", label="Email")
    .step(ReviewStepView, name="review")
)

project = (
    Wizard()
    .step(ProjectForm, name="project", label="Project")
    .step(ReviewStepView, name="review")
)

budget = AddAnother(
    Wizard()
    .step(BudgetLineForm, name="line", label="Budget line")
    .step(ReviewStepView, name="review"),
    title="Budget",
    item_title="item",
    min_items=1,
    reopen_at="review",
)

match_funding = Wizard().step(MatchFundingForm, name="source", label="Match funding")

referees = Wizard().step(RefereeForm, name="referee", label="Referee")

documents = Wizard().step(GoverningDocumentForm, name="document", label="Document")


# --- sections with something to do ---------------------------------------------


class SetupSection(SectionViewSet):
    """The setup wizard as a section of the journey: watched, and recording
    its one answer where the rest of the application reads it."""

    wizard = setup
    observer_class = CountRejections

    def done(self, run):
        record_applying_as(self.get_journey_store(), run)
        return super().done(run)


class ContactSection(SectionViewSet):
    wizard = contact

    def done(self, run):
        record_email(self.get_journey_store(), run)
        return super().done(run)


class ProjectSection(SectionViewSet):
    wizard = project

    def done(self, run):
        record_amount(self.get_journey_store(), run)
        return super().done(run)


class MatchFundingSection(SectionViewSet):
    """Not there until the amount asked for crosses the threshold."""

    wizard = match_funding

    @classmethod
    def hidden(cls, store):
        return store.metadata.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


class RefereesSection(SectionViewSet):
    """Locked until contact details are finished."""

    wizard = referees

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("contact")


class DocumentsSection(SectionViewSet):
    """Only for organisations — an answer the setup section wrote at the root.
    A file step, so its own template rather than the page's."""

    wizard = documents
    template_name = "testapp/file_upload_wizard.html"

    @classmethod
    def hidden(cls, store):
        return store.metadata.get("applying_as") != "organisation"


# --- the task list ---------------------------------------------------------------


class SupportingInformation(TaskList):
    referees = Section(RefereesSection, title="Referees")
    documents = Section(DocumentsSection, title="Governing document")


class SupportingInformationPage(TaskListViewSet):
    """The group's page: what a view carries, for the list it lists."""

    task_list = SupportingInformation
    template_name = "testapp/nested_task_list.html"


class GrantApplication(TaskList):
    """What the application is: its sections, in the order the page lists
    them. A value — `GrantApplication.begin(request)` starts one."""

    setup = Section(SetupSection, title="Applying as")
    contact = Section(ContactSection, title="Contact details", reopen_at="review")
    project = Section(ProjectSection, title="Project", reopen_at="review")
    budget = budget
    match_funding = Section(
        MatchFundingSection, title="Match funding", key="match-funding"
    )
    supporting = Group(SupportingInformationPage, title="Supporting information")


class GrantApplicationViewSet(TaskListViewSet):
    """The page. Mounted under `apply/<journey>/`, so every request —
    the page, the doors, each section beneath it — reads the same journey,
    and two applications are two URLs."""

    description = "Chapter 15: the application's task list, with a submit."
    url_name = "readme-apply"
    template_name = "testapp/journey_task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    add_another_template_name = "testapp/budget.html"
    remove_template_name = "testapp/budget_remove.html"
    task_list = GrantApplication

    def journey_done(self, page, store):
        application = Application.objects.create()
        application.submit(store.metadata["email"])
        store.metadata["reference"] = application.reference
        return redirect(self.get_page_url())

    def submitted(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.metadata["reference"]},
        )


# --- minting ---------------------------------------------------------------------


class ApplicationStartViewSet(WizardViewSet):
    """The first wizard, before there is a journey to be a section of:
    begin one, record this run as its `setup` section, go there."""

    description = (
        "Chapter 15 as a task list: the setup wizard that begins an application."
    )
    url_name = "readme-apply-start"
    template_name = "testapp/linear_wizard.html"
    observer_class = CountRejections
    wizard = setup

    def done(self, run):
        journey = GrantApplication.begin(self.request)
        journey.finish("setup", run)
        return redirect(journey.url)
