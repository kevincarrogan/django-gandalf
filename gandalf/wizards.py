import logging
from copy import copy
from http import HTTPStatus

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.views.generic.edit import FormView

from gandalf.storage import SessionStorage


logger = logging.getLogger(__name__)


def condition(predicate, target):
    return predicate, target


def form_view_factory(form_class, *, template_name=None):
    form_name = form_class.__name__

    class GeneratedFormView(FormView):
        def get_success_url(self):
            return self.request.path

    GeneratedFormView.form_class = form_class
    GeneratedFormView.template_name = template_name
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView


class Wizard:
    def __init__(self, *, steps=None):
        if steps is None:
            steps = []

        self.steps = list(steps)

    def step(self, form_class_or_form_view_class, context=None):
        return self.__class__(
            steps=[
                *self.steps,
                form_class_or_form_view_class,
            ],
        )

    def branch(self, *conditions, default=None):
        return self.__class__(steps=self.steps)

    def configure(self, **configuration):
        return ConfiguredWizard(
            steps=self.steps,
            configuration=configuration,
        )


class ConfiguredWizard:
    storage_class = SessionStorage

    def __init__(self, *, steps, configuration):
        self.configuration = configuration
        self.steps = self._configure_steps(steps)
        self.storage_class = configuration.get("storage_class", self.storage_class)

    def configure(self, **configuration):
        return self.__class__(
            steps=self.steps,
            configuration={
                **self.configuration,
                **configuration,
            },
        )

    def _configure_steps(self, steps):
        template_name = self.configuration.get("template_name")

        configured_steps = []

        for step in steps:
            if issubclass(step, forms.Form):
                if template_name is None:
                    raise ImproperlyConfigured(
                        "Wizard.configure() must receive template_name when "
                        "generating FormView steps from Form classes."
                    )

                step = form_view_factory(
                    step,
                    template_name=template_name,
                )

            configured_steps.append(step)

        return configured_steps

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

    def submit(self, submission, *args, **kwargs):
        self.storage.set_submissions(
            self.run_id,
            self._build_updated_submissions(
                submission,
                *args,
                **kwargs,
            ),
        )

    def _build_updated_submissions(self, submission, *args, **kwargs):
        updated_submissions = []

        for form_view, stored_submission in zip(
            self.wizard.steps, self.get_submissions()
        ):
            response = self._dispatch_step(
                form_view,
                self._build_step_request("POST", submission=stored_submission),
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

    def replay(self, *args, **kwargs):
        submissions = self.get_submissions()
        for form_view, submission in zip(self.wizard.steps, submissions):
            response = self._dispatch_step(
                form_view,
                self._build_step_request("POST", submission=submission),
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
                *args,
                **kwargs,
            )

        return None

    def _response_satisfies_step(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def _dispatch_step(self, form_view, request, *args, **kwargs):
        step_view = form_view.as_view()
        return step_view(request, *args, **kwargs)

    def _build_step_request(self, method, submission=None):
        request = copy(self.request)
        request.method = method

        if method == "POST":
            request.POST = submission

        return request
