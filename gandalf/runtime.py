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

    def find_step(self, **context):
        finder = tree.ContextFinder(context)
        tree.walk(self.wizard.tree, finder)
        return finder.one()

    def filter_steps(self, **context):
        finder = tree.ContextFinder(context)
        tree.walk(self.wizard.tree, finder)
        return finder.all()

    def submit(self, submission, *args, **kwargs):
        walker = _CursorWalker(self, self.get_state(), submission, args, kwargs)
        tree.walk(self.wizard.tree, walker)
        self.storage.set_state(self.run_id, walker.cursor().state)

    def replay(self, *args, **kwargs):
        walker = _CursorWalker(self, self.get_state(), None, args, kwargs)
        tree.walk(self.wizard.tree, walker)
        cursor = walker.cursor()
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


class _CursorWalker:
    """Tree visitor that locates the wizard cursor and builds the tree-shaped
    state up to that point. Validates stored entries by dispatching POSTs;
    when given a pending submission, places it at the cursor's slot."""

    def __init__(self, bound_wizard, entries, pending_submission, args, kwargs):
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self._pending_submission = pending_submission
        self._args = args
        self._kwargs = kwargs
        self.state = []
        self._cursor = None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        stored = entry["step"] if entry is not None else None
        if stored is None:
            self._place_pending()
            self._cursor = Cursor(node=step, state=self.state)
            return False
        response = self._bound_wizard._dispatch_step(
            step,
            self._bound_wizard._build_step_request("POST", submission=stored),
            *self._args,
            **self._kwargs,
        )
        if not self._bound_wizard._response_satisfies_step(response):
            self._place_pending()
            self._cursor = Cursor(node=step, state=self.state, response=response)
            return False
        self.state.append({"step": stored})
        return True

    def visit_branch(self, branch):
        entry = next(self._entries_iter, None)
        sub_entries = entry["branch"] if entry is not None else []
        arm = self._bound_wizard._select_branch_arm(branch)
        sub = _CursorWalker(
            self._bound_wizard,
            sub_entries,
            self._pending_submission,
            self._args,
            self._kwargs,
        )
        tree.walk(arm, sub)
        self.state.append({"branch": sub.state})
        if sub._cursor is not None:
            self._cursor = Cursor(
                node=sub._cursor.node,
                state=self.state,
                response=sub._cursor.response,
            )
            return False
        return True

    def cursor(self):
        if self._cursor is not None:
            return self._cursor
        return Cursor(node=None, state=self.state)

    def _place_pending(self):
        if self._pending_submission is not None:
            self.state.append({"step": self._pending_submission})
