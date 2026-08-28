"""Chapter 14 — one application, start to submit. Everything so far, scoped
to one journey, with an ending."""

import uuid

from django.shortcuts import redirect, render

from gandalf.collections import CollectionView, ItemMemberMixin
from gandalf.observers import WizardObserver
from gandalf.hubs import HubView, Member, RunMemberMixin
from gandalf.storage import SessionJourneyStore
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from ..models import Application
from .ch06_review import ReviewStepView
from .ch13_gated import MATCH_FUNDING_THRESHOLD
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


# --- watching it (chapter 15) -------------------------------------------------


#: What the observer below has seen, for the README's test to read back.
rejections = []


class CountRejections(WizardObserver):
    """Which steps do applicants get wrong? Told what happened, never what
    was said."""

    def submission(self, step, accepted, metadata):
        if not accepted:
            rejections.append(step.context["name"])


# --- minting -----------------------------------------------------------------


def record_applying_as(store, bound_wizard):
    """Read the one answer the rest of the journey turns on, once, and write
    it where every other member can read it without a walk."""
    step = bound_wizard.path.find_step(name="applying_as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]


class ApplicationStartViewSet(WizardViewSet):
    """The first wizard. There is no journey yet, so `done()` mints one,
    stashes these answers as its first member, and sends the applicant to
    the hub under the new id."""

    description = "Chapter 14: the setup wizard that mints an application."
    url_name = "readme-apply-start"
    wizard = (
        Wizard()
        .step(ApplyingAsForm, name="applying_as", label="Applying as")
        .configure(
            template_name="testapp/linear_wizard.html",
            observer_class=CountRejections,
        )
    )

    def done(self, bound_wizard):
        journey = uuid.uuid4().hex
        store = SessionJourneyStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applying_as(store, bound_wizard)
        return redirect("readme-apply-hub", journey=journey)


class SetupMemberViewSet(RunMemberMixin, WizardViewSet):
    """The same wizard, once a journey exists: re-openable from the hub like
    any other member, and re-recording its answer when it is re-saved."""

    description = "Chapter 14: the setup answers, re-openable from the hub."
    url_name = "readme-apply-setup"
    member_key = "setup"
    hub_url_name = "readme-apply-hub"
    wizard = ApplicationStartViewSet.wizard

    def member_done(self, bound_wizard):
        record_applying_as(self.get_journey_store(), bound_wizard)
        return super().member_done(bound_wizard)


# --- the members --------------------------------------------------------------


class ContactMemberViewSet(RunMemberMixin, WizardViewSet):
    description = "Chapter 14: a plain member of the application."
    url_name = "readme-apply-contact"
    template_name = "testapp/linear_wizard.html"
    member_key = "contact"
    hub_url_name = "readme-apply-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        .step(ReviewStepView, name="review")
    )


class ProjectMemberViewSet(RunMemberMixin, WizardViewSet):
    description = "Chapter 14: the project, whose amount reveals match funding."
    url_name = "readme-apply-project"
    template_name = "testapp/linear_wizard.html"
    member_key = "project"
    hub_url_name = "readme-apply-hub"
    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def member_done(self, bound_wizard):
        project = bound_wizard.path.find_step(name="project")
        self.get_journey_store().data["amount"] = int(
            project.form.cleaned_data["amount"]
        )
        return super().member_done(bound_wizard)


class BudgetLineViewSet(ItemMemberMixin, WizardViewSet):
    description = "Chapter 14: one budget line, under the application's journey."
    url_name = "readme-apply-budget-line"
    template_name = "testapp/linear_wizard.html"
    collection_key = "budget"
    hub_url_name = "readme-apply-budget"
    item_title_step = "line"
    item_title_field = "item"
    wizard = (
        Wizard()
        .step(BudgetLineForm, name="line", label="Budget line")
        .step(ReviewStepView, name="review")
    )


class BudgetCollectionView(CollectionView):
    description = "Chapter 14: the budget, under the application's journey."
    template_name = "testapp/budget.html"
    remove_template_name = "testapp/budget_remove.html"
    url_name = "readme-apply-budget"
    member_key = "budget"
    item_viewset = BudgetLineViewSet
    item_name = "Budget line"
    item_reopen_step = "review"
    min_items = 1
    hub_url_name = "readme-apply-hub"


class MatchFundingMemberViewSet(RunMemberMixin, WizardViewSet):
    description = "Chapter 14: hidden until the amount crosses the threshold."
    url_name = "readme-apply-match-funding"
    template_name = "testapp/linear_wizard.html"
    member_key = "match_funding"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


# --- a task list within the task list -------------------------------------------


class RefereesMemberViewSet(RunMemberMixin, WizardViewSet):
    """Listed by the supporting-information hub, not the application's: its
    key carries that hub's prefix, and it returns there when it finishes.
    The record it reads is still the journey's — `contact` is a root key."""

    description = "Chapter 14: locked until contact details are finished."
    url_name = "readme-apply-referees"
    template_name = "testapp/linear_wizard.html"
    member_key = "supporting:referees"
    hub_url_name = "readme-apply-supporting"
    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, member, store):
        return not store.has_stash("contact")


class DocumentsMemberViewSet(RunMemberMixin, WizardViewSet):
    description = "Chapter 14: the governing document, only for organisations."
    url_name = "readme-apply-documents"
    template_name = "testapp/file_upload_wizard.html"
    member_key = "supporting:documents"
    hub_url_name = "readme-apply-supporting"
    wizard = Wizard().step(GoverningDocumentForm, name="document", label="Document")

    @classmethod
    def hidden(cls, request, member, store):
        # Written by the setup member at the root; one record, so a member
        # two hubs down reads it without being handed anything.
        return store.data.get("applying_as") != "organisation"


class SupportingHubView(HubView):
    """A hub that is a member of the application's hub. `member_key` is the
    prefix its own members are keyed under; `hub_url_name` is where its
    Continue returns to. Its row on the parent reads its own rows' status,
    and its submit tombstones nothing — only the application's does."""

    description = "Chapter 14: a task list within the application's task list."
    template_name = "testapp/nested_hub.html"
    url_name = "readme-apply-supporting"
    member_url_name = "readme-apply-supporting-member"
    member_key = "supporting"
    hub_url_name = "readme-apply-hub"
    members = [
        Member("referees", RefereesMemberViewSet, title="Referees"),
        Member("documents", DocumentsMemberViewSet, title="Governing document"),
    ]


# --- the hub -------------------------------------------------------------------


class GrantApplicationHubView(HubView):
    """Mounted under `apply/<journey>/`, so every request — the page, the
    doors, and each member's own wizard under the same segment — reads the
    same journey, and two applications are two URLs."""

    description = "Chapter 14: the application's task list, with a submit."
    template_name = "testapp/journey_hub.html"
    url_name = "readme-apply-hub"
    member_url_name = "readme-apply-hub-member"
    members = [
        Member("setup", SetupMemberViewSet, title="Applying as"),
        Member(
            "contact",
            ContactMemberViewSet,
            title="Contact details",
            reopen_step="review",
        ),
        Member("project", ProjectMemberViewSet, title="Project", reopen_step="review"),
        Member("budget", BudgetCollectionView, title="Budget"),
        Member("match_funding", MatchFundingMemberViewSet, title="Match funding"),
        Member("supporting", SupportingHubView, title="Supporting information"),
    ]

    def journey_done(self, hub, store):
        # The stashes are still readable here; the tombstone keeps only
        # `store.data`, so whatever the done page needs goes there.
        contact = store.get_stash("contact")
        application = Application.objects.create()
        application.submit(contact["state"][1]["step"]["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_page_url())

    def journey_completed(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )
