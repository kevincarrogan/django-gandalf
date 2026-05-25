import logging
from copy import copy
from http import HTTPStatus

from gandalf import tree
from gandalf.storage import WizardState


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
        return WizardState(self.get_state()).submissions()

    def submit(self, submission, *args, **kwargs):
        self.storage.set_state(
            self.run_id,
            self._build_updated_state(submission, *args, **kwargs),
        )

    def _build_updated_state(self, submission, *args, **kwargs):
        consumed = [False]
        return self._rebuild_at(
            self.wizard.tree,
            self.get_state(),
            submission,
            [],
            consumed,
            *args,
            **kwargs,
        )

    def _rebuild_at(
        self,
        node,
        entries,
        submission,
        submissions,
        consumed,
        *args,
        **kwargs,
    ):
        new_entries = []
        entry_iter = iter(entries)
        while node is not None and not consumed[0]:
            if isinstance(node, tree.Step):
                entry = next(entry_iter, None)
                stored = entry["step"] if entry is not None else None
                if stored is None:
                    new_entries.append({"step": submission})
                    consumed[0] = True
                    return new_entries
                response = self._dispatch_step(
                    node,
                    self._build_step_request("POST", submission=stored),
                    *args,
                    **kwargs,
                )
                if self._response_satisfies_step(response):
                    new_entries.append({"step": stored})
                    submissions.append(stored)
                    node = node.next
                else:
                    new_entries.append({"step": submission})
                    consumed[0] = True
                    return new_entries
            else:
                entry = next(entry_iter, None)
                sub_entries = entry["branch"] if entry is not None else []
                arm = self._select_branch_arm(node, submissions)
                sub_new = self._rebuild_at(
                    arm,
                    sub_entries,
                    submission,
                    submissions,
                    consumed,
                    *args,
                    **kwargs,
                )
                new_entries.append({"branch": sub_new})
                node = node.next
        return new_entries

    def replay(self, *args, **kwargs):
        state = WizardState(self.get_state())
        for step, stored in state.walk(self.wizard.tree, self._select_branch_arm):
            if stored is None:
                return self._dispatch_step(
                    step,
                    self._build_step_request("GET"),
                    *args,
                    **kwargs,
                )
            response = self._dispatch_step(
                step,
                self._build_step_request("POST", submission=stored),
                *args,
                **kwargs,
            )
            if not self._response_satisfies_step(response):
                return response
        return None

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
