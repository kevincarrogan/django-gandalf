import logging
from copy import copy
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from gandalf import tree
from gandalf.storage import WizardState


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Cursor:
    """Position in the wizard where the user currently is — the first step
    whose stored data does not satisfy the step (no data, or invalid data).

    `node` is None when every stored submission validates and there is no
    next step. `response` carries the rendered form when stored data was
    invalid; otherwise the cursor is at an empty slot ready for a GET render.
    `state` is the tree-shaped state with a pending submission (if any)
    already placed at the cursor's slot.
    """

    node: tree.Step | None
    state: list
    response: Any = None


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
        cursor = self._find_cursor(submission, *args, **kwargs)
        self.storage.set_state(self.run_id, cursor.state)

    def replay(self, *args, **kwargs):
        cursor = self._find_cursor(None, *args, **kwargs)
        if cursor.node is None:
            return None
        if cursor.response is not None:
            return cursor.response
        return self._dispatch_step(
            cursor.node,
            self._build_step_request("GET"),
            *args,
            **kwargs,
        )

    def _find_cursor(self, pending_submission, *args, **kwargs):
        state, cursor_node, response = self._walk_for_cursor(
            self.wizard.tree,
            self.get_state(),
            pending_submission,
            *args,
            **kwargs,
        )
        return Cursor(node=cursor_node, state=state, response=response)

    def _walk_for_cursor(
        self,
        node,
        entries,
        pending_submission,
        *args,
        **kwargs,
    ):
        new_entries = []
        entry_iter = iter(entries)
        while node is not None:
            if isinstance(node, tree.Step):
                entry = next(entry_iter, None)
                stored = entry["step"] if entry is not None else None
                if stored is None:
                    if pending_submission is not None:
                        new_entries.append({"step": pending_submission})
                    return new_entries, node, None
                response = self._dispatch_step(
                    node,
                    self._build_step_request("POST", submission=stored),
                    *args,
                    **kwargs,
                )
                if not self._response_satisfies_step(response):
                    if pending_submission is not None:
                        new_entries.append({"step": pending_submission})
                    return new_entries, node, response
                new_entries.append({"step": stored})
                node = node.next
            else:
                entry = next(entry_iter, None)
                sub_entries = entry["branch"] if entry is not None else []
                arm = self._select_branch_arm(node)
                sub_new, sub_cursor, sub_response = self._walk_for_cursor(
                    arm,
                    sub_entries,
                    pending_submission,
                    *args,
                    **kwargs,
                )
                new_entries.append({"branch": sub_new})
                if sub_cursor is not None:
                    return new_entries, sub_cursor, sub_response
                node = node.next
        return new_entries, None, None

    def _select_branch_arm(self, branch_node):
        request = self._build_step_request("GET")
        request.wizard = self
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
