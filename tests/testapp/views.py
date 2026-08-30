from gandalf import tree as tree_module
from gandalf import wizard
from gandalf.context import WizardContext
from gandalf.form_views import form_view_factory
from gandalf.wizard import (
    MergeCleanedData,
    on_field,
    StepNameRouter,
    Wizard,
    condition,
)
from gandalf.viewsets import WizardViewSet

from http import HTTPStatus


from django.contrib.auth import get_user_model, login, logout
from django import forms
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView
from django.views.generic.edit import FormView

from gandalf.escapes import Obliterate
from gandalf.form_views import StepFormView
from gandalf.runtime import STASH_VERSION, InvalidStash
from gandalf.add_another import AddAnotherViewSet
from gandalf.tasklists import (
    AddAnother,
    Section,
    SectionViewSet,
    TaskList,
    TaskListViewSet,
)
from gandalf.storage import (
    SessionJourneyStore,
    SessionStashStore,
    SessionStorage,
    StashNotFound,
)
from gandalf.summary import Group, Hide, SummaryMixin

from . import catalogue
from .counting import CountingCursorWalker, CountingStepDispatcher
from .durable import ModelCollectionStore, ModelJourneyStore, ModelStorage
from .forms import (
    AccountKindForm,
    AddressForm,
    ConfirmForm,
    GuestForm,
    AccountTypeForm,
    BareEscapeForm,
    BusinessDetailsForm,
    CancelSignupForm,
    DeliveryChoiceForm,
    EmailLookupForm,
    EscapingPhotoForm,
    FirstStepForm,
    ItemCountForm,
    ItemForm,
    NewsletterForm,
    OptionalPhotoForm,
    PersonalDetailsForm,
    ProfilePhotoForm,
    ReviewForm,
    SecondStepForm,
    SniffedPhotoForm,
    SummaryDisplayForm,
    SummaryFieldsForm,
    ToppingsForm,
)


class IndexView(TemplateView):
    """The demo site's front door.

    The examples are grouped and explained by `catalogue.py` rather than
    listed alphabetically, because the wizards worth comparing are the ones
    that differ in a single respect — and alphabetical order scatters them.
    """

    template_name = "testapp/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["groups"] = catalogue.resolve()
        return context


def is_business_account(context):
    account_step = context.run.path.find_step(name="account_type")
    return account_step.form.cleaned_data["account_type"] == "business"


class SingleStepWizardViewSet(WizardViewSet):
    description = "A single-step wizard with a custom done() returning the run id."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "single-step-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class TwoTombstoneStorage(SessionStorage):
    """Keeps only two completion tombstones, so pruning is observable
    without completing dozens of runs."""

    max_completed_runs = 2


class PrunedCompletionWizardViewSet(WizardViewSet):
    description = (
        "Single-step wizard whose storage keeps only two completion "
        "tombstones, exercising the prune of the oldest finished runs."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")
    storage_class = TwoTombstoneStorage

    url_name = "pruned-completion-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class RunUnavailableWizardViewSet(WizardViewSet):
    description = (
        "Single-step wizard overriding run_unavailable() so finished and "
        "unknown runs answer differently instead of redirecting to the start."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "run-unavailable-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")

    def run_unavailable(self, run, reason):
        return HttpResponse(f"unavailable: {reason}", status=HTTPStatus.GONE)


#: Every record `RunMetadataWizardViewSet` has opened, in order. A list
#: rather than a counter so a test can see a *second* one appear when one
#: should not have.
OPENED_RECORDS: list[str] = []


class RecordReadingStepView(StepFormView):
    """A step that reads the run's metadata every time it is dispatched.

    Which is every request, not every answer — the walk re-proves this step
    on each later page. Recording what it saw is how a test proves the bag
    is still there on a walk that persists nothing.
    """

    form_class = SecondStepForm
    template_name = "testapp/run_metadata_wizard.html"

    def get_initial(self):
        metadata = self.request.run.metadata
        SEEN_RECORDS.append(metadata.get("record_id"))
        # A note in this step's own bag, so the run-level record id and a
        # step's own cannot tread on each other. Written on every dispatch,
        # which is every walk — including the one `keep_readable()` takes
        # after `done()` has returned. A step that writes metadata must
        # therefore be idempotent about it, exactly as its `clean()` is.
        metadata.for_step("second")["drafted"] = True
        return super().get_initial()


#: What `RecordReadingStepView` saw, per dispatch.
SEEN_RECORDS: list[object] = []


class RunMetadataWizardViewSet(WizardViewSet):
    description = (
        "Two-step wizard that opens a record when the run starts, remembers "
        "it in the run's metadata, and reads it back at every later step."
    )
    template_name = "testapp/run_metadata_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(RecordReadingStepView, name="second")
        .configure(template_name="testapp/run_metadata_wizard.html")
    )

    url_name = "run-metadata-wizard"

    def run_started(self, run):
        record_id = f"record-{len(OPENED_RECORDS) + 1}"
        OPENED_RECORDS.append(record_id)
        # Two facts about the same moment, so one write rather than two.
        run.metadata.update(record_id=record_id, pending=True)

    def done(self, run):
        metadata = run.metadata
        # Set once when the run opened its record, and cleared once here.
        # Nothing replays either, which is what makes a plain delete safe —
        # unlike the step's note above.
        del metadata["pending"]
        return HttpResponse(
            f"completed {metadata['record_id']} recording {len(metadata)}"
        )


class SingleStepWizardWithoutDoneViewSet(WizardViewSet):
    description = "Single-step wizard with no done() override (falls back to default)."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "single-step-wizard-without-done"


class SingleStepWizardDoneDataViewSet(WizardViewSet):
    description = (
        "Single-step wizard; done() reads the submitted form data via the runtime tree."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "single-step-wizard-done-data"

    def done(self, run):
        cleaned_data = run.runtime_tree.form.cleaned_data
        return HttpResponse(f"completed {cleaned_data['name']}")


class SingleStepWizardDoneRunDataViewSet(WizardViewSet):
    description = (
        "Single-step wizard; done() reads raw stored state via get_run_data()."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "single-step-wizard-done-run-data"

    def done(self, run):
        run_data = run.get_run_data()
        submission = run_data["state"][0]["step"]
        return HttpResponse(f"completed {submission.get('name')}")


class LinearWizardViewSet(WizardViewSet):
    description = (
        "Two-step linear wizard built from the module-level `wizard` instance."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.step(FirstStepForm, name="first").step(
        SecondStepForm, name="second"
    )

    url_name = "linear-wizard"


class DoneLinearWizardViewSet(WizardViewSet):
    description = "Two-step linear wizard with a done() that combines both submissions."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
            name="first",
        )
        .step(
            SecondStepForm,
            name="second",
        )
    )

    url_name = "done-linear-wizard"

    def done(self, run):
        first = run.runtime_tree
        second = first.next
        return HttpResponse(
            f"completed {first.form.cleaned_data['name']} "
            f"at {second.form.cleaned_data['email']}"
        )


class MultiValueWizardViewSet(WizardViewSet):
    description = (
        "Two-step wizard whose first step posts a multi-valued field, so the "
        "submission carries more than one value under one name."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            ToppingsForm,
            name="toppings",
        )
        .step(
            SecondStepForm,
            name="second",
        )
    )

    url_name = "multi-value-wizard"

    def done(self, run):
        toppings = run.path.find_step(name="toppings")
        second = run.path.find_step(name="second")
        return HttpResponse(
            f"completed {','.join(toppings.form.cleaned_data['toppings'])} "
            f"for {second.form.cleaned_data['email']}"
        )


class OtherLinearWizardViewSet(WizardViewSet):
    description = (
        "Same two-step shape as the linear wizard, rendered with a different template."
    )
    template_name = "testapp/other_linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
            name="first",
        )
        .step(
            SecondStepForm,
            name="second",
        )
    )

    url_name = "other-linear-wizard"


class RecreatedLinearWizardViewSet(WizardViewSet):
    description = (
        "Two-step linear wizard rendered with the recreated_linear_wizard template."
    )
    template_name = "testapp/recreated_linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
            name="first",
        )
        .step(
            SecondStepForm,
            name="second",
        )
    )

    url_name = "recreated-linear-wizard"


class BranchingWizardViewSet(WizardViewSet):
    description = (
        "Branches on the first step's account type: business -> business details, "
        "otherwise personal details, then a shared review step."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "branching-wizard"


class MemberRouter(StepNameRouter):
    """Custom router keying step URLs on a `member` context entry rather
    than `name`."""

    context_key = "member"


class MemberEditingWizardViewSet(WizardViewSet):
    description = (
        "Wizard configuring a custom `step_router_class` that routes step "
        "URLs by a `member` context entry rather than `name`."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, member="account")
        .step(PersonalDetailsForm, member="details")
        .step(ReviewForm, member="review")
        .configure(
            template_name="testapp/editing_wizard.html",
            step_router_class=MemberRouter,
        )
    )

    url_name = "member-editing-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EditingBranchingWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard whose review template renders edit links for each prior "
        "step (account type and the active arm's detail step)."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "editing-branching-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class DoneBranchingWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard exercising name context, find_step / filter_steps, "
        "and ContextFinder over the declared tree."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(
                PersonalDetailsForm,
                name="personal",
            ),
        )
        .step(ReviewForm, name="review")
        .step(SecondStepForm, name="second")
    )

    url_name = "done-branching-wizard"

    def done(self, run):
        from gandalf import tree as tree_module

        all_steps = run.path.filter_steps()
        review_step = run.path.find_step(name="review")
        missing_step = run.path.find_step(name="nonexistent")
        account_steps = run.path.filter_steps(name="account_type")

        declared_finder = tree_module.ContextFinder({})
        declared_finder.visit(run.wizard.tree)

        return HttpResponse(
            f"completed {len(all_steps)} via "
            f"{review_step.declaration.declaration.__name__} "
            f"missing={missing_step} account_count={len(account_steps)} "
            f"declared_count={len(declared_finder.all())}"
        )


def _always_false(request):
    return False


def _always_the_second_case(request):
    """Names a case without reading any answer, so it can decide the very
    first node."""
    return "second"


class MisdeclaredSwitchWizardViewSet(WizardViewSet):
    description = (
        "ImproperlyConfigured: a switch whose on_field() names a step the "
        "wizard does not declare, refused when the wizard is configured."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountKindForm, name="account_kind")
        .switch(
            on_field("nowhere", "kind"),
            {"business": Wizard().step(BusinessDetailsForm, name="business_name")},
        )
    )

    url_name = "misdeclared-switch-wizard"


class OffRouteSwitchWizardViewSet(WizardViewSet):
    description = (
        "A switch whose on_field() names a declared step that this run did "
        "not walk: the declaration is sound, so it is the walk that says "
        "which step the selector wanted."
    )
    template_name = "testapp/linear_wizard.html"
    url_name = "off-route-switch-wizard"
    wizard = (
        Wizard()
        .step(AccountKindForm, name="account_kind")
        .branch(
            condition(
                lambda context: False,
                Wizard().step(BusinessDetailsForm, name="never_walked"),
            ),
            default=Wizard(),
        )
        .switch(
            on_field("never_walked", "business_name"),
            {"acme": Wizard().step(PersonalDetailsForm, name="personal")},
        )
    )


class SwitchEntryWizardViewSet(WizardViewSet):
    description = (
        "Wizard whose very first node is a switch (no preceding step): the "
        "selector names a case rather than each arm answering yes or no."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.switch(
        _always_the_second_case,
        {
            "first": wizard.step(FirstStepForm, name="first"),
            "second": wizard.step(SecondStepForm, name="second"),
        },
        default=wizard.step(ReviewForm, name="neither"),
    )

    url_name = "switch-entry-wizard"


class SwitchWizardViewSet(WizardViewSet):
    description = (
        "Routes on the account type as a value rather than through a series "
        "of predicates: one case per outcome, each case's answers stored "
        "under its own name, and on_field() declaring which answer decides."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountKindForm, name="account_kind")
        .switch(
            on_field("account_kind", "kind"),
            {
                "business": Wizard().step(BusinessDetailsForm, name="business_name"),
                "personal": Wizard().step(PersonalDetailsForm, name="preferred_name"),
            },
            default=Wizard().step(ReviewForm, name="anything_else"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "switch-wizard"

    def done(self, run):
        payload = MergeCleanedData().reduce(run.path)
        name = payload.get("business_name") or payload.get("preferred_name")
        return HttpResponse(f"Switched to {name}")


class BranchEntryWizardViewSet(WizardViewSet):
    description = "Wizard whose very first node is a branch (no preceding step)."
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.branch(
        condition(_always_false, wizard.step(FirstStepForm, name="first")),
        default=wizard.step(SecondStepForm, name="second"),
    )

    url_name = "branch-entry-wizard"


class DuplicateContextWizardViewSet(WizardViewSet):
    description = (
        "Two steps sharing the same name, which is a declaration error: "
        "resolving the wizard rejects it, so the run never starts and the "
        "done() below is unreachable."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="duplicate")
        .step(SecondStepForm, name="duplicate")
    )

    url_name = "duplicate-context-wizard"

    def done(self, run):
        try:
            run.path.find_step(name="duplicate")
        except Exception as exc:
            return HttpResponse(f"raised {type(exc).__name__}")
        return HttpResponse("no raise")


class InvalidWizardViewSet(WizardViewSet):
    description = "Wizard attribute is not a Wizard instance; visiting should error."
    url_name = "invalid-wizard"
    wizard = object()


class WizardConfiguredStorageViewSet(WizardViewSet):
    description = (
        "Configures storage_class on the wizard instead of the viewset; "
        "visiting should error rather than silently ignore it."
    )
    url_name = "wizard-configured-storage"
    template_name = "testapp/single_step_wizard.html"

    def get_wizard(self, run):
        # Built per request: configuring it at class level would raise on
        # import and take the whole test app with it.
        return (
            Wizard()
            .step(FirstStepForm, name="first")
            .configure(storage_class=TwoTombstoneStorage)
        )


FirstStepFormView = form_view_factory(
    FirstStepForm,
    template_name="testapp/single_step_wizard.html",
)


class FormViewStepWizardViewSet(WizardViewSet):
    description = (
        "Step backed by a form_view_factory FormView rather than a bare Form class."
    )
    wizard = Wizard().step(FirstStepFormView, name="first")

    url_name = "form-view-step-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class MissingTemplateWizardViewSet(WizardViewSet):
    description = (
        "Wizard with neither template_name nor configured template (expect failure)."
    )
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "missing-template-wizard"


class PreConfiguredWizardViewSet(WizardViewSet):
    description = (
        "Wizard whose template_name comes from Wizard.configure() rather than the view."
    )
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .configure(
            template_name="testapp/single_step_wizard.html",
        )
    )

    url_name = "pre-configured-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EmptyWizardViewSet(WizardViewSet):
    description = "Wizard with no steps; should immediately reach done()."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard()

    url_name = "empty-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EmailStepPrefilledFromPath(FormView):
    """Second-step view that pre-fills its email field from the
    previous step's submitted name, by reading `context.run.path`
    mid-wizard."""

    form_class = SecondStepForm
    template_name = "testapp/linear_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_initial(self):
        initial = super().get_initial()
        path = self.request.run.path
        if path:
            name = path.head.form.cleaned_data["name"]
            initial["email"] = f"{name.lower()}@example.com"
        return initial


class PathAwareLinearWizardViewSet(WizardViewSet):
    description = (
        "Linear wizard whose second step pre-fills its initial value from "
        "context.run.path mid-wizard."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.step(FirstStepForm, name="first").step(
        EmailStepPrefilledFromPath, name="second"
    )

    url_name = "path-aware-linear-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class FirstStepFromFormView(FormView):
    """User-supplied first-step FormView used to verify that path-aware reads
    work when the upstream step is a FormView (Layer 2) rather than a plain
    Form declaration."""

    form_class = FirstStepForm
    template_name = "testapp/linear_wizard.html"

    def get_success_url(self):
        return self.request.path


class PathAwareFormViewFirstStepWizardViewSet(WizardViewSet):
    description = (
        "Linear wizard whose first step is a user-supplied FormView; the "
        "second step still pre-fills its initial value from "
        "context.run.path mid-wizard."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.step(FirstStepFromFormView, name="first").step(
        EmailStepPrefilledFromPath, name="second"
    )

    url_name = "path-aware-form-view-first-step-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class BranchingMergedPayloadWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard with a two-step arm; done() merges cleaned data "
        "across the path via MergeCleanedData."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        wizard.step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                wizard.step(BusinessDetailsForm, name="business_name").step(
                    SecondStepForm, name="second"
                ),
            ),
            default=wizard.step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "branching-merged-payload-wizard"

    def done(self, run):
        payload = MergeCleanedData().reduce(run.path)
        return HttpResponse(
            f"account_type={payload['account_type']} "
            f"business_name={payload['business_name']} "
            f"email={payload['email']} "
            f"confirmed={payload['confirmed']}"
        )


def _never_matches(request):
    return False


def _always_matches(request):
    return True


class EmptyBranchArmMergedPayloadWizardViewSet(WizardViewSet):
    description = (
        "Wizard with a branch whose condition never matches and which has no "
        "default arm; done() shows the branch is dropped from the path."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        wizard.step(FirstStepForm, name="first")
        .branch(
            condition(_never_matches, wizard.step(SecondStepForm, name="second")),
        )
        .step(AccountTypeForm, name="skip_branch_account")
    )

    url_name = "empty-branch-arm-merged-payload-wizard"

    def done(self, run):
        payload = MergeCleanedData().reduce(run.path)
        return HttpResponse(
            f"name={payload['name']} account_type={payload['account_type']}"
        )


class RuntimeTreeBranchingMergeViewSet(WizardViewSet):
    description = (
        "Branching wizard whose done() merges cleaned data across the runtime "
        "tree (not the path), exercising MergeCleanedData.visit_branch."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        wizard.step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                wizard.step(BusinessDetailsForm, name="business_name"),
            ),
            default=wizard.step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "runtime-tree-branching-merge-wizard"

    def done(self, run):
        payload = MergeCleanedData().reduce(run.runtime_tree)
        return HttpResponse(
            f"account_type={payload['account_type']} "
            f"business_name={payload['business_name']} "
            f"confirmed={payload['confirmed']}"
        )


class MergedPayloadLinearWizardViewSet(WizardViewSet):
    description = (
        "Linear two-step wizard whose done() merges cleaned data across the "
        "path via MergeCleanedData and dispatches the merged payload."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second")
    )

    url_name = "merged-payload-wizard"

    def done(self, run):
        payload = MergeCleanedData().reduce(run.path)
        return HttpResponse(
            f"completed name={payload['name']} email={payload['email']}"
        )


class DoubleConfiguredWizardViewSet(WizardViewSet):
    description = "Wizard configured both via get_wizard() and configure_wizard() to test layering."
    template_name = "testapp/single_step_wizard.html"

    def get_wizard(self, run):
        return (
            Wizard()
            .step(FirstStepForm, name="first")
            .configure(
                template_name=self.template_name,
            )
        )

    def configure_wizard(self, wizard):
        return wizard.configure(template_name=self.template_name)

    url_name = "double-configured-wizard"


class DynamicWizardViewSet(WizardViewSet):
    description = (
        "Dynamically-built wizard: pick a count, then the same view generates "
        "that many item-name steps from the stored count on each request."
    )
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, run):
        state = run.get_state()
        wizard = Wizard().step(ItemCountForm, name="count")
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(ItemForm, index=index, name=f"item-{index}")
        return wizard

    url_name = "dynamic-wizard"

    def done(self, run):
        node = run.runtime_tree.next
        names = []
        while node is not None:
            names.append(node.data["name"])
            node = node.next
        return HttpResponse(f"completed {', '.join(names)}")


class MergeWithLists(MergeCleanedData):
    """MergeCleanedData variant that respects a `list_key` context entry.

    Steps declared with `list_key="items"` contribute their cleaned
    data as `{"items": [cleaned]}`; combine concatenates lists under the
    same key instead of overwriting. Steps without `list_key` behave like
    the base reducer (last-write-wins merge).
    """

    def visit_step(self, runtime_step):
        cleaned = runtime_step.form.cleaned_data
        list_key = (runtime_step.declaration.context or {}).get("list_key")
        if list_key is None:
            return cleaned
        return {list_key: [cleaned]}

    def combine(self, accumulator, value):
        merged = {**accumulator}
        for key, incoming in value.items():
            existing = merged.get(key)
            if isinstance(existing, list) and isinstance(incoming, list):
                merged[key] = existing + incoming
            else:
                merged[key] = incoming
        return merged


class FileUploadingWizardViewSet(WizardViewSet):
    description = (
        "Two-step wizard whose first step accepts a file upload; done() echoes "
        "the stored filename and cleans up the run's files."
    )
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard().step(ProfilePhotoForm, name="photo").step(FirstStepForm, name="first")
    )

    url_name = "file-uploading-wizard"

    def done(self, run):
        photo_step = run.path.find_step(name="photo")
        filename = photo_step.files["photo"]["name"]
        return HttpResponse(f"completed {filename}")


class SniffedFileWizardViewSet(WizardViewSet):
    description = (
        "Upload wizard whose first step validates by reading the file, not by "
        "reading its name; done() reads the stored bytes back and echoes them."
    )
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard().step(SniffedPhotoForm, name="photo").step(FirstStepForm, name="first")
    )

    url_name = "sniffed-file-wizard"

    def done(self, run):
        photo_step = run.path.find_step(name="photo")
        with photo_step.form.cleaned_data["photo"] as photo:
            contents = photo.read()
        return HttpResponse(b"completed " + contents)


class FileDoneWizardViewSet(WizardViewSet):
    description = (
        "Upload wizard whose done() returns a TemplateResponse that reads the "
        "finished run back — the summary page renders the file step's form, "
        "which reopens the stored upload at render time rather than in done()."
    )
    template_name = "testapp/file_upload_wizard.html"
    wizard = Wizard().step(ProfilePhotoForm, name="photo")

    url_name = "file-done-wizard"

    def done(self, run):
        return TemplateResponse(
            self.request,
            "testapp/file_done_wizard.html",
            {"wizard": run},
        )


class DynamicListPayloadWizardViewSet(WizardViewSet):
    description = (
        "Dynamic wizard whose generated item steps are condensed into a "
        "list under one key via a context-aware MergeCleanedData subclass."
    )
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, run):
        state = run.get_state()
        wizard = Wizard().step(ItemCountForm, name="count")
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(
                    ItemForm,
                    list_key="items",
                    index=index,
                    name=f"item-{index}",
                )
        return wizard

    url_name = "dynamic-list-payload-wizard"

    def done(self, run):
        import json

        payload = MergeWithLists().reduce(run.path)
        return HttpResponse(json.dumps(payload, sort_keys=True))


class FileEditingWizardViewSet(WizardViewSet):
    description = (
        "Wizard whose first step is an optional-photo upload, supporting an "
        "edit cycle on that step (replace, add, or leave alone)."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard().step(OptionalPhotoForm, name="photo").step(ReviewForm, name="review")
    )

    url_name = "file-editing-wizard"

    def done(self, run):
        photo_step = run.path.find_step(name="photo")
        photo_ref = (photo_step.files or {}).get("photo")
        filename = photo_ref["name"] if photo_ref else "no-photo"
        return HttpResponse(f"completed {filename}")


class EmptyBranchArmContextFinderViewSet(WizardViewSet):
    description = (
        "Wizard with a matched and an unmatched no-default branch; done() runs "
        "ContextFinder over the declared tree (covers the no-default branch "
        "arc) and the runtime tree (covers both the active-selected-arm and "
        "empty-selected-arm branch arcs)."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .branch(
            condition(_always_matches, Wizard().step(SecondStepForm, name="matched")),
        )
        .branch(
            condition(_never_matches, Wizard().step(ReviewForm, name="skipped")),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "empty-branch-arm-context-finder-wizard"

    def done(self, run):
        declared_finder = tree_module.ContextFinder({})
        declared_finder.visit(run.wizard.tree)
        runtime_finder = tree_module.ContextFinder({})
        runtime_finder.visit(run.runtime_tree)
        return HttpResponse(
            f"completed declared={len(declared_finder.all())} "
            f"runtime={len(runtime_finder.all())}"
        )


class RoutedWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard with addressable step URLs: each step is named and "
        "routed via a gandalf_step URL segment; the bare run URL redirects "
        "to the cursor's step URL."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "routed-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class WizardlessWizardViewSet(WizardViewSet):
    description = (
        "Viewset that defines no wizard and does not override "
        "get_wizard(); any request raises ImproperlyConfigured."
    )
    url_name = "wizardless-wizard"


class MisconfiguredStepUrlsWizardViewSet(WizardViewSet):
    description = (
        "Wizard registered with hand-written URL patterns but neither "
        "url_name nor the reverse hooks; any request raises "
        "ImproperlyConfigured."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class LookupProbeStepView(FormView):
    """Step view that probes render_edit for its own (still unanswered)
    step while rendering: `require_data` skips the match, so the probe
    observes StepNotFound mid-run. Also probes the `name=` step lookup."""

    form_class = SecondStepForm
    template_name = "testapp/editing_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        from gandalf.runtime import StepNotFound

        context = super().get_context_data(**kwargs)
        try:
            self.request.run.render_step(name="second")
        except StepNotFound:
            context["lookup_probe"] = "step-not-found"
        found = self.request.run.path.find_step(name="first")
        context["name_lookup_probe"] = found.declaration.context["name"]
        return context


class ProgrammaticLookupWizardViewSet(WizardViewSet):
    description = (
        "Exercises programmatic Run lookups: a mid-run render_edit "
        "of the unanswered cursor step raises StepNotFound (require_data), "
        "done() shows edit() deleting newly stored uploads when its target "
        "cannot be resolved, and the navigation properties fall back to "
        "None outside a step render."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(LookupProbeStepView, name="second")
    )

    url_name = "programmatic-lookup-wizard"

    def done(self, run):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from gandalf import tree as gandalf_tree
        from gandalf.runtime import Run

        upload = SimpleUploadedFile("orphan.txt", b"orphan-bytes")
        ref = run.file_storage.save(run.run_id, upload)
        # A claim the run cannot reach places nothing, so the uploads it came
        # with are the caller's to clean up — which is what the viewset does.
        walk = run.walk(
            claim={"name": "missing"},
            submission={"name": "x"},
            files={"upload": ref},
        )
        if not walk.reached:
            run.delete_file_refs({"upload": ref})
        deleted = not run.file_storage.backend.exists(ref["tmp_name"])

        detached = Run(WizardContext.from_request(self.request), run.storage)
        cursor = run.cursor()
        foreign_declaration = gandalf_tree.Step(FirstStepForm)
        nav_probe = (
            detached.run_url is None
            and detached.back_url is None
            and detached.step_url(foreign_declaration) is None
            and detached.entry_url() is None
            and detached.rendering is None
            and run.back_url is None
            and run.run_url == self.get_wizard_url(run.run_id)
            and run.previous_step(cursor, foreign_declaration) is None
        )
        resolved = run.render_step(name="first")

        # A claim can also be a step declaration, for callers that already
        # hold one rather than resolving a URL segment.
        first = run.path.find_step(name="first")
        by_declaration = run.walk(claim=first.declaration)
        declaration_probe = by_declaration.reached and by_declaration.target.data == {
            "name": "Ada"
        }

        # A context that matches more than one step refuses to guess.
        try:
            run.path.find_step()
        except gandalf_tree.MultipleStepsReturned:
            ambiguous_probe = True
        else:
            ambiguous_probe = False

        return HttpResponse(
            f"completed edit-cleanup={deleted} nav-probe={nav_probe} "
            f"resolve-status={resolved.status_code} "
            f"declaration-claim={declaration_probe} ambiguous={ambiguous_probe}"
        )


def _business_was_acme(context):
    business_step = context.run.path.find_step(name="business_name")
    return business_step.data["business_name"] == "Acme"


class PathProbeStepView(FormView):
    """Step view that reads context.run.path while rendering — the
    mid-run introspection that must stay safe when later branch regions
    are opaque."""

    form_class = PersonalDetailsForm
    template_name = "testapp/editing_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        names = [step.declaration.context["name"] for step in self.request.run.path]
        context["path_names"] = names
        return context


class CrossBranchWizardViewSet(WizardViewSet):
    description = (
        "Second branch's predicate dereferences a step inside the first "
        "branch's business arm; mid-divert renders and edits must stay "
        "safe because unreached branch regions are opaque."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PathProbeStepView, name="preferred_name"),
        )
        .branch(
            condition(
                _business_was_acme,
                Wizard().step(SecondStepForm, name="second"),
            ),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "cross-branch-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class UnroutableWizardViewSet(WizardViewSet):
    description = (
        "Wizard with an unnamed step: resolving it at the HTTP boundary "
        "raises ImproperlyConfigured because every step needs a routable "
        "name."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = Wizard().step(FirstStepForm).step(SecondStepForm, name="second")

    url_name = "unroutable-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class OrgScopedStepView(FormView):
    form_class = FirstStepForm
    template_name = "testapp/editing_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["org"] = self.kwargs["org"]
        return context


class OrgScopedEditingWizardViewSet(WizardViewSet):
    description = (
        "Wizard mounted under an extra URL kwarg; the first step's view "
        "reads self.kwargs['org'] in every render, including edit cycles. "
        "Relies on the default URL hooks forwarding the org kwarg."
    )
    template_name = "testapp/editing_wizard.html"
    url_name = "org-scoped-wizard"
    wizard = (
        Wizard().step(OrgScopedStepView, name="first").step(ReviewForm, name="review")
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


def _always_true(_request):
    return True


class BranchEditRejectionWizardViewSet(WizardViewSet):
    description = (
        "Linear-via-branch wizard used to exercise rejected edits around a "
        "branch (an invalid edit targeting a step after or inside the branch "
        "returns the error render and leaves state untouched), plus the "
        "require_data branch arc when an edit targets a step that hasn't "
        "been visited yet."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .branch(
            condition(
                _always_true,
                Wizard().step(SecondStepForm, name="second"),
            ),
        )
        .step(ReviewForm, name="review")
        .step(AccountTypeForm, name="tail")
    )

    url_name = "branch-edit-rejection-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EscapeLandingView(View):
    description = "Where the escaping wizards send the user."

    def get(self, request):
        return HttpResponse("escaped")


class EscapeParkWizardViewSet(WizardViewSet):
    description = (
        "First step escapes with Park for a known address: the run stays on "
        "that step and the answer is not stored."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(EmailLookupForm, name="email").step(FirstStepForm, name="first")
    )

    url_name = "escape-park-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EscapeAdvanceWizardViewSet(WizardViewSet):
    description = (
        "First step escapes with Advance: the answer is stored and the run "
        "resumes at the second step."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(NewsletterForm, name="newsletter")
        .step(FirstStepForm, name="first")
    )

    url_name = "escape-advance-wizard"

    def done(self, run):
        newsletter = run.path.find_step(name="newsletter")
        return HttpResponse(f"completed {newsletter.form.cleaned_data['email']}")


class EscapeAdvanceFinalStepWizardViewSet(WizardViewSet):
    description = "Single step escaping with Advance, so the escape defers done()."
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(NewsletterForm, name="newsletter")

    url_name = "escape-advance-final-step-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class CancelSignupStepView(FormView):
    """Escapes from `form_valid()` rather than `clean()`, destroying the run."""

    form_class = CancelSignupForm
    template_name = "testapp/linear_wizard.html"

    def get_success_url(self):
        return self.request.path

    def form_valid(self, form):
        if form.cleaned_data["cancel"]:
            raise Obliterate(reverse("escape-landing"))
        return super().form_valid(form)


class EscapeObliterateWizardViewSet(WizardViewSet):
    description = (
        "First step escapes with Obliterate from a user-supplied FormView: "
        "the run and its files are removed."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(CancelSignupStepView, name="cancel")
        .step(FirstStepForm, name="first")
    )

    url_name = "escape-obliterate-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class BareEscapeWizardViewSet(WizardViewSet):
    description = "Raises the base Escape, which the viewset rejects as misuse."
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(BareEscapeForm, name="bare")

    url_name = "bare-escape-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class MidFlowEscapeParkWizardViewSet(WizardViewSet):
    description = (
        "Escapes with Park from the second step, so rolling back must leave "
        "the first step's answer alone."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(FirstStepForm, name="first").step(EmailLookupForm, name="email")
    )

    url_name = "mid-flow-escape-park-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EscapeParkFileWizardViewSet(WizardViewSet):
    description = "Escapes with Park from a step that uploaded a file."
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard().step(EscapingPhotoForm, name="photo").step(FirstStepForm, name="first")
    )

    url_name = "escape-park-file-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class EscapeEditingWizardViewSet(WizardViewSet):
    description = (
        "Escaping step followed by another, used to show that editing a "
        "completed step never escapes."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard().step(EmailLookupForm, name="email").step(FirstStepForm, name="first")
    )

    url_name = "escape-editing-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class WalkCountingWizardViewSet(WizardViewSet):
    description = (
        "Four-step linear wizard wired to counting walker/dispatcher classes, "
        "so tests can assert exactly how much work one request does."
    )
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .step(PersonalDetailsForm, name="third")
        .step(ReviewForm, name="fourth")
        .configure(
            template_name="testapp/linear_wizard.html",
            step_dispatcher_class=CountingStepDispatcher,
            cursor_walker_class=CountingCursorWalker,
        )
    )

    url_name = "walk-counting-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


def build_item_steps(context):
    """Expansion builder: read the count answered earlier and produce that
    many item steps. Runs mid-walk, behind the validated count."""
    count = int(context.run.path.find_step(name="count").form.cleaned_data["count"])
    steps = Wizard()
    for index in range(count):
        steps = steps.step(ItemForm, name=f"item-{index}")
    return steps


class ExpandWizardViewSet(WizardViewSet):
    description = (
        "Pick a count, then .expand() grows that many item steps in the same "
        "walk, followed by a shared review step."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(build_item_steps)
        .step(ReviewForm, name="review")
        .configure(
            template_name="testapp/linear_wizard.html",
            step_dispatcher_class=CountingStepDispatcher,
            cursor_walker_class=CountingCursorWalker,
        )
    )

    url_name = "expand-wizard"

    def done(self, run):
        names = [
            step.data["name"] for step in _iter_path(run) if "name" in (step.data or {})
        ]
        return HttpResponse(f"completed items={','.join(names)}")


class EmptyExpandWizardViewSet(WizardViewSet):
    description = "An expansion that returns no steps, so the run skips it."
    template_name = "testapp/linear_wizard.html"
    # Two steps trail the expansion, so building the chain iterates through the
    # Expand node while it already has a `next`.
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .expand(lambda request: Wizard())
        .step(ReviewForm, name="review")
        .step(SecondStepForm, name="last")
    )

    url_name = "empty-expand-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class PathReadingGate(FormView):
    """A step that reads `context.run.path` as it renders, so a run whose
    expansion is sealed behind this cursor exercises flattening over a
    `PreservedExpand`."""

    form_class = FirstStepForm
    template_name = "testapp/linear_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Only read `path` on the real GET render, where the viewset has
        # recorded the render walk to reuse. During the throwaway validation
        # render inside a walk there is no such context, and reading `path`
        # would start a fresh walk that re-dispatches this very step.
        if self.request.method == "GET":
            names = [
                step.declaration.context.get("name") for step in self.request.run.path
            ]
            context["path_names"] = names
        return context


class SealableExpandWizardViewSet(WizardViewSet):
    description = (
        "A gate step sits between the count and the expansion, so the run can "
        "park before the expansion and hold it sealed."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .step(PathReadingGate, name="gate")
        .expand(build_item_steps)
        .step(ReviewForm, name="review")
    )

    url_name = "sealable-expand-wizard"

    def done(self, run):
        merged = MergeCleanedData().reduce(run.runtime_tree)
        return HttpResponse(f"count={merged['count']} name={merged.get('name', '')}")


def build_branching_items(request):
    """An expansion whose subtree contains a branch — allowed, since only
    expand-within-expand is barred."""
    return Wizard().branch(
        condition(
            lambda request: True,
            Wizard().step(BusinessDetailsForm, name="biz"),
        ),
        default=Wizard().step(PersonalDetailsForm, name="pers"),
    )


class BranchingExpandWizardViewSet(WizardViewSet):
    description = "An expansion that builds a branch rather than a flat list."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(build_branching_items)
        .step(ReviewForm, name="review")
    )

    url_name = "branching-expand-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class PathAwareWalkedPastWizardViewSet(WizardViewSet):
    """A step that reads the run from `get_initial()` with a step after it.

    `get_initial()` is one of the composition hooks Gandalf re-enters every
    time it replays a stored answer, so every request past the second step
    re-runs that read *inside* the walk. Without the `walking()` handoff it
    started a nested walk and recursed.
    """

    description = (
        "Path-reading step with a step after it, so the walk replays the "
        "read on every later request."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(EmailStepPrefilledFromPath, name="second")
        .step(ReviewForm, name="third")
    )

    url_name = "path-aware-walked-past-wizard"

    def done(self, run):
        payload = MergeCleanedData().reduce(run.path)
        return HttpResponse(f"completed {payload['name']} at {payload['email']}")


class EmptyPathReadingStepView(FormView):
    """First-step view that reads the run before any answer exists.

    The prefix handed to a first step is empty, which must read as an empty
    path rather than as "no walk in progress".
    """

    form_class = FirstStepForm
    template_name = "testapp/linear_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_initial(self):
        initial = super().get_initial()
        initial["name"] = f"seen-{len(list(self.request.run.path))}"
        return initial


class EmptyPathFirstStepWizardViewSet(WizardViewSet):
    description = "First step reads context.run.path, which is empty there."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(EmptyPathReadingStepView, name="first")
        .step(SecondStepForm, name="second")
    )

    url_name = "empty-path-first-step-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


def has_no_prior_answers(context):
    """Branch predicate reading the run from position 0, where it is empty."""
    return len(list(context.run.path)) == 0


class EmptyPathBranchWizardViewSet(WizardViewSet):
    description = "Branch at position 0 whose predicate reads the empty path before it."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .branch(
            condition(
                has_no_prior_answers,
                Wizard().step(FirstStepForm, name="first"),
            ),
            default=Wizard().step(SecondStepForm, name="second"),
        )
        .step(ReviewForm, name="review")
    )

    url_name = "empty-path-branch-wizard"

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


def _iter_path(run):
    yield from run.path


class StashingWizardViewSet(WizardViewSet):
    description = (
        "Linear wizard whose done() stashes the finished answers in the "
        "session, so the resurrect view can re-open them in a fresh run "
        "for editing. Its second step's photo is optional — the stash "
        "drops uploads, so a resurrected run sails past it."
    )
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
            name="first",
        )
        .step(
            OptionalPhotoForm,
            name="photo",
        )
    )

    url_name = "stashing-wizard"

    def done(self, run):
        SessionStashStore(run.context).put("contact", run.stash(label="contact"))
        first = run.path.find_step(name="first")
        return HttpResponse(f"stashed {first.form.cleaned_data['name']}")


class RequiredPhotoStashingWizardViewSet(WizardViewSet):
    description = (
        "Stashing wizard whose second step requires a file. The stash drops "
        "uploads, so resurrecting parks the run on the photo step, where the "
        "user re-uploads."
    )
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
            name="first",
        )
        .step(
            ProfilePhotoForm,
            name="photo",
        )
    )

    url_name = "required-photo-stashing-wizard"

    def done(self, run):
        SessionStashStore(run.context).put(
            "required-photo", run.stash(label="required-photo")
        )
        return HttpResponse(b"stashed with photo")


def _resurrect_stash(request, viewset_class, key):
    """Send the user into a fresh run seeded from the stash under `key`.

    The stash is read, not popped: re-opening it for another edit keeps
    working, and re-completing the wizard overwrites it with the new
    answers."""
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.get(key)
        url = viewset_class.resurrect(request, payload, expected_label=key)
    except (StashNotFound, InvalidStash):
        return HttpResponse(status=HTTPStatus.GONE)
    return redirect(url)


def resurrect_contact_stash(request):
    return _resurrect_stash(request, StashingWizardViewSet, "contact")


def resurrect_required_photo_stash(request):
    return _resurrect_stash(
        request, RequiredPhotoStashingWizardViewSet, "required-photo"
    )


class BranchingStashingWizardViewSet(WizardViewSet):
    description = (
        "Stashing wizard with a branch and an expansion, so its stash "
        "payload nests entries at every depth. done() stashes without a "
        "label under the 'members' key; the resurrect view consumes the "
        "stash and reopens the run at the count step."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            AccountTypeForm,
            name="account_type",
        )
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(
            ItemCountForm,
            name="count",
        )
        .expand(build_item_steps)
    )

    url_name = "branching-stashing-wizard"

    def done(self, run):
        SessionStashStore(run.context).put("members", run.stash())
        return HttpResponse(b"stashed members")


def resurrect_members_stash(request):
    """Consume the members stash and reopen it at the count step."""
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.pop("members")
        url = BranchingStashingWizardViewSet.resurrect(request, payload, step="count")
    except (StashNotFound, InvalidStash):
        return HttpResponse(status=HTTPStatus.GONE)
    return redirect(url)


def stashed_member_keys(request):
    """The bigger-collection page's view of which members are stashed."""
    stashes = SessionStashStore(WizardContext.from_request(request))
    return HttpResponse(",".join(stashes.keys()))


def discard_members_stash(request):
    SessionStashStore(WizardContext.from_request(request)).delete("members")
    return HttpResponse(b"discarded")


def resurrect_empty_stash(request):
    """Resurrect an empty payload into the stepless wizard: with no step to
    land on, the only URL is the bare run one, which completes on arrival."""
    url = EmptyWizardViewSet.resurrect(request, {"version": STASH_VERSION, "state": []})
    return redirect(url)


class SummaryStepView(SummaryMixin, StepFormView):
    """A check-your-answers step: `SummaryMixin` puts one row per answered
    step in the context, each with its formatted fields and change link."""

    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


class SummaryWizardViewSet(WizardViewSet):
    description = (
        "Summary: a check-your-answers step listing every answer, formatted, "
        "with a change link per step."
    )
    url_name = "summary-wizard"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type", label="Account type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(SummaryFieldsForm, name="preferences", label="Preferences")
        .step(SummaryStepView, name="summary")
        .configure(
            template_name="testapp/linear_wizard.html",
            step_dispatcher_class=CountingStepDispatcher,
            cursor_walker_class=CountingCursorWalker,
        )
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class CustomSummaryStepView(SummaryMixin, StepFormView):
    """Every hook the mixin exposes, overridden: the step label, the value
    formatting, and which fields appear at all."""

    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"

    def get_summary_label(self, step):
        return super().get_summary_label(step).upper()

    def include_summary_field(self, step, bound_field):
        return bound_field.name != "note"

    def format_value(self, bound_field, value):
        if bound_field.name == "starts_on":
            return value.strftime("%d/%m/%Y")
        return super().format_value(bound_field, value)


class CustomSummaryWizardViewSet(WizardViewSet):
    description = "Summary with the label, field selection and formatting overridden."
    url_name = "custom-summary-wizard"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(SummaryFieldsForm, name="preferences")
        .step(CustomSummaryStepView, name="summary")
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class SummaryDisplayWizardViewSet(WizardViewSet):
    description = "Summary of answers a page cannot show raw: files, times, groups."
    url_name = "summary-display-wizard"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(SummaryDisplayForm, name="delivery")
        .step(SummaryStepView, name="summary")
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class ShorterAddressForm(forms.Form):
    """The address a dynamic step asks for when it asks for less."""

    line_1 = forms.CharField(label="Address line 1")
    postcode = forms.CharField(label="Postcode")


class DynamicAddressStepView(StepFormView):
    """A step that picks its form per request, so what it asks cannot be
    read off the declaration."""

    template_name = "testapp/linear_wizard.html"

    def get_form_class(self):
        return ShorterAddressForm


class DynamicSummaryStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"
    summary_fields = {"address": [Group("line_1", "town", "postcode", separator=", ")]}


class DynamicSummaryWizardViewSet(WizardViewSet):
    description = (
        "Summary over a step that chooses its form per request: a group "
        "names more than the step asks, and survives it."
    )
    url_name = "dynamic-summary-wizard"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(DynamicAddressStepView, name="address", label="Address")
        .step(DynamicSummaryStepView, name="summary")
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


class GroupedSummaryStepView(SummaryMixin, StepFormView):
    """A check-your-answers step that shapes a row declaratively: the four
    fields of an address read as one line, and the token that looked it up
    reads as nothing at all."""

    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"
    summary_fields = {
        "address": [
            Group("line_1", "line_2", "town", "postcode", separator=", "),
            Hide("lookup_token"),
        ],
    }


class GroupedSummaryWizardViewSet(WizardViewSet):
    description = (
        "Summary whose address step reads as one line: four fields grouped, "
        "the lookup token hidden, declared on the summary view."
    )
    url_name = "grouped-summary-wizard"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, name="who", label="Who you are")
        .step(AddressForm, name="address", label="Address")
        .step(GroupedSummaryStepView, name="summary")
        .configure(
            template_name="testapp/linear_wizard.html",
            step_dispatcher_class=CountingStepDispatcher,
            cursor_walker_class=CountingCursorWalker,
        )
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


def build_delivery_address(context):
    """One address step, or none. The expansion decides whether to ask, so
    "address" is a name the declaration itself never mentions."""
    delivery = context.run.path.find_step(name="delivery")
    if delivery.form.cleaned_data["delivery"] == "collect":
        return Wizard()
    return Wizard().step(AddressForm, name="address", label="Address")


class ExpandedSummaryWizardViewSet(WizardViewSet):
    description = (
        "Summary over a wizard that grows mid-walk: the address step exists "
        "only for a home delivery, so the shaping keyed on its name cannot be "
        "checked against the declaration."
    )
    url_name = "expanded-summary-wizard"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(DeliveryChoiceForm, name="delivery", label="Delivery")
        .expand(build_delivery_address)
        .step(GroupedSummaryStepView, name="summary")
    )

    def done(self, run):
        return HttpResponse(f"completed {run.run_id}")


# --- Task list scenarios -------------------------------------------------------


FIRST_STEP = Wizard().step(FirstStepForm, name="first")


class Scenario(TaskList):
    # No review step: one valid answer walks straight to done().
    plain = Section(FIRST_STEP, title="Plain")
    # Escapes with Advance, so its run never completes.
    advancing = Section(
        Wizard().step(NewsletterForm, name="newsletter"), title="Advancing"
    )


class ScenarioViewSet(TaskListViewSet):
    description = "Task list over sections that exercise the awkward run states."
    template_name = "testapp/task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "scenario-hub"
    task_list = Scenario


GUESTS = AddAnother(
    Wizard().step(GuestForm, name="guest").step(ConfirmForm, name="review"),
    item_name="Guest",
    item_title="name",
)


class Org(TaskList):
    details = Section(FIRST_STEP, title="Details")
    org_guests = GUESTS.replace(title="Guests")


class OrgViewSet(TaskListViewSet):
    """Mounted under an org prefix. Nothing here forwards the slug: every
    entry is mounted beneath the page, so the request's own kwargs reach
    every URL the page builds."""

    description = "Task list whose entries carry mount-prefix URL kwargs."
    template_name = "testapp/task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    add_another_template_name = "testapp/items.html"
    remove_template_name = "testapp/collection_remove.html"
    url_name = "org-hub"
    task_list = Org


COUNTING = (
    Wizard()
    .step(FirstStepForm, name="first")
    .step(SecondStepForm, name="second")
    .configure(
        template_name="testapp/linear_wizard.html",
        step_dispatcher_class=CountingStepDispatcher,
        cursor_walker_class=CountingCursorWalker,
    )
)


class Counting(TaskList):
    counting = Section(COUNTING, title="Counting")
    other = Section(COUNTING, title="Other")


class CountingViewSet(TaskListViewSet):
    description = "Task list over counting sections, for asserting a row's cost."
    template_name = "testapp/task_list.html"
    url_name = "counting-hub"
    task_list = Counting
    builds = 0

    def build_rows(self):
        self.builds += 1
        return super().build_rows()

    def get_context_data(self, **kwargs):
        """An app wanting something the `TaskListPage` does not offer asks
        for the rows a second time — and gets the ones already built."""
        context = super().get_context_data(**kwargs)
        context["first_unfinished"] = next(
            (row for row in self.get_rows() if not row.is_complete), None
        )
        context["builds"] = self.builds
        return context


# --- Storage that outlives a session -----------------------------------------


class Durable(TaskList):
    durable = Section(
        Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second"),
        title="Durable",
    )


class DurableViewSet(TaskListViewSet):
    """Both stores swapped once, on the root, and every section gets them."""

    description = "Task list whose sections and bookkeeping outlive the session."
    template_name = "testapp/task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "durable-hub"
    storage_class = ModelStorage
    journey_store_class = ModelJourneyStore
    task_list = Durable


# --- Gated, and beside an add-another --------------------------------------------


class GatedSecondSection(SectionViewSet):
    wizard = FIRST_STEP

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("first")


class Gated(TaskList):
    first = Section(FIRST_STEP, title="First")
    second = Section(GatedSecondSection, title="Second")


class GatedViewSet(TaskListViewSet):
    description = "Task list whose second section unlocks when the first ends."
    template_name = "testapp/task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "gated-hub"
    task_list = Gated


class Party(TaskList):
    venue = Section(FIRST_STEP, title="Venue")
    guests = GUESTS.replace(title="Guests")


class PartyViewSet(TaskListViewSet):
    description = "Task list with an add-another row beside a plain section."
    template_name = "testapp/task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    add_another_template_name = "testapp/items.html"
    remove_template_name = "testapp/collection_remove.html"
    url_name = "party-hub"
    task_list = Party


# --- Add-another pages mounted on their own -------------------------------------


class GuestsViewSet(AddAnotherViewSet):
    """An add-another page mounted on its own, returning to a page it is
    not listed by — the shape `examples/insurance.py` uses."""

    description = "Add another: a list of items with full CRUD."
    template_name = "testapp/items.html"
    remove_template_name = "testapp/collection_remove.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "standalone-guests"
    key = "standalone-guests"
    add_another = GUESTS
    task_list_url_name = "party-hub"


class LockedGuestsViewSet(GuestsViewSet):
    description = "An add-another page whose items are all locked."
    url_name = "locked-guests"
    key = "locked-guests"

    def entry_blocked(self, entry, store):
        return True


class MinimumGuestsViewSet(GuestsViewSet):
    description = "An add-another page that needs at least one item to be complete."
    url_name = "minimum-guests"
    key = "minimum-guests"
    add_another = GUESTS.replace(min_items=1)


class AdvancingGuestsViewSet(GuestsViewSet):
    description = "An add-another page over items that park rather than complete."
    url_name = "advancing-guests"
    key = "advancing-guests"
    add_another = GUESTS.replace(
        wizard=Wizard().step(NewsletterForm, name="newsletter"),
        item_title="email",
    )


class AnonymousGuestsViewSet(GuestsViewSet):
    description = "ImproperlyConfigured: items that cannot name themselves."
    url_name = "anonymous-guests"
    key = "anonymous-guests"
    add_another = GUESTS.replace(item_title=None)


class OffRouteGuestsViewSet(GuestsViewSet):
    """Items named by a step that is not on the route the user took, so the
    row falls back to a positional name rather than inventing one."""

    description = "Items that answer nothing that names them."
    url_name = "off-route-guests"
    key = "off-route-guests"
    add_another = GUESTS.replace(
        wizard=Wizard()
        .step(GuestForm, name="guest")
        .branch(
            condition(
                lambda context: False, Wizard().step(NewsletterForm, name="newsletter")
            )
        )
        .step(ConfirmForm, name="review"),
        item_title="email",
    )


class ReshapedGuestsViewSet(GuestsViewSet):
    """A deploy reshaped the item, so the label moved — once, for both the
    stamp and the check."""

    description = "Items whose shape was reshaped and re-labelled."
    url_name = "reshaped-guests"
    key = "reshaped-guests"
    add_another = GUESTS.replace(label="guests-v2", item_name=None)


class TitledGuestsViewSet(GuestsViewSet):
    """Items named by a callable of the finished run, not one field."""

    description = "Items named by a callable rather than a field."
    url_name = "titled-guests"
    key = "titled-guests"
    add_another = GUESTS.replace(
        item_title=lambda run: run.path.find_step(name="guest")
        .form.cleaned_data["name"]
        .upper()
    )


class DurableGuestsViewSet(GuestsViewSet):
    """Items on model-backed storage — both stores swapped, which is what a
    list the user grows over days needs."""

    description = "Items whose runs and registry outlive the session."
    url_name = "durable-guests"
    key = "durable-guests"
    storage_class = ModelStorage
    journey_store_class = ModelCollectionStore
    task_list_url_name = "durable-hub"


# --- Journeys ----------------------------------------------------------------


class ShortMemoryJourneyStore(SessionJourneyStore):
    """A session store that keeps one completed journey, so pruning can be
    watched without submitting eleven applications."""

    max_completed_journeys = 1


class Submit(TaskList):
    first = Section(FIRST_STEP, title="First")
    second = Section(FIRST_STEP, title="Second")


class SubmitViewSet(TaskListViewSet):
    """A journey-mounted task list whose submit records nothing: the
    tombstone it leaves is the bare one, and its default `submitted()` is
    the 404 the library ships."""

    description = (
        "Journeys: a task list under a journey segment, submitting to a bare tombstone."
    )
    template_name = "testapp/journey_hub.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "submit-hub"
    journey_store_class = ShortMemoryJourneyStore
    task_list = Submit

    def journey_done(self, page, store):
        return HttpResponse(f"submitted {self.get_journey()}")


def staff_sign_in(request):
    """Chapter 5's demo door: sign in as a staff member so `readme-paper`
    asks the extra question. A real project has a login; this one mints a
    staff user on the spot and comes straight back."""
    user, _ = get_user_model().objects.get_or_create(
        username="fund-officer", defaults={"is_staff": True}
    )
    login(request, user)
    return redirect("readme-paper")


def staff_sign_out(request):
    logout(request)
    return redirect("readme-paper")
