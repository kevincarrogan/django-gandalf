from gandalf.wizards import Wizard
from gandalf.viewsets import WizardViewSet

from .forms import FirstStepForm, SecondStepForm


class SingleStepWizardViewSet(WizardViewSet):
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["step_title"] = "First step"
        return context


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
