from gandalf import wizard
from gandalf.form_views import form_view_factory
from gandalf.wizard import Wizard, condition
from gandalf.viewsets import WizardViewSet

from django.http import HttpResponse
from django.urls import reverse
from django.views.generic import TemplateView

from .forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
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
    return account_step.data["account_type"] == "business"


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
        submission = bound_wizard.runtime_tree.data
        return HttpResponse(f"completed {submission.get('name')}")


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
            f"completed {first.data.get('name')} at {second.data.get('email')}"
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


class DoubleConfiguredWizardViewSet(WizardViewSet):
    description = "Wizard configured both via get_wizard() and configure_wizard() to test layering."
    template_name = "testapp/single_step_wizard.html"

    def get_wizard(self):
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
