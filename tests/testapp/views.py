from gandalf.wizards import Wizard
from gandalf.viewsets import WizardViewSet

from .forms import FirstStepForm


class SingleStepWizardViewSet(WizardViewSet):
    template_name = "testapp/single_step_wizard.html"
    wizard = Wizard().step(FirstStepForm)
