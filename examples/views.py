from .core import NamedURLRouter, Wizard, WizardViewSet
from .wizards import main_wizard
from .forms import FirstForm, SecondForm, ThirdForm


class MyWizardViewSet(WizardViewSet):
    wizard = main_wizard

    def done(self, wizard):
        pass


wizard_router = NamedURLRouter(MyWizardViewSet)
urlpatterns = wizard_router.urls


# Pretend these are regular Django FormViews.
#
# The important bit is that each step owns its own `get_initial()` logic, so
# you do not end up with one giant `if current_step == ...` block. The wizard
# just provides a way to read the already-completed steps.
#
# For example, imagine `self.wizard.data` contains cleaned data keyed by step
# name:
#
# {
#     "account": {"email": "kevin@example.com", "country": "GB"},
#     "profile": {"display_name": "Kevin"},
# }
#
class WizardStepView:
    step_name = None

    def get_wizard_data(self, step_name):
        return self.wizard.data.get(step_name, {})


class AccountStepView(WizardStepView):
    step_name = "account"
    form_class = FirstForm

    def get_initial(self):
        return {
            "email": self.request.user.email,
            "country": getattr(self.request.user.profile, "country", "GB"),
        }


class ProfileStepView(WizardStepView):
    step_name = "profile"
    form_class = SecondForm

    def get_initial(self):
        account = self.get_wizard_data("account")

        return {
            "display_name": self.request.user.get_full_name(),
            "contact_email": account.get("email"),
            "country": account.get("country"),
        }


class ConfirmStepView(WizardStepView):
    step_name = "confirm"
    form_class = ThirdForm

    def get_initial(self):
        account = self.get_wizard_data("account")
        profile = self.get_wizard_data("profile")

        return {
            "email": account.get("email"),
            "display_name": profile.get("display_name"),
            "country": profile.get("country") or account.get("country"),
        }


FirstFormView = AccountStepView


view_based = Wizard().step(AccountStepView).step(ProfileStepView).step(ConfirmStepView)
