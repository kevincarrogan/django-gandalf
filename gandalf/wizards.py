import logging
import uuid

from django import forms
from django.views.generic.edit import FormView


logger = logging.getLogger(__name__)


def form_view_factory(form_class):
    form_name = form_class.__name__

    class GeneratedFormView(FormView):
        def get_success_url(self):
            return self.request.path

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

    def initialise(self, request):
        bound_wizard = BoundWizard(self, request)
        bound_wizard.initialise()
        return bound_wizard

    def bind(self, request, run_id):
        bound_wizard = BoundWizard(self, request)
        bound_wizard.retrieve(run_id)
        return bound_wizard

    def step(self, form_class_or_form_view_class, context=None):
        if issubclass(form_class_or_form_view_class, forms.Form):  # pragma: no branch
            form_class = form_class_or_form_view_class
            form_view = form_view_factory(form_class)
            self.steps.append(form_view)
            self.start = self.steps[0]

        return self


class BoundWizard:
    SESSION_KEY = "gandalf_runs"

    def __init__(self, wizard, request):
        self.wizard = wizard
        self.request = request
        self.run_id = None

    def initialise(self):
        self.run_id = str(uuid.uuid4())
        logger.debug("Initialise BoundWizard: %s", self.run_id)

        gandalf_runs = self.request.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[self.run_id] = {
            "current_step_index": 0,
        }
        logger.debug("Initialised data: %s", gandalf_runs)

        self.request.session.modified = True

    def retrieve(self, run_id):
        self.run_id = run_id
        logger.debug("Retrieving BoundWizard: %s", self.run_id)
        gandalf_runs = self.request.session[self.SESSION_KEY]
        logger.debug("Retrieved data: %s", gandalf_runs)
        run_data = gandalf_runs[str(self.run_id)]
        self.current_step_index = run_data["current_step_index"]

        self.request.session.modified = True

    def get_current_form_view(self):
        return self.wizard.steps[self.current_step_index]

    def complete_current_step(self):
        self.current_step_index += 1
        gandalf_runs = self.request.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[str(self.run_id)] = {
            "current_step_index": self.current_step_index,
        }
        self.request.session.modified = True
