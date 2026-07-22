from gandalf import tree as tree_module
from gandalf import wizard
from gandalf.form_views import form_view_factory
from gandalf.wizard import (
    MergeCleanedData,
    StepNameRouter,
    Wizard,
    condition,
    named,
)
from gandalf.viewsets import WizardViewSet

from http import HTTPStatus

from django.http import HttpResponse
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView
from django.views.generic.edit import FormView

from gandalf.escapes import Obliterate
from gandalf.storage import SessionStorage

from .forms import (
    AccountTypeForm,
    BareEscapeForm,
    BusinessDetailsForm,
    CancelSignupForm,
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
)


class IndexView(TemplateView):
    template_name = "testapp/index.html"

    def get_context_data(self, **kwargs):
        from django.urls import get_resolver

        context = super().get_context_data(**kwargs)
        entries = []
        for pattern in get_resolver(None).url_patterns:
            if not hasattr(pattern, "callback"):
                continue
            if "run_id" in pattern.pattern.converters:
                continue
            if pattern.name == "index":
                continue
            callback = pattern.callback
            view_class = getattr(callback, "view_class", None)
            if view_class is None:
                continue
            entries.append(
                {
                    "name": pattern.name,
                    "url": reverse(pattern.name),
                    "view_name": view_class.__name__,
                    "description": getattr(view_class, "description", ""),
                }
            )
        entries.sort(key=lambda e: e["view_name"])
        context["entries"] = entries
        return context


def is_business_account(request):
    account_step = request.wizard.find_step(step_name="account_type")
    return account_step.form.cleaned_data["account_type"] == "business"


class SingleStepWizardViewSet(WizardViewSet):
    description = "A single-step wizard with a custom done() returning the run id."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "single-step-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class RunUnavailableWizardViewSet(WizardViewSet):
    description = (
        "Single-step wizard overriding run_unavailable() so finished and "
        "unknown runs answer differently instead of redirecting to the start."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "run-unavailable-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")

    def run_unavailable(self, bound_wizard, reason):
        return HttpResponse(f"unavailable: {reason}", status=HTTPStatus.GONE)


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

    def done(self, bound_wizard):
        cleaned_data = bound_wizard.runtime_tree.form.cleaned_data
        return HttpResponse(f"completed {cleaned_data['name']}")


class SingleStepWizardDoneRunDataViewSet(WizardViewSet):
    description = (
        "Single-step wizard; done() reads raw stored state via get_run_data()."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm, name="first")

    url_name = "single-step-wizard-done-run-data"

    def done(self, bound_wizard):
        run_data = bound_wizard.get_run_data()
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

    def done(self, bound_wizard):
        first = bound_wizard.runtime_tree
        second = first.next
        return HttpResponse(
            f"completed {first.form.cleaned_data['name']} "
            f"at {second.form.cleaned_data['email']}"
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
        .step(AccountTypeForm, context={"step_name": "account_type"})
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


class SectionRouter(StepNameRouter):
    """Custom router keying step URLs on a `section` context entry rather
    than `step_name`."""

    context_key = "section"


class SectionEditingWizardViewSet(WizardViewSet):
    description = (
        "Wizard configuring a custom `step_router_class` that routes step "
        "URLs by a `section` context entry rather than `step_name`."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"section": "account"})
        .step(PersonalDetailsForm, context={"section": "details"})
        .step(ReviewForm, context={"section": "review"})
        .configure(
            template_name="testapp/editing_wizard.html",
            step_router_class=SectionRouter,
        )
    )

    url_name = "section-editing-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class EditingBranchingWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard whose review template renders edit links for each prior "
        "step (account type and the active arm's detail step)."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"step_name": "business_name"}
                ),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"step_name": "preferred_name"}
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
    )

    url_name = "editing-branching-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class DoneBranchingWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard exercising step_name context, find_step / filter_steps, "
        "and ContextFinder over the declared tree."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, context={"step_name": "business"}),
            ),
            default=Wizard().step(
                PersonalDetailsForm,
                context={"step_name": "personal"},
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .step(SecondStepForm, name="second")
    )

    url_name = "done-branching-wizard"

    def done(self, bound_wizard):
        from gandalf import tree as tree_module

        all_steps = bound_wizard.filter_steps()
        review_step = bound_wizard.find_step(step_name="review")
        missing_step = bound_wizard.find_step(step_name="nonexistent")
        account_steps = bound_wizard.filter_steps(step_name="account_type")

        declared_finder = tree_module.ContextFinder({})
        declared_finder.visit(bound_wizard.wizard.tree)

        return HttpResponse(
            f"completed {len(all_steps)} via "
            f"{review_step.declaration.declaration.__name__} "
            f"missing={missing_step} account_count={len(account_steps)} "
            f"declared_count={len(declared_finder.all())}"
        )


def _always_false(request):
    return False


class BranchEntryWizardViewSet(WizardViewSet):
    description = "Wizard whose very first node is a branch (no preceding step)."
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.branch(
        condition(_always_false, wizard.step(FirstStepForm, name="first")),
        default=wizard.step(SecondStepForm, name="second"),
    )

    url_name = "branch-entry-wizard"


class DuplicateContextWizardViewSet(WizardViewSet):
    description = "Two steps sharing the same step_name; done() shows find_step raising on ambiguity."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "duplicate"})
        .step(SecondStepForm, context={"step_name": "duplicate"})
    )

    url_name = "duplicate-context-wizard"

    def done(self, bound_wizard):
        try:
            bound_wizard.find_step(step_name="duplicate")
        except Exception as exc:
            return HttpResponse(f"raised {type(exc).__name__}")
        return HttpResponse("no raise")


class InvalidWizardViewSet(WizardViewSet):
    description = "Wizard attribute is not a Wizard instance; visiting should error."
    url_name = "invalid-wizard"
    wizard = object()


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class EmptyWizardViewSet(WizardViewSet):
    description = "Wizard with no steps; should immediately reach done()."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard()

    url_name = "empty-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class EmailStepPrefilledFromPath(FormView):
    """Second-step view that pre-fills its email field from the
    previous step's submitted name, by reading `request.wizard.path`
    mid-wizard."""

    form_class = SecondStepForm
    template_name = "testapp/linear_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_initial(self):
        initial = super().get_initial()
        path = self.request.wizard.path
        if path is not None:
            name = path.form.cleaned_data["name"]
            initial["email"] = f"{name.lower()}@example.com"
        return initial


class PathAwareLinearWizardViewSet(WizardViewSet):
    description = (
        "Linear wizard whose second step pre-fills its initial value from "
        "request.wizard.path mid-wizard."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.step(FirstStepForm, name="first").step(
        EmailStepPrefilledFromPath, name="second"
    )

    url_name = "path-aware-linear-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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
        "request.wizard.path mid-wizard."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.step(FirstStepFromFormView, name="first").step(
        EmailStepPrefilledFromPath, name="second"
    )

    url_name = "path-aware-form-view-first-step-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class BranchingMergedPayloadWizardViewSet(WizardViewSet):
    description = (
        "Branching wizard with a two-step arm; done() merges cleaned data "
        "across the path via MergeCleanedData."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        wizard.step(AccountTypeForm, context={"step_name": "account_type"})
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

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"account_type={payload['account_type']} "
            f"business_name={payload['business_name']} "
            f"email={payload['email']} "
            f"confirmed={payload['confirmed']}"
        )


def _never_matches(request):
    return False


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
        .step(AccountTypeForm, context={"step_name": "skip_branch_account"})
    )

    url_name = "empty-branch-arm-merged-payload-wizard"

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
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
        wizard.step(AccountTypeForm, context={"step_name": "account_type"})
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

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.runtime_tree)
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

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"completed name={payload['name']} email={payload['email']}"
        )


class DoubleConfiguredWizardViewSet(WizardViewSet):
    description = "Wizard configured both via get_wizard() and configure_wizard() to test layering."
    template_name = "testapp/single_step_wizard.html"

    def get_wizard(self, bound_wizard):
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

    def get_wizard(self, bound_wizard):
        state = bound_wizard.get_state()
        wizard = Wizard().step(ItemCountForm, context={"step_name": "count"})
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(
                    ItemForm, context={"index": index}, name=f"item-{index}"
                )
        return wizard

    url_name = "dynamic-wizard"

    def done(self, bound_wizard):
        node = bound_wizard.runtime_tree.next
        names = []
        while node is not None:
            names.append(node.data["name"])
            node = node.next
        return HttpResponse(f"completed {', '.join(names)}")


class MergeWithLists(MergeCleanedData):
    """MergeCleanedData variant that respects a `list_key` context entry.

    Steps with `context={"list_key": "items"}` contribute their cleaned
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
        Wizard()
        .step(ProfilePhotoForm, context={"step_name": "photo"})
        .step(FirstStepForm, name="first")
    )

    url_name = "file-uploading-wizard"

    def done(self, bound_wizard):
        photo_step = bound_wizard.find_step(step_name="photo")
        filename = photo_step.files["photo"]["name"]
        return HttpResponse(f"completed {filename}")


class DynamicListPayloadWizardViewSet(WizardViewSet):
    description = (
        "Dynamic wizard whose generated item steps are condensed into a "
        "list under one key via a context-aware MergeCleanedData subclass."
    )
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, bound_wizard):
        state = bound_wizard.get_state()
        wizard = Wizard().step(ItemCountForm, context={"step_name": "count"})
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(
                    ItemForm,
                    context={"list_key": "items", "index": index},
                    name=f"item-{index}",
                )
        return wizard

    url_name = "dynamic-list-payload-wizard"

    def done(self, bound_wizard):
        import json

        payload = MergeWithLists().reduce(bound_wizard.path)
        return HttpResponse(json.dumps(payload, sort_keys=True))


class NamedHelperWizardViewSet(WizardViewSet):
    description = "Wizard whose steps are declared via the `named()` helper."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(named("first", FirstStepForm))
        .step(named("second", SecondStepForm))
    )

    url_name = "named-helper-wizard"

    def done(self, bound_wizard):
        first = bound_wizard.find_step(step_name="first")
        second = bound_wizard.find_step(step_name="second")
        return HttpResponse(
            f"completed first={first.form.cleaned_data['name']} "
            f"second={second.form.cleaned_data['email']}"
        )


class FileEditingWizardViewSet(WizardViewSet):
    description = (
        "Wizard whose first step is an optional-photo upload, supporting an "
        "edit cycle on that step (replace, add, or leave alone)."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, context={"step_name": "photo"})
        .step(ReviewForm, context={"step_name": "review"})
    )

    url_name = "file-editing-wizard"

    def done(self, bound_wizard):
        photo_step = bound_wizard.find_step(step_name="photo")
        photo_ref = (photo_step.files or {}).get("photo")
        filename = photo_ref["name"] if photo_ref else "no-photo"
        return HttpResponse(f"completed {filename}")


class EmptyBranchArmContextFinderViewSet(WizardViewSet):
    description = (
        "Wizard with an unmatched no-default branch; done() runs ContextFinder "
        "over both the declared tree (covers the no-default branch arc) and "
        "the runtime tree (covers the empty-selected-arm branch arc)."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(named("first", FirstStepForm))
        .branch(
            condition(_never_matches, Wizard().step(SecondStepForm, name="second")),
        )
        .step(named("review", ReviewForm))
    )

    url_name = "empty-branch-arm-context-finder-wizard"

    def done(self, bound_wizard):
        declared_finder = tree_module.ContextFinder({})
        declared_finder.visit(bound_wizard.wizard.tree)
        runtime_finder = tree_module.ContextFinder({})
        runtime_finder.visit(bound_wizard.runtime_tree)
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
        .step(named("account_type", AccountTypeForm))
        .branch(
            condition(
                is_business_account,
                Wizard().step(named("business_name", BusinessDetailsForm)),
            ),
            default=Wizard().step(named("preferred_name", PersonalDetailsForm)),
        )
        .step(named("review", ReviewForm))
    )

    url_name = "routed-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class LookupProbeStepView(FormView):
    """Step view that probes render_edit for its own (still unanswered)
    step while rendering: `require_data` skips the match, so the probe
    observes StepNotFound mid-run. Also probes the `name=` lookup
    shorthand and the TypeError for passing it alongside `step_name`."""

    form_class = SecondStepForm
    template_name = "testapp/editing_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        from gandalf.runtime import StepNotFound

        context = super().get_context_data(**kwargs)
        try:
            self.request.wizard.render_edit(step_name="second")
        except StepNotFound:
            context["lookup_probe"] = "step-not-found"
        found = self.request.wizard.find_step(name="first")
        context["name_lookup_probe"] = found.declaration.context["step_name"]
        try:
            self.request.wizard.find_step(name="first", step_name="first")
        except TypeError:
            context["ambiguous_lookup_probe"] = "type-error"
        return context


class ProgrammaticLookupWizardViewSet(WizardViewSet):
    description = (
        "Exercises programmatic BoundWizard lookups: a mid-run render_edit "
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

    def done(self, bound_wizard):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from gandalf import tree as gandalf_tree
        from gandalf.runtime import BoundWizard, StepNotFound

        upload = SimpleUploadedFile("orphan.txt", b"orphan-bytes")
        ref = bound_wizard.file_storage.save(bound_wizard.run_id, upload)
        try:
            bound_wizard.edit({"name": "x"}, files={"upload": ref}, step_name="missing")
        except StepNotFound:
            deleted = not bound_wizard.file_storage.backend.exists(ref["tmp_name"])
        else:
            deleted = False

        detached = BoundWizard(self.request, bound_wizard.storage)
        cursor = bound_wizard.cursor()
        foreign_declaration = gandalf_tree.Step(FirstStepForm)
        nav_probe = (
            detached.run_url is None
            and detached.back_url is None
            and bound_wizard.back_url is None
            and bound_wizard.run_url == self.get_wizard_url(bound_wizard.run_id)
            and bound_wizard.previous_step(cursor, foreign_declaration) is None
        )
        resolved = bound_wizard.render_edit(step_name="first")
        return HttpResponse(
            f"completed edit-cleanup={deleted} nav-probe={nav_probe} "
            f"resolve-status={resolved.status_code}"
        )


def _business_was_acme(request):
    business_step = request.wizard.find_step(step_name="business_name")
    return business_step.data["business_name"] == "Acme"


class PathProbeStepView(FormView):
    """Step view that reads request.wizard.path while rendering — the
    mid-run introspection that must stay safe when later branch regions
    are opaque."""

    form_class = PersonalDetailsForm
    template_name = "testapp/editing_wizard.html"

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        names = []
        node = self.request.wizard.path
        while node is not None:
            names.append(node.declaration.context["step_name"])
            node = node.next
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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class UnroutableWizardViewSet(WizardViewSet):
    description = (
        "Wizard with an unnamed step: resolving it at the HTTP boundary "
        "raises ImproperlyConfigured because every step needs a routable "
        "name."
    )
    template_name = "testapp/editing_wizard.html"
    wizard = Wizard().step(FirstStepForm).step(named("second", SecondStepForm))

    url_name = "unroutable-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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
        Wizard()
        .step(OrgScopedStepView, context={"step_name": "first"})
        .step(ReviewForm, context={"step_name": "review"})
    )

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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
        .step(FirstStepForm, context={"step_name": "first"})
        .branch(
            condition(
                _always_true,
                Wizard().step(SecondStepForm, context={"step_name": "second"}),
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .step(AccountTypeForm, context={"step_name": "tail"})
    )

    url_name = "branch-edit-rejection-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        newsletter = bound_wizard.find_step(name="newsletter")
        return HttpResponse(f"completed {newsletter.form.cleaned_data['email']}")


class EscapeAdvanceFinalStepWizardViewSet(WizardViewSet):
    description = "Single step escaping with Advance, so the escape defers done()."
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(NewsletterForm, name="newsletter")

    url_name = "escape-advance-final-step-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class BareEscapeWizardViewSet(WizardViewSet):
    description = "Raises the base Escape, which the viewset rejects as misuse."
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(BareEscapeForm, name="bare")

    url_name = "bare-escape-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class EscapeParkFileWizardViewSet(WizardViewSet):
    description = "Escapes with Park from a step that uploaded a file."
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard().step(EscapingPhotoForm, name="photo").step(FirstStepForm, name="first")
    )

    url_name = "escape-park-file-wizard"

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


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

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")
