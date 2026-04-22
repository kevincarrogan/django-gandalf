from django import forms
from django.generic.views import FormView


def form_view_factory(form_class):
    form_name = form_class.__name__

    return type(f"{form_name}View", (FormView), {"form_class": form_class})


class Wizard:
    def __init__(self, **configuration):
        self.tree = []

    def step(self, form_class_or_form_view_class):
        if isinstance(form_class_or_form_view_class, forms.Form):
            form_view_class = form_view_factory(form_class_or_form_view_class)

        if not isinstance(form_class_or_form_view_class, FormView):
            raise TypeError("This should be a FormView")
        
        self.tree.append(form_view_class)

        return self
    
    def branch(self, *forms_or_form_views, default=None):
        return self
    

class WizardViewSet:
    # This handles the outside world of the request/response and then splits
    # this out to route to the correct step (which should just be a FormView).
    #
    # This will handle routing to the right view, handle the urls.
    #
    # This is ideally how we would handle the ManagementForm.
    # 
    # __Although how do we inject the ManagentForm in whilst making the child
    # FormViews not care that they're part of this - maybe the view needs to
    # know more context__.
    #
    pass


class NamedURLRouter:
    def __init__(self, *args, **kwargs):
        pass

    @property
    def urls(self):
        return []
    

class FirstForm:
    pass


class SecondForm:
    pass


class ThirdForm:
    pass


class MaybeThisForm:
    pass


class MaybeThatForm:
    pass


class MyFinalForm:
    pass


class AWizardFirstForm:
    pass


class AWizardSecondForm:
    pass


class BWizardFirstForm:
    pass


class BWizardSecondForm:
    pass


class BWizardThirdForm:
    pass


def is_this(wizard):
    pass


def is_that(wizard):
    pass


def condition(cond, flow):
    pass


that_wizard = (
    Wizard()
    .step(BWizardFirstForm)
    .branch(
        condition(is_this, BWizardSecondForm),
        default=BWizardThirdForm,
    )
)


main_wizard = (
    Wizard()  # This will be used for high-level configuration
    .step(FirstForm)  # This could possibly be a view instead (need to work out that concept)
    .step(SecondForm)
    .step(ThirdForm)
    .branch(
        condition(
            is_this,
            Wizard().step(AWizardFirstForm).step(AWizardSecondForm),
        ),
        condition(is_that, that_wizard),
        # If neither condition is met then this would be skipped instead of erroring
    )
    .step(MyFinalForm)
)


class MyWizardViewSet(WizardViewSet):
    wizard = main_wizard

    def done(self, wizard):
        pass


wizard_router = NamedURLRouter(MyWizardViewSet)
urlpatterns = wizard_router.urls


class ManagementFormClass:
    pass


configured = (
    Wizard(management_form_class=ManagementFormClass)
    .step(FirstForm)
    .step(SecondForm)
)


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
