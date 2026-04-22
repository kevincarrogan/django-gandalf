from .core import NamedURLRouter, Wizard, WizardViewSet
from .wizards import main_wizard
from .forms import FirstForm, SecondForm


class MyWizardViewSet(WizardViewSet):
    wizard = main_wizard

    def done(self, wizard):
        pass


wizard_router = NamedURLRouter(MyWizardViewSet)
urlpatterns = wizard_router.urls


# Pretend this is:
# from django.views.generic import FormView
# class FirstFormView(FormView):
#
# Ideally this just follows the same pattern as any other FormView and can
# easily be re-used as a FormView in its own right.
#
# This does mean that we have to handle more configuration outside of the
# FormView to achieve that, but we can handle that in the Wizard declaration.
#
# From an abstraction perspective, these FormViews shouldn't know they exist
# in a wizard context at all (how leaky that is remains to be seen).
#
# django-formtools instead viewed the Django Form as the thing to compose
# in django-gandalf the FormView is instead the thing we compose.
#
class FirstFormView:
    form_class = FirstForm

    def get_initial(self):
        return {
            "a_different_thing": "A different thing",
        }


view_based = (
    Wizard()
    .step(FirstFormView)
    .step(SecondForm)  # Under the hood this is just automatically generating the FormView for us, but each step _is_ a FormView (or something that matches that contract)
)
