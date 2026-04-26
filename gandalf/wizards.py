import logging
from copy import copy
from http import HTTPStatus

from django import forms
from django.views.generic.edit import FormView

from gandalf.storage import SessionStorage


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

    def __init__(self):
        self.steps = []

    def step(self, form_class_or_form_view_class, context=None):
        if issubclass(form_class_or_form_view_class, forms.Form):  # pragma: no branch
            form_class = form_class_or_form_view_class
            form_view = form_view_factory(form_class)
            self.steps.append(form_view)

        return self

    def configure(self, **configuration):
        return ConfiguredWizard(
            steps=self.steps,
            configuration=configuration,
        )


class ConfiguredWizard:
    storage_class = SessionStorage
    tree = None

    def __init__(self, *, steps, configuration):
        self.steps = steps
        self.configuration = configuration
        self.storage_class = configuration.get("storage_class", self.storage_class)

    def get_bound_wizard(self, request):
        return BoundWizard(self, request, self.storage_class(request))

class BoundWizard:
    def __init__(self, wizard, request, storage):
        self.wizard = wizard
        self.request = request
        self.storage = storage
        self.run_id = None

    def initialise(self):
        self.run_id = self.storage.initialise_run()
        logger.debug("Initialise BoundWizard: %s", self.run_id)

    def retrieve(self, run_id):
        self.run_id = self.storage.retrieve_run(run_id)
        logger.debug("Retrieving BoundWizard: %s", self.run_id)

    def get_run_data(self):
        return self.storage.get_run_data(self.run_id)

    def get_submissions(self):
        return self.storage.get_submissions(self.run_id)

    def submit(self, submission, template_name, *args, **kwargs):
        self.storage.set_submissions(
            self.run_id,
            self._build_updated_submissions(
                submission,
                template_name,
                *args,
                **kwargs,
            ),
        )

    def _build_updated_submissions(self, submission, template_name, *args, **kwargs):
        updated_submissions = []

        for form_view, stored_submission in zip(
            self.wizard.steps, self.get_submissions()
        ):
            response = self._dispatch_step(
                form_view,
                self._build_step_request("POST", submission=stored_submission),
                template_name,
                *args,
                **kwargs,
            )

            if self._response_satisfies_step(response):
                updated_submissions.append(stored_submission)
                continue

            updated_submissions.append(submission)
            return updated_submissions

        if len(updated_submissions) < len(self.wizard.steps):
            updated_submissions.append(submission)

        return updated_submissions

    def replay(self, template_name, *args, **kwargs):
        submissions = self.get_submissions()
        for form_view, submission in zip(self.wizard.steps, submissions):
            response = self._dispatch_step(
                form_view,
                self._build_step_request("POST", submission=submission),
                template_name,
                *args,
                **kwargs,
            )

            if not self._response_satisfies_step(response):
                return response

        remaining_steps = self.wizard.steps[len(submissions) :]
        if remaining_steps:
            return self._dispatch_step(
                remaining_steps[0],
                self._build_step_request("GET"),
                template_name,
                *args,
                **kwargs,
            )

        return None

    def _response_satisfies_step(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def _dispatch_step(self, form_view, request, template_name, *args, **kwargs):
        step_view = form_view.as_view(
            template_name=template_name,
        )
        return step_view(request, *args, **kwargs)

    def _build_step_request(self, method, submission=None):
        request = copy(self.request)
        request.method = method

        if method == "POST":
            request.POST = submission

        return request
