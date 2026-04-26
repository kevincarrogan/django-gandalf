import uuid

from django import forms
from django.views.generic.edit import FormView

from .forms import ManagementForm


def form_view_factory(form_class):
    form_name = form_class.__name__

    class GeneratedFormView(FormView):
        pass

    GeneratedFormView.form_class = form_class
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView


class Wizard:
    tree = None

    def __init__(self, **configuration):
        self.configuration = configuration
        self.steps = []
        self.start = None

    def bind(self, request):
        return BoundWizard(self, request=request)

    def get_current_form_view(self):
        return self.steps[0]

    def step(self, form_class_or_form_view_class, context=None):
        if issubclass(form_class_or_form_view_class, forms.Form):  # pragma: no branch
            form_class = form_class_or_form_view_class
            form_view = form_view_factory(form_class)
            self.steps.append(form_view)
            self.start = self.steps[0]

        return self


class BoundWizard:
    MANAGEMENT_FORM_RUN_ID_FIELD_NAME = "run_id"
    SESSION_KEY = "gandalf_runs"

    def __init__(self, wizard, request):
        self.wizard = wizard
        self.request = request
        self.run_id = self.get_run_id()
        self.current_step_index = self.get_session_state().get("current_step_index", 0)

    def get_run_id(self):
        management_form = self.get_bound_management_form()

        if management_form.is_valid():
            return management_form.cleaned_data[self.MANAGEMENT_FORM_RUN_ID_FIELD_NAME]

        return str(uuid.uuid4())

    def get_bound_management_form(self):
        data = self.request.POST or self.request.GET or None
        return ManagementForm(data=data)

    def get_management_form(self):
        return ManagementForm(
            initial={self.MANAGEMENT_FORM_RUN_ID_FIELD_NAME: self.run_id},
        )

    def get_session_state(self):
        return self.request.session.get(self.SESSION_KEY, {}).get(self.run_id, {})

    def get_current_form_view(self):
        return self.wizard.steps[self.current_step_index]

    def complete_current_step(self):
        self.current_step_index += 1
        gandalf_runs = self.request.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[self.run_id] = {
            "current_step_index": self.current_step_index,
        }
        if hasattr(self.request.session, "modified"):
            self.request.session.modified = True
