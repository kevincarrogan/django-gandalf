"""Chapter 14 — one application, start to submit. Everything so far, scoped
to one journey, with an ending."""

from django.shortcuts import redirect, render

from gandalf.collections import Collection
from gandalf.hubs import Hub, HubViewSet
from gandalf.observers import WizardObserver
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from ..models import Application
from .ch06_review import ReviewStepView
from .ch13_gated import MATCH_FUNDING_THRESHOLD, record_amount
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


# --- what the members decide ---------------------------------------------------


def record_applying_as(store, bound_wizard):
    """Read the one answer the rest of the journey turns on, once, and write
    it where every other member can read it without a walk."""
    step = bound_wizard.path.find_step(name="applying_as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]


def record_email(store, bound_wizard):
    """What submitting needs, written once here rather than read out of the
    stash's positional state at journey_done()."""
    step = bound_wizard.path.find_step(name="email")
    store.data["email"] = step.form.cleaned_data["email"]


# --- the wizards ---------------------------------------------------------------


setup = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as", label="Applying as")
    .configure(
        template_name="testapp/linear_wizard.html",
        observer_class=CountRejections,
    )
)

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

budget = Collection(
    Wizard()
    .step(BudgetLineForm, name="line", label="Budget line")
    .step(ReviewStepView, name="review"),
    item_name="Budget line",
    item_title=("line", "item"),
    min_items=1,
    reopen="review",
    template_name="testapp/budget.html",
    remove_template_name="testapp/budget_remove.html",
)

match_funding = Wizard().step(MatchFundingForm, name="source", label="Match funding")

referees = Wizard().step(RefereeForm, name="referee", label="Referee")

documents = (
    Wizard()
    .step(GoverningDocumentForm, name="document", label="Document")
    .configure(template_name="testapp/file_upload_wizard.html")
)


# --- a task list within the task list -------------------------------------------


supporting = (
    Hub()
    # Locked until contact details are finished. `contact` is a root key:
    # the record is the journey's, whichever hub reads it.
    .member(
        "referees",
        referees,
        title="Referees",
        blocked=lambda store: not store.has_stash("contact"),
    )
    # Written by the setup member at the root; one record, so a member two
    # hubs down reads it without being handed anything.
    .member(
        "documents",
        documents,
        title="Governing document",
        hidden=lambda store: store.data.get("applying_as") != "organisation",
    )
    .configure(template_name="testapp/nested_hub.html")
)


# --- the journey ---------------------------------------------------------------


application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .member("project", project, title="Project", reopen="review", done=record_amount)
    .collection("budget", budget, title="Budget")
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        hidden=lambda store: store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD,
    )
    .hub("supporting", supporting, title="Supporting information")
)


class GrantApplicationViewSet(HubViewSet):
    """Mounted under `apply/<journey>/`, so every request — the page, the
    doors, and each member's own wizard beneath it — reads the same journey,
    and two applications are two URLs."""

    description = "Chapter 14: the application's task list, with a submit."
    template_name = "testapp/journey_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-apply"
    hub = application

    def journey_done(self, hub, store):
        # The stashes are still readable here, but `data` is what the
        # members wrote for reading back; the tombstone keeps only `data`,
        # so whatever the done page needs goes there too.
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_page_url())

    def submitted(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )


# --- minting -----------------------------------------------------------------


class ApplicationStartViewSet(WizardViewSet):
    """The first wizard. There is no journey yet, so `done()` begins one,
    records these answers as its `setup` member — stashed, `run_done()`
    run — and sends the applicant to the hub under the new id."""

    description = "Chapter 14: the setup wizard that mints an application."
    url_name = "readme-apply-start"
    wizard = setup

    def done(self, bound_wizard):
        journey = GrantApplicationViewSet.begin(self.request)
        journey.finish("setup", bound_wizard)
        return redirect(journey.url)
