from django.generic.views import FormView


def form_view_factory(form_class):
    form_name = form_class.__name__

    class GeneratedFormView(FormView):
        pass

    GeneratedFormView.form_class = form_class
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__
    return GeneratedFormView


class StepDefinition:
    def __init__(self, form_view_class, context=None):
        self.form_view_class = form_view_class
        self.context = context or {}


class Wizard:
    def __init__(self, **configuration):
        self.tree = []

    def step(self, form_class_or_form_view_class, context=None):
        if hasattr(form_class_or_form_view_class, "form_class"):
            form_view_class = form_class_or_form_view_class
        else:
            form_view_class = form_view_factory(form_class_or_form_view_class)

        if not isinstance(form_view_class, type):
            raise TypeError("This should be a FormView")

        self.tree.append(StepDefinition(form_view_class, context=context))

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
    # __Although how do we inject the ManagentForm in whilst making the child
    # FormViews not care that they're part of this - maybe the view needs to
    # know more context__.
    #
    wizard = None

    def get_wizard(self):
        """
        Return the wizard for this request.

        The default implementation returns the class-level `wizard`, but this
        can be overridden to build a wizard dynamically from request context.
        """
        return self.wizard


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


def is_this(request):
    pass


def is_that(request):
    pass


def condition(cond, flow):
    pass


that_wizard = (
    Wizard()
    .step(BWizardFirstForm, context={"step_name": "b_wizard_first"})
    .branch(
        condition(is_this, BWizardSecondForm),
        default=BWizardThirdForm,
    )
)


main_wizard = (
    Wizard()  # This will be used for high-level configuration
    .step(
        FirstForm,
        context={"step_name": "first"},
    )  # This could possibly be a view instead (need to work out that concept)
    .step(SecondForm, context={"step_name": "second"})
    .step(ThirdForm, context={"step_name": "third"})
    .branch(
        condition(
            is_this,
            Wizard()
            .step(AWizardFirstForm, context={"step_name": "a_wizard_first"})
            .step(AWizardSecondForm, context={"step_name": "a_wizard_second"}),
        ),
        condition(is_that, that_wizard),
        # If neither condition is met then this would be skipped instead of erroring
    )
    .step(MyFinalForm, context={"step_name": "final"})
)


class MyWizardViewSet(WizardViewSet):
    wizard = main_wizard

    def done(self, wizard):
        pass


class DynamicWizardViewSet(WizardViewSet):
    def get_wizard(self):
        wizard = Wizard().step(FirstForm, context={"step_name": "first"})

        if getattr(self.request.user, "is_staff", False):
            wizard = wizard.step(SecondForm, context={"step_name": "second"})
        else:
            wizard = wizard.step(ThirdForm, context={"step_name": "third"})

        return wizard.step(MyFinalForm, context={"step_name": "final"})

    def done(self, wizard):
        pass


wizard_router = NamedURLRouter(MyWizardViewSet)
urlpatterns = wizard_router.urls


class ManagementFormClass:
    pass


configured = (
    Wizard(management_form_class=ManagementFormClass)
    .step(FirstForm, context={"step_name": "first"})
    .step(SecondForm, context={"step_name": "second"})
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
    .step(FirstFormView, context={"step_name": "first"})
    .step(
        SecondForm,
        context={"step_name": "second"},
    )  # Under the hood this is just automatically generating the FormView for us, but each step _is_ a FormView (or something that matches that contract)
)
