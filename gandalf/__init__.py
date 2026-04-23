from django import forms
from django.views import View
from django.views.generic.edit import FormView


class Wizard:
    def __init__(self):
        self.steps = []

    def step(self, form_or_view):
        self.steps.append(form_or_view)
        return self


class GandalfManagementForm(forms.Form):
    current_step = forms.CharField(widget=forms.HiddenInput())


class DefaultFormViewFactory:
    def create(self, form_class, template_name=None):
        class GeneratedFormView(FormView):
            pass

        GeneratedFormView.form_class = form_class

        if template_name:
            GeneratedFormView.template_name = template_name

        return GeneratedFormView


class WizardViewSet(View):
    wizard = None
    template_name = None
    form_view_factory_class = DefaultFormViewFactory

    def get_wizard(self):
        return self.wizard

    def get_template_name(self):
        return self.template_name

    def get_form_view_factory(self):
        return self.form_view_factory_class()

    def get_current_step_view_class(self):
        wizard = self.get_wizard()
        if wizard is None or not wizard.steps:
            raise ValueError("Wizard must define at least one step")

        step = wizard.steps[0]
        if isinstance(step, type) and issubclass(step, forms.BaseForm):
            return self.get_form_view_factory().create(
                form_class=step,
                template_name=self.get_template_name(),
            )
        return step

    def dispatch(self, request, *args, **kwargs):
        request.gandalf_management_form = GandalfManagementForm(
            initial={"current_step": "0"},
        )
        step_view_class = self.get_current_step_view_class()
        return step_view_class.as_view()(request, *args, **kwargs)
