from gandalf import wizard
from gandalf.form_views import form_view_factory
from gandalf.wizard import MergeCleanedData, Wizard, condition
from gandalf.viewsets import WizardViewSet

from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import TemplateView
from django.views.generic.edit import FormView

from .forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
    ItemCountForm,
    ItemForm,
    PersonalDetailsForm,
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
    wizard = Wizard().step(FirstStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "single-step-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class SingleStepWizardWithoutDoneViewSet(WizardViewSet):
    description = "Single-step wizard with no done() override (falls back to default)."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "single-step-wizard-without-done-run",
            kwargs={
                "run_id": run_id,
            },
        )


class SingleStepWizardDoneDataViewSet(WizardViewSet):
    description = (
        "Single-step wizard; done() reads the submitted form data via the runtime tree."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "single-step-wizard-done-data-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        cleaned_data = bound_wizard.runtime_tree.form.cleaned_data
        return HttpResponse(f"completed {cleaned_data['name']}")


class SingleStepWizardDoneRunDataViewSet(WizardViewSet):
    description = (
        "Single-step wizard; done() reads raw stored state via get_run_data()."
    )
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "single-step-wizard-done-run-data-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        run_data = bound_wizard.get_run_data()
        submission = run_data["state"][0]["step"]
        return HttpResponse(f"completed {submission.get('name')}")


class LinearWizardViewSet(WizardViewSet):
    description = (
        "Two-step linear wizard built from the module-level `wizard` instance."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = wizard.step(FirstStepForm).step(SecondStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "linear-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


class DoneLinearWizardViewSet(WizardViewSet):
    description = "Two-step linear wizard with a done() that combines both submissions."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "done-linear-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
        )
        .step(
            SecondStepForm,
        )
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "other-linear-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


class RecreatedLinearWizardViewSet(WizardViewSet):
    description = (
        "Two-step linear wizard rendered with the recreated_linear_wizard template."
    )
    template_name = "testapp/recreated_linear_wizard.html"
    wizard = (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "recreated-linear-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


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
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "branching-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


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

    def get_wizard_url(self, run_id):
        return reverse(
            "editing-branching-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
        .step(SecondStepForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "done-branching-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
        condition(_always_false, wizard.step(FirstStepForm)),
        default=wizard.step(SecondStepForm),
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "branch-entry-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


class DuplicateContextWizardViewSet(WizardViewSet):
    description = "Two steps sharing the same step_name; done() shows find_step raising on ambiguity."
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "duplicate"})
        .step(SecondStepForm, context={"step_name": "duplicate"})
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "duplicate-context-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        try:
            bound_wizard.find_step(step_name="duplicate")
        except Exception as exc:
            return HttpResponse(f"raised {type(exc).__name__}")
        return HttpResponse("no raise")


class InvalidWizardViewSet(WizardViewSet):
    description = "Wizard attribute is not a Wizard instance; visiting should error."
    wizard = object()


FirstStepFormView = form_view_factory(
    FirstStepForm,
    template_name="testapp/single_step_wizard.html",
)


class FormViewStepWizardViewSet(WizardViewSet):
    description = (
        "Step backed by a form_view_factory FormView rather than a bare Form class."
    )
    wizard = Wizard().step(FirstStepFormView)

    def get_wizard_url(self, run_id):
        return reverse(
            "form-view-step-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class FormViewStepRaisesNotImplementedViewSet(WizardViewSet):
    description = (
        "FormView-backed step whose done() reads runtime_tree.form to surface "
        "the NotImplementedError raised for FormView-declared steps."
    )
    wizard = Wizard().step(FirstStepFormView)

    def get_wizard_url(self, run_id):
        return reverse(
            "form-view-step-not-implemented-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        try:
            bound_wizard.runtime_tree.form
        except NotImplementedError:
            return HttpResponse(f"form_not_implemented {bound_wizard.run_id}")
        return HttpResponse(f"completed {bound_wizard.run_id}")


class MissingTemplateWizardViewSet(WizardViewSet):
    description = (
        "Wizard with neither template_name nor configured template (expect failure)."
    )
    wizard = Wizard().step(FirstStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "missing-template-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


class PreConfiguredWizardViewSet(WizardViewSet):
    description = (
        "Wizard whose template_name comes from Wizard.configure() rather than the view."
    )
    wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(
            template_name="testapp/single_step_wizard.html",
        )
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "pre-configured-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")


class EmptyWizardViewSet(WizardViewSet):
    description = "Wizard with no steps; should immediately reach done()."
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard()

    def get_wizard_url(self, run_id):
        return reverse(
            "empty-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
    wizard = (
        wizard.step(FirstStepForm)
        .step(EmailStepPrefilledFromPath)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "path-aware-linear-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
                wizard.step(BusinessDetailsForm).step(SecondStepForm),
            ),
            default=wizard.step(PersonalDetailsForm),
        )
        .step(ReviewForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "branching-merged-payload-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
        wizard.step(FirstStepForm)
        .branch(
            condition(_never_matches, wizard.step(SecondStepForm)),
        )
        .step(AccountTypeForm, context={"step_name": "skip_branch_account"})
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "empty-branch-arm-merged-payload-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
                wizard.step(BusinessDetailsForm),
            ),
            default=wizard.step(PersonalDetailsForm),
        )
        .step(ReviewForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "runtime-tree-branching-merge-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
        Wizard()
        .step(FirstStepForm)
        .step(SecondStepForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "merged-payload-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
            .step(FirstStepForm)
            .configure(
                template_name=self.template_name,
            )
        )

    def configure_wizard(self, wizard):
        return wizard.configure(template_name=self.template_name)

    def get_wizard_url(self, run_id):
        return reverse(
            "double-configured-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


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
                wizard = wizard.step(ItemForm, context={"index": index})
        return wizard

    def get_wizard_url(self, run_id):
        return reverse(
            "dynamic-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

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
                )
        return wizard

    def get_wizard_url(self, run_id):
        return reverse(
            "dynamic-list-payload-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )

    def done(self, bound_wizard):
        import json

        payload = MergeWithLists().reduce(bound_wizard.path)
        return HttpResponse(json.dumps(payload, sort_keys=True))
