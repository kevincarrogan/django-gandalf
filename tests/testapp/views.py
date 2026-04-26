from gandalf.wizards import Wizard
from gandalf.viewsets import WizardViewSet

from django.http import HttpResponse
from django.urls import reverse

from .forms import FirstStepForm, SecondStepForm


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
