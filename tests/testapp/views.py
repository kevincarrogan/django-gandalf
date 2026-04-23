from django import forms

from gandalf import Wizard, WizardViewSet


class AccountForm(forms.Form):
    email = forms.EmailField()


class WizardStepViewSet(WizardViewSet):
    template_name = "tests/testapp/wizard_step.html"
    wizard = Wizard().step(AccountForm)
