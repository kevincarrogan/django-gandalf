"""Chapter 14 as a task list: the same application, declared as a class
body. Sections carry facts; the thing in the slot carries behaviour."""

from django.shortcuts import redirect, render

from gandalf.hubs import MemberViewSet
from gandalf.tasklists import AddAnother, Group, Section, TaskList, TaskListViewSet
from gandalf.viewsets import WizardViewSet

from ..models import Application
from .ch13_gated import MATCH_FUNDING_THRESHOLD, record_amount
from .ch14_journey import (
    budget,
    contact,
    documents,
    match_funding,
    project,
    record_applying_as,
    record_email,
    referees,
    setup,
)


# --- sections with something to do ---------------------------------------------


class SetupMember(MemberViewSet):
    wizard = setup

    def run_done(self, bound_wizard):
        record_applying_as(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class ContactMember(MemberViewSet):
    wizard = contact

    def run_done(self, bound_wizard):
        record_email(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class ProjectMember(MemberViewSet):
    wizard = project

    def run_done(self, bound_wizard):
        record_amount(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class MatchFundingMember(MemberViewSet):
    """Not there until the amount asked for crosses the threshold."""

    wizard = match_funding

    @classmethod
    def hidden(cls, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


class RefereesMember(MemberViewSet):
    """Locked until contact details are finished."""

    wizard = referees

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("contact")


class DocumentsMember(MemberViewSet):
    """Only for organisations — an answer the setup section wrote at the root."""

    wizard = documents

    @classmethod
    def hidden(cls, store):
        return store.data.get("applying_as") != "organisation"


# --- the task list ---------------------------------------------------------------


class SupportingInformation(TaskList):
    template_name = "testapp/nested_hub.html"

    referees = Section(RefereesMember, title="Referees")
    documents = Section(DocumentsMember, title="Governing document")


class GrantApplication(TaskList):
    """What the application is: its sections, in the order the page lists
    them. A value — `GrantApplication.begin(request)` starts one."""

    setup = Section(SetupMember, title="Applying as")
    contact = Section(ContactMember, title="Contact details", reopen="review")
    project = Section(ProjectMember, title="Project", reopen="review")
    budget = AddAnother(budget, title="Budget")
    match_funding = Section(MatchFundingMember, title="Match funding")
    supporting = Group(SupportingInformation, title="Supporting information")


class GrantApplicationViewSet(TaskListViewSet):
    """The page. Mounted under `tasklist/<journey>/`, so every request —
    the page, the doors, each section beneath it — reads the same journey,
    and two applications are two URLs."""

    description = "Chapter 14 as a task list: the application declared as a class body."
    url_name = "readme-tasklist"
    template_name = "testapp/journey_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    tasklist = GrantApplication

    def journey_done(self, hub, store):
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_page_url())

    def journey_completed(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )


# --- minting ---------------------------------------------------------------------


class TaskListStartViewSet(WizardViewSet):
    """The first wizard, before there is a journey to be a section of:
    begin one, record this run as its `setup` section, go there."""

    description = (
        "Chapter 14 as a task list: the setup wizard that mints an application."
    )
    url_name = "readme-tasklist-start"
    wizard = setup

    def done(self, bound_wizard):
        journey = GrantApplication.begin(self.request)
        journey.finish("setup", bound_wizard)
        return redirect(journey.url)
