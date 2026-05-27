import logging
from copy import copy
from dataclasses import dataclass, field as dataclass_field, replace
from http import HTTPStatus
from typing import Any

from django.utils.datastructures import MultiValueDict

from gandalf import tree


logger = logging.getLogger(__name__)


class StepNotFound(LookupError):
    """Raised when a context-based edit targets a step that is not on the
    active runtime path or has no stored submission."""


def _open_file_refs(bound_wizard, file_refs):
    if not file_refs:
        return None
    return MultiValueDict(
        {
            field_name: [bound_wizard.file_storage.open(ref)]
            for field_name, ref in file_refs.items()
        }
    )


@dataclass
class RuntimeStep:
    """Runtime mirror of a declared `tree.Step`, carrying per-request state."""

    declaration: tree.Step
    data: dict | None = None
    files: dict | None = None
    next: "RuntimeStep | RuntimeBranch | None" = None
    bound_wizard: "BoundWizard | None" = dataclass_field(
        default=None, repr=False, compare=False
    )

    @property
    def form(self):
        """Reconstruct a bound, validated form for this step.

        Drives the step's `FormView` through its public composition API:
        instantiates the view, calls `view.setup()` with a synthetic POST
        request carrying the stored submission, then returns `view.get_form()`
        after calling `is_valid()` to populate `cleaned_data`. This honors
        `form_class`, `get_form_class()`, `get_form_kwargs()`, `get_initial()`,
        and `get_prefix()` overrides on the user's FormView.

        Note: the synthetic request is built from `bound_wizard.request` — the
        *current* request, not the request that originally submitted the step.
        For typical single-user flows they're equivalent; for flows where one
        user edits another's run, `request.user` reflects the editor.

        Customizations beyond composition (overrides of `form_valid()`,
        `post()`, `dispatch()`, or `setup()`) are not surfaced here — `.form`
        does not run the FormView's dispatch pipeline.
        """
        form_view_class = self.declaration.form_view
        request = self.bound_wizard.dispatcher.build_request(
            "POST",
            submission=self.data or {},
            files=_open_file_refs(self.bound_wizard, self.files),
        )
        view = form_view_class()
        view.setup(request)
        form = view.get_form()
        form.is_valid()
        return form

    def matches_context(self, **context):
        return self.declaration.matches_context(**context)

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

    def accept_reduce(self, reducer):
        sub_result = reducer.reduce(self.selected_arm)
        return reducer.visit_branch(self, sub_result)

    def accept_transform(self, transformer):
        transformed_arm = transformer.transform(self.selected_arm)
        next_result = transformer.transform(self.next)
        return transformer.visit_branch(self, transformed_arm, next_result)


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


class StepDispatcher:
    """HTTP adapter: builds request snapshots, dispatches step form views,
    decides whether a step's response represents a valid submission, and
    renders a cursor as an HTTP response.
    """

    def __init__(self, bound_wizard):
        self._bound_wizard = bound_wizard

    def dispatch(self, step, request, *args, initial=None, **kwargs):
        view_kwargs = {} if initial is None else {"initial": initial}
        step_view = step.form_view.as_view(**view_kwargs)
        return step_view(request, *args, **kwargs)

    def build_request(self, method, submission=None, files=None):
        request = copy(self._bound_wizard.request)
        request.method = method
        request.wizard = self._bound_wizard
        if method == "POST":
            request.POST = submission
            if files is not None:
                request._files = files
        return request

    def response_satisfies_step(self, response):
        return (
            HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST
        )

    def render_cursor(self, cursor, *args, **kwargs):
        if cursor.response is not None:
            return cursor.response
        return self.dispatch(
            cursor.node,
            self.build_request("GET"),
            *args,
            **kwargs,
        )


class BoundWizard:
    def __init__(self, request, storage, wizard=None):
        self.wizard = wizard
        self.request = request
        self.storage = storage
        self.run_id = None
        self._predicate_runtime_tree = None
        self._dispatcher = None
        self._file_storage = None

    @property
    def dispatcher(self):
        if self._dispatcher is None:
            self._dispatcher = self.wizard.step_dispatcher_class(self)
        return self._dispatcher

    @property
    def file_storage(self):
        if self._file_storage is None:
            self._file_storage = self.wizard.file_storage_class()
        return self._file_storage

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

    def submit(self, submission, *args, files=None, **kwargs):
        walker = self.wizard.cursor_walker_class(
            self.dispatcher,
            self.get_state(),
            submission,
            args,
            kwargs,
            self,
            pending_files=files,
        )
        walker.walk(self.wizard.tree)
        serializer = self.wizard.state_serializer_class()
        entries = serializer.reduce(walker.cursor().state)
        self.storage.set_state(self.run_id, entries)

    def replay(self, *args, **kwargs):
        walker = self.wizard.cursor_walker_class(
            self.dispatcher, self.get_state(), None, args, kwargs, self
        )
        walker.walk(self.wizard.tree)
        cursor = walker.cursor()
        if cursor.node is None:
            return None
        return self.dispatcher.render_cursor(cursor, *args, **kwargs)

    def render_edit(self, *args, **context):
        runtime_step = self._resolve_edit_target(context)
        initial = dict(runtime_step.data or {})
        for field, ref in (runtime_step.files or {}).items():
            initial[field] = self.file_storage.open(ref)
        return self.dispatcher.dispatch(
            runtime_step.declaration,
            self.dispatcher.build_request("GET"),
            *args,
            initial=initial,
        )

    def edit(self, submission, *args, files=None, **context):
        runtime = self.runtime_tree
        runtime_step = self._resolve_edit_target(context, runtime=runtime)
        leaf_decl = runtime_step.declaration
        merged_files = self._merge_file_refs(runtime_step.files or {}, files or {})
        spliced = SpliceSubmission(
            runtime_step, submission, files=merged_files or None
        ).transform(runtime)
        serializer = self.wizard.state_serializer_class()
        rebuilt_entries = serializer.reduce(spliced)
        walker = self.wizard.cursor_walker_class(
            self.dispatcher, rebuilt_entries, None, args, {}, self
        )
        walker.walk(self.wizard.tree)
        cursor = walker.cursor()
        if cursor.response is not None and cursor.node is leaf_decl:
            rebuilt_runtime = self._build_runtime_tree(entries=rebuilt_entries)
            entries = serializer.reduce(truncate_after(rebuilt_runtime, leaf_decl))
        else:
            entries = serializer.reduce(cursor.state)
        self.storage.set_state(self.run_id, entries)

    def _merge_file_refs(self, old_refs, new_refs):
        merged = {}
        for field, old_ref in old_refs.items():
            if field in new_refs:
                self.file_storage.delete(old_ref)
                merged[field] = new_refs[field]
            else:
                merged[field] = old_ref
        for field, new_ref in new_refs.items():
            if field not in old_refs:
                merged[field] = new_ref
        return merged

    def cleanup_files(self):
        """Remove all files persisted under this run's prefix.

        Intended to be called from `WizardViewSet.done()` overrides after the
        final submission has been consumed. Idempotent on empty runs.
        """
        self.file_storage.delete_run(self.run_id)

    def _resolve_edit_target(self, context, runtime=None):
        if runtime is None:
            runtime = self.runtime_tree
        finder = tree.ContextFinder(context, require_data=True)
        finder.visit(runtime)
        match = finder.one_with_path()
        if match is None:
            raise StepNotFound(context)
        _, runtime_step = match
        return runtime_step

    def _build_runtime_tree(self, entries):
        builder = self.wizard.runtime_tree_builder_class(self, entries)
        builder.walk(self.wizard.tree)
        return builder.head

    def _select_branch_arm(self, branch_node, partial_runtime_head=None):
        request = self.dispatcher.build_request("GET")
        self._predicate_runtime_tree = partial_runtime_head
        try:
            for predicate, subtree in branch_node.arms:
                if predicate(request):
                    return subtree
            return branch_node.default
        finally:
            self._predicate_runtime_tree = None


class CursorWalker(tree.Interpreter):
    """Interpreter that locates the wizard cursor and builds the runtime tree
    up to that point. Validates stored entries by dispatching POSTs through
    the StepDispatcher; when given a pending submission, places it at the
    cursor's slot."""

    def __init__(
        self,
        dispatcher,
        entries,
        pending_submission,
        args,
        kwargs,
        bound_wizard,
        pending_files=None,
    ):
        self._dispatcher = dispatcher
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self._pending_submission = pending_submission
        self._pending_files = pending_files
        self._args = args
        self._kwargs = kwargs
        self._head: RuntimeStep | RuntimeBranch | None = None
        self._tail: RuntimeStep | RuntimeBranch | None = None
        self._cursor = None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        stored = entry["step"] if entry is not None else None
        stored_files = entry.get("files") if entry is not None else None
        if stored is None:
            self._place_pending(step)
            self._cursor = Cursor(node=step, state=self._head)
            return False
        response = self._dispatcher.dispatch(
            step,
            self._dispatcher.build_request(
                "POST",
                submission=stored,
                files=self._open_files(stored_files),
            ),
            *self._args,
            **self._kwargs,
        )
        if not self._dispatcher.response_satisfies_step(response):
            self._place_pending(step)
            self._cursor = Cursor(node=step, state=self._head, response=response)
            return False
        self._append(
            RuntimeStep(
                declaration=step,
                data=stored,
                files=stored_files,
                bound_wizard=self._bound_wizard,
            )
        )
        return True

    def visit_branch(self, branch):
        entry = next(self._entries_iter, None)
        sub_entries = entry["branch"] if entry is not None else []
        arm = self._bound_wizard._select_branch_arm(branch, self._head)
        sub = type(self)(
            self._dispatcher,
            sub_entries,
            self._pending_submission,
            self._args,
            self._kwargs,
            self._bound_wizard,
            pending_files=self._pending_files,
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
            self._append(
                RuntimeStep(
                    declaration=step,
                    data=self._pending_submission,
                    files=self._pending_files,
                    bound_wizard=self._bound_wizard,
                )
            )

    def _open_files(self, file_refs):
        return _open_file_refs(self._bound_wizard, file_refs)

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
        entry = {"step": runtime_step.data}
        if runtime_step.files:
            entry["files"] = runtime_step.files
        return entry

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
    state data to runtime steps along the active path."""

    def __init__(self, bound_wizard, entries):
        self._bound_wizard = bound_wizard
        self._entries_iter = iter(entries)
        self.head: RuntimeStep | RuntimeBranch | None = None
        self._tail: RuntimeStep | RuntimeBranch | None = None

    def visit_step(self, step):
        entry = next(self._entries_iter, None)
        if entry is None:
            data = None
            files = None
        else:
            data = entry["step"]
            files = entry.get("files")
        self._append(
            RuntimeStep(
                declaration=step,
                data=data,
                files=files,
                bound_wizard=self._bound_wizard,
            )
        )

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


class SpliceSubmission(tree.Transformer):
    """Transformer over a runtime tree that replaces the `data` (and `files`)
    on a target RuntimeStep (identified by identity) with a new submission.
    All other nodes are structurally cloned."""

    def __init__(self, target, submission, files=None):
        self._target = target
        self._submission = submission
        self._files = files

    def visit_step(self, runtime_step, next_result):
        if runtime_step is self._target:
            data = self._submission
            files = self._files
        else:
            data = runtime_step.data
            files = runtime_step.files
        return RuntimeStep(
            declaration=runtime_step.declaration,
            data=data,
            files=files,
            next=next_result,
            bound_wizard=runtime_step.bound_wizard,
        )

    def visit_branch(self, runtime_branch, transformed_arm, next_result):
        return RuntimeBranch(
            declaration=runtime_branch.declaration,
            selected_arm=transformed_arm,
            next=next_result,
        )


def truncate_after(runtime_tree, target_decl):
    """Returns a new runtime tree where the RuntimeStep with
    `declaration is target_decl` is preserved (with `next=None`) and
    everything after it is dropped."""
    new_tree, _ = _truncate_after_recurse(runtime_tree, target_decl)
    return new_tree


def _truncate_after_recurse(node, target_decl):
    if node is None:
        return None, False
    if isinstance(node, RuntimeStep):
        if node.declaration is target_decl:
            return (
                RuntimeStep(
                    node.declaration,
                    data=node.data,
                    files=node.files,
                    next=None,
                    bound_wizard=node.bound_wizard,
                ),
                True,
            )
        new_next, found = _truncate_after_recurse(node.next, target_decl)
        return (
            RuntimeStep(
                node.declaration,
                data=node.data,
                files=node.files,
                next=new_next,
                bound_wizard=node.bound_wizard,
            ),
            found,
        )
    new_arm, found_in_arm = _truncate_after_recurse(node.selected_arm, target_decl)
    if found_in_arm:
        return (
            RuntimeBranch(node.declaration, selected_arm=new_arm, next=None),
            True,
        )
    new_next, found_in_next = _truncate_after_recurse(node.next, target_decl)
    return (
        RuntimeBranch(node.declaration, selected_arm=new_arm, next=new_next),
        found_in_next,
    )
