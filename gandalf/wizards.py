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

    def __init__(self):
        self.steps = []
        self.start = None

    def step(self, form_class_or_form_view_class, context=None):
        if issubclass(form_class_or_form_view_class, forms.Form):  # pragma: no branch
            form_class = form_class_or_form_view_class
            form_view = form_view_factory(form_class)
            self.steps.append(form_view)
            self.start = self.steps[0]

        return self

    def configure(self, **configuration):
        return ConfiguredWizard(
            steps=self.steps,
            start=self.start,
            configuration=configuration,
        )


class ConfiguredWizard:
    tree = None

    def __init__(self, *, steps, start, configuration):
        self.steps = steps
        self.start = start
        self.configuration = configuration

    def initialise(self, request):
        bound_wizard = BoundWizard(self, request)
        bound_wizard.initialise()
        return bound_wizard

    def bind(self, request, run_id):
        bound_wizard = BoundWizard(self, request)
        bound_wizard.retrieve(run_id)
        return bound_wizard


class BoundWizard:
    SESSION_KEY = "gandalf_runs"
    NO_SUBMISSION = object()

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

    def get_submissions(self):
        run_data = self.get_run_data()
        return run_data.get("submissions", [])

    def submit(self, submission, template_name, *args, **kwargs):
        run_data = self.get_run_data()
        run_data["submissions"] = self._build_updated_submissions(
            submission,
            template_name,
            *args,
            **kwargs,
        )
        self.request.session.modified = True

    def _build_updated_submissions(self, submission, template_name, *args, **kwargs):
        updated_submissions = []
        stored_submissions = iter(self.get_submissions())

        for form_view in self.wizard.steps:
            stored_submission = next(stored_submissions, self.NO_SUBMISSION)
            if stored_submission is self.NO_SUBMISSION:
                updated_submissions.append(submission)
                return updated_submissions

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

        return updated_submissions

    def replay(self, template_name, *args, **kwargs):
        stored_submissions = iter(self.get_submissions())

        for form_view in self.wizard.steps:
            submission = next(stored_submissions, self.NO_SUBMISSION)

            if submission is self.NO_SUBMISSION:
                return self._dispatch_step(
                    form_view,
                    self._build_step_request("GET"),
                    template_name,
                    *args,
                    **kwargs,
                )

            response = self._dispatch_step(
                form_view,
                self._build_step_request("POST", submission=submission),
                template_name,
                *args,
                **kwargs,
            )

            if not self._response_satisfies_step(response):
                return response

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
