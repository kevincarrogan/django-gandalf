from gandalf.form_views import form_view_factory
from gandalf.wizards import Wizard, condition
from gandalf.viewsets import WizardViewSet

from django.http import HttpResponse
from django.urls import reverse

from .forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
    PersonalDetailsForm,
    ReviewForm,
    SecondStepForm,
)


def is_business_account(request):
    account_type_submission = request.wizard.get_submissions()[0]
    return account_type_submission["account_type"] == "business"


class SingleStepWizardViewSet(WizardViewSet):
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
        submission = bound_wizard.get_submissions()[0]
        return HttpResponse(f"completed {submission.get('name')}")


class SingleStepWizardDoneRunDataViewSet(WizardViewSet):
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
            "linear-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


class DoneLinearWizardViewSet(WizardViewSet):
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
        name_submission, email_submission = bound_wizard.get_submissions()
        return HttpResponse(
            f"completed {name_submission.get('name')} "
            f"at {email_submission.get('email')}"
        )


class OtherLinearWizardViewSet(WizardViewSet):
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
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm)
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
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account"})
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
        submissions = bound_wizard.get_submissions()
        review_step = bound_wizard.find_step(step_name="review")
        missing_step = bound_wizard.find_step(step_name="nonexistent")
        account_steps = bound_wizard.filter_steps(step_name="account")
        return HttpResponse(
            f"completed {len(submissions)} via {review_step.declaration.__name__} "
            f"missing={missing_step} account_count={len(account_steps)}"
        )


class DuplicateContextWizardViewSet(WizardViewSet):
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
    wizard = object()


FirstStepFormView = form_view_factory(
    FirstStepForm,
    template_name="testapp/single_step_wizard.html",
)


class FormViewStepWizardViewSet(WizardViewSet):
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
    wizard = Wizard().step(FirstStepForm)

    def get_wizard_url(self, run_id):
        return reverse(
            "missing-template-wizard-run",
            kwargs={
                "run_id": run_id,
            },
        )


class PreConfiguredWizardViewSet(WizardViewSet):
    wizard = Wizard().step(FirstStepForm).configure(
        template_name="testapp/single_step_wizard.html",
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
    template_name = "testapp/single_step_wizard.html"

    def get_wizard(self):
        return Wizard().step(FirstStepForm).configure(
            template_name=self.template_name,
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
