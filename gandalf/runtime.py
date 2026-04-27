import logging
from copy import copy
from http import HTTPStatus


logger = logging.getLogger(__name__)


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

        for step, stored_submission in zip(self.wizard.steps, self.get_submissions()):
            response = self._dispatch_step(
                step,
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
        for step, submission in zip(self.wizard.steps, submissions):
            response = self._dispatch_step(
                step,
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

    def _dispatch_step(self, step, request, *args, **kwargs):
        step_view = step.form_view.as_view()
        return step_view(request, *args, **kwargs)

    def _build_step_request(self, method, submission=None):
        request = copy(self.request)
        request.method = method

        if method == "POST":
            request.POST = submission

        return request
