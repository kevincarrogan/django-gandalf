import logging
from copy import copy
from dataclasses import dataclass, replace
from http import HTTPStatus
from typing import Any

from django import forms

from gandalf import tree


logger = logging.getLogger(__name__)


@dataclass
class RuntimeStep:
    """Runtime mirror of a declared `tree.Step`, carrying per-request state."""

    declaration: tree.Step
    data: dict | None = None
    next: "RuntimeStep | RuntimeBranch | None" = None

    @property
    def form(self):
        form_class = self.declaration.declaration
        if not issubclass(form_class, forms.Form):
            raise NotImplementedError(
                "RuntimeStep.form is currently only defined for steps "
                "declared with a plain forms.Form subclass."
            )
        form = form_class(self.data)
        form.is_valid()
        return form

    def matches_context(self, **context):
        return self.declaration.matches_context(**context)

    def accept_visit(self, visitor):
        visitor.visit_step(self)

    def accept_reduce(self, reducer):
        return reducer.visit_step(self)

    def accept_transform(self, transformer):
        next_result = transformer.transform(self.next)
        return transformer.visit_step(self, next_result)


@dataclass
class RuntimeBranch:
    """Runtime mirror of a declared `tree.Branch` along the active path —
    records the selected arm only. Inactive arms are not mirrored in the
    runtime tree; inspect `bound_wizard.wizard.tree` for the full declared
    structure.
    """

    declaration: tree.Branch
    selected_arm: "RuntimeStep | RuntimeBranch | None" = None
    next: "RuntimeStep | RuntimeBranch | None" = None

    def accept_visit(self, visitor):
        visitor.visit_branch(self)
        visitor.visit(self.selected_arm)

    def accept_reduce(self, reducer):
        sub_result = reducer.reduce(self.selected_arm)
        return reducer.visit_branch(self, sub_result)

    def accept_transform(self, transformer):
        transformed_selected_arm = transformer.transform(self.selected_arm)
        next_result = transformer.transform(self.next)
        return transformer.visit_branch(
            self, transformed_selected_arm, next_result
        )


@dataclass(frozen=True)
class Cursor:
    """Position in the wizard where the user currently is — the first step
    whose stored data does not satisfy the step (no data, or invalid data).

    `node` is None when every stored submission validates and there is no
    next step. `response` carries the rendered form when stored data was
    invalid; otherwise the cursor is at an empty slot ready for a GET render.
    `state` is the runtime tree built up to (and including) the cursor, with
    a pending submission already placed at the cursor's slot.
    """

    node: tree.Step | None
    state: RuntimeStep | RuntimeBranch | None
    response: Any = None


class BoundWizard:
    def __init__(self, request, storage, wizard=None):
        self.wizard = wizard
        self.request = request
        self.storage = storage
        self.run_id = None
        self._predicate_runtime_tree = None

    def bind(self, wizard):
        self.wizard = wizard

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

    @property
    def runtime_tree(self):
        builder = self.wizard.runtime_tree_builder_class(self, self.get_state())
        builder.walk(self.wizard.tree)
        return builder.head

    @property
    def path(self):
        return PathFlattener().transform(self.runtime_tree)

    def _current_runtime_tree(self):
        if self._predicate_runtime_tree is not None:
            return self._predicate_runtime_tree
        return self.runtime_tree

    def find_step(self, **context):
        finder = tree.ContextFinder(context)
        finder.visit(self._current_runtime_tree())
        return finder.one()

    def filter_steps(self, **context):
        finder = tree.ContextFinder(context)
        finder.visit(self._current_runtime_tree())
        return finder.all()

    def submit(self, submission, *args, **kwargs):
        walker = self.wizard.cursor_walker_class(
            self, self.get_state(), submission, args, kwargs
        )
        walker.walk(self.wizard.tree)
        serializer = self.wizard.state_serializer_class()
        entries = serializer.reduce(walker.cursor().state)
        self.storage.set_state(self.run_id, entries)

    def replay(self, *args, **kwargs):
        walker = self.wizard.cursor_walker_class(
            self, self.get_state(), None, args, kwargs
        )
        walker.walk(self.wizard.tree)
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

    def _select_branch_arm(self, branch_node, partial_runtime_head=None):
        request = self._build_step_request("GET")
        request.wizard = self
        self._predicate_runtime_tree = partial_runtime_head
        try:
            for predicate, subtree in branch_node.arms:
                if predicate(request):
                    return subtree
            return branch_node.default
        finally:
            self._predicate_runtime_tree = None

    def _response_satisfies_step(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def _dispatch_step(self, step, request, *args, **kwargs):
        request.wizard = self
        step_view = step.form_view.as_view()
        return step_view(request, *args, **kwargs)

    def _build_step_request(self, method, submission=None):
        request = copy(self.request)
        request.method = method

        if method == "POST":
            request.POST = submission

        return request


class CursorWalker(tree.Interpreter):
    """Interpreter that locates the wizard cursor and builds the runtime tree
    up to that point. Validates stored entries by dispatching POSTs; when
    given a pending submission, places it at the cursor's slot."""

    def __init__(self, bound_wizard, entries, pending_submission, args, kwargs):
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self._pending_submission = pending_submission
        self._args = args
        self._kwargs = kwargs
        self._head: RuntimeStep | RuntimeBranch | None = None
        self._tail: RuntimeStep | RuntimeBranch | None = None
        self._cursor = None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        stored = entry["step"] if entry is not None else None
        if stored is None:
            self._place_pending(step)
            self._cursor = Cursor(node=step, state=self._head)
            return False
        response = self._bound_wizard._dispatch_step(
            step,
            self._bound_wizard._build_step_request("POST", submission=stored),
            *self._args,
            **self._kwargs,
        )
        if not self._bound_wizard._response_satisfies_step(response):
            self._place_pending(step)
            self._cursor = Cursor(node=step, state=self._head, response=response)
            return False
        self._append(RuntimeStep(declaration=step, data=stored))
        return True

    def visit_branch(self, branch):
        entry = next(self._entries_iter, None)
        sub_entries = entry["branch"] if entry is not None else []
        arm = self._bound_wizard._select_branch_arm(branch, self._head)
        sub = type(self)(
            self._bound_wizard,
            sub_entries,
            self._pending_submission,
            self._args,
            self._kwargs,
        )
        sub.walk(arm)
        self._append(RuntimeBranch(declaration=branch, selected_arm=sub._head))
        if sub._cursor is not None:
            self._cursor = Cursor(
                node=sub._cursor.node,
                state=self._head,
                response=sub._cursor.response,
            )
            return False
        return True

    def cursor(self):
        if self._cursor is not None:
            return self._cursor
        return Cursor(node=None, state=self._head)

    def _place_pending(self, step):
        if self._pending_submission is not None:
            self._append(RuntimeStep(declaration=step, data=self._pending_submission))

    def _append(self, node):
        if self._head is None:
            self._head = node
        else:
            self._tail.next = node
        self._tail = node


class StateSerializer(tree.Reducer):
    """Bottom-up reducer that flattens a runtime tree into the dict-shaped
    state stored in `request.session`."""

    def visit_step(self, runtime_step):
        return {"step": runtime_step.data}

    def visit_branch(self, runtime_branch, sub_result):
        return {"branch": sub_result}


class PathFlattener(tree.Transformer):
    """Transformer that turns a runtime tree into a linked chain of
    completed RuntimeStep nodes (the active route). Steps whose `data`
    is None are dropped; branches are spliced by inlining the
    transformed selected arm before the branch's next."""

    def visit_step(self, runtime_step, next_result):
        if runtime_step.data is None:
            return next_result
        return replace(runtime_step, next=next_result)

    def visit_branch(self, runtime_branch, transformed_selected_arm, next_result):
        if transformed_selected_arm is None:
            return next_result
        tail = transformed_selected_arm
        while tail.next is not None:
            tail = tail.next
        tail.next = next_result
        return transformed_selected_arm


class MergeCleanedData(tree.Reducer):
    """Reducer that folds completed step cleaned_data into a single dict
    using last-write-wins on key collisions.

    Intended for `bound_wizard.path` but also works on
    `bound_wizard.runtime_tree`; for each `RuntimeStep` it contributes
    `step.form.cleaned_data`, and any branch sub-fold is merged into the
    accumulator. Subclass and override `combine`, `visit_step`, or
    `visit_branch` for a different merge policy.
    """

    def initial(self):
        return {}

    def combine(self, accumulator, value):
        return {**accumulator, **value}

    def visit_step(self, runtime_step):
        return runtime_step.form.cleaned_data

    def visit_branch(self, runtime_branch, sub_result):
        return sub_result


class RuntimeTreeBuilder(tree.Interpreter):
    """Builds a runtime tree mirroring the declaration tree, applying stored
    state data to runtime steps along the active path. All arms of every
    branch are mirrored (without state) so the runtime tree preserves the
    full declared structure for introspection."""

    def __init__(self, bound_wizard, entries):
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self.head: RuntimeStep | RuntimeBranch | None = None
        self._tail: RuntimeStep | RuntimeBranch | None = None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        data = entry["step"] if entry is not None else None
        self._append(RuntimeStep(declaration=step, data=data))

    def visit_branch(self, branch):
        entry = next(self._entries_iter, None)
        sub_entries = entry["branch"] if entry is not None else []
        selected_decl = self._bound_wizard._select_branch_arm(branch, self.head)

        sub_builder = type(self)(self._bound_wizard, sub_entries)
        sub_builder.walk(selected_decl)

        self._append(
            RuntimeBranch(
                declaration=branch,
                selected_arm=sub_builder.head,
            )
        )

    def _append(self, node):
        if self.head is None:
            self.head = node
        else:
            self._tail.next = node
        self._tail = node
