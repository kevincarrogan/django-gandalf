import logging
from copy import copy
from http import HTTPStatus
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
    NO_STEP_DATA = object()

    def __init__(self, wizard, request):
        self.wizard = wizard
        self.request = request
        self.run_id = None

    def initialise(self):
        self.run_id = str(uuid.uuid4())
        logger.debug("Initialise BoundWizard: %s", self.run_id)

        gandalf_runs = self.request.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[self.run_id] = {}
        logger.debug("Initialised data: %s", gandalf_runs)

        self.request.session.modified = True

    def retrieve(self, run_id):
        self.run_id = run_id
        logger.debug("Retrieving BoundWizard: %s", self.run_id)
        gandalf_runs = self.request.session[self.SESSION_KEY]
        logger.debug("Retrieved data: %s", gandalf_runs)

        self.request.session.modified = True

    def get_run_data(self):
        gandalf_runs = self.request.session[self.SESSION_KEY]
        return gandalf_runs[str(self.run_id)]

    def get_step_data(self):
        run_data = self.get_run_data()
        return run_data.get("step_data", [])

    def save_current_step_data(self, data, template_name, *args, **kwargs):
        run_data = self.get_run_data()
        run_data["step_data"] = self.build_updated_step_data(
            data,
            template_name,
            *args,
            **kwargs,
        )
        self.request.session.modified = True

    def build_updated_step_data(self, data, template_name, *args, **kwargs):
        updated_step_data = []
        stored_step_data = iter(self.get_step_data())

        for form_view in self.wizard.steps:
            stored_data = next(stored_step_data, self.NO_STEP_DATA)
            if stored_data is self.NO_STEP_DATA:
                updated_step_data.append(data)
                return updated_step_data

            response = self.dispatch_form_view(
                form_view,
                self.build_step_request("POST", data=stored_data),
                template_name,
                *args,
                **kwargs,
            )

            if self.is_step_response_successful(response):
                updated_step_data.append(stored_data)
                continue

            updated_step_data.append(data)
            return updated_step_data

        return updated_step_data

    def dispatch_next_incomplete_step(self, template_name, *args, **kwargs):
        stored_step_data = iter(self.get_step_data())

        for form_view in self.wizard.steps:
            data = next(stored_step_data, self.NO_STEP_DATA)

            if data is self.NO_STEP_DATA:
                return self.dispatch_form_view(
                    form_view,
                    self.build_step_request("GET"),
                    template_name,
                    *args,
                    **kwargs,
                )

            response = self.dispatch_form_view(
                form_view,
                self.build_step_request("POST", data=data),
                template_name,
                *args,
                **kwargs,
            )

            if not self.is_step_response_successful(response):
                return response

        return None

    def is_step_response_successful(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def dispatch_form_view(self, form_view, request, template_name, *args, **kwargs):
        step_view = form_view.as_view(
            template_name=template_name,
        )
        return step_view(request, *args, **kwargs)

    def build_step_request(self, method, data=None):
        request = copy(self.request)
        request.method = method

        if method == "POST":
            request.POST = data

        return request
