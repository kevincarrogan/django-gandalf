import logging
from copy import copy
from http import HTTPStatus

from gandalf import tree


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

    def get_state(self):
        return self.storage.get_state(self.run_id)

    def get_submissions(self):
        return [entry["step"] for entry in self.get_state()]

    def submit(self, submission, *args, **kwargs):
        self.storage.set_state(
            self.run_id,
            self._build_updated_state(submission, *args, **kwargs),
        )

    def _build_updated_state(self, submission, *args, **kwargs):
        stored_submissions = self.get_submissions()
        path = list(self._resolved_path(stored_submissions))
        updated_state = []

        for index, step in enumerate(path):
            if index >= len(stored_submissions):
                updated_state.append({"step": submission})
                return updated_state

            stored = stored_submissions[index]
            response = self._dispatch_step(
                step,
                self._build_step_request("POST", submission=stored),
                *args,
                **kwargs,
            )

            if self._response_satisfies_step(response):
                updated_state.append({"step": stored})
                continue

            updated_state.append({"step": submission})
            return updated_state

        return updated_state

    def replay(self, *args, **kwargs):
        stored_submissions = self.get_submissions()
        path = list(self._resolved_path(stored_submissions))

        for index, step in enumerate(path):
            if index >= len(stored_submissions):
                return self._dispatch_step(
                    step,
                    self._build_step_request("GET"),
                    *args,
                    **kwargs,
                )

            stored = stored_submissions[index]
            response = self._dispatch_step(
                step,
                self._build_step_request("POST", submission=stored),
                *args,
                **kwargs,
            )

            if not self._response_satisfies_step(response):
                return response

        return None

    def _resolved_path(self, submissions):
        consumed = [0]
        yield from self._iter_resolved(self.wizard.tree, submissions, consumed)

    def _iter_resolved(self, node, submissions, consumed):
        while node is not None:
            if isinstance(node, tree.Step):
                yield node
                consumed[0] += 1
                node = node.next
            else:
                if consumed[0] > len(submissions):
                    return
                arm = self._select_branch_arm(node, submissions[: consumed[0]])
                yield from self._iter_resolved(arm, submissions, consumed)
                node = node.next

    def _select_branch_arm(self, branch_node, submissions):
        request = self._build_step_request("GET")
        request.wizard = _BranchView(submissions)
        for predicate, subtree in branch_node.arms:
            if predicate(request):
                return subtree
        return branch_node.default

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


class _BranchView:
    def __init__(self, submissions):
        self._submissions = submissions

    def get_submissions(self):
        return self._submissions
