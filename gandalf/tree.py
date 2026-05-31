from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from django import forms
from django.core.exceptions import ImproperlyConfigured

from gandalf.form_views import form_view_factory


Node = "Step | Branch"


class MultipleStepsReturned(ValueError):
    """Raised when a context-based step lookup matches more than one step."""


@dataclass(frozen=True)
class Step:
    declaration: type
    form_view: type | None = None
    next: Node | None = None
    context: dict | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return _format_tree(self)

    def matches_context(self, **context) -> bool:
        own = self.context or {}
        return all(own.get(key) == value for key, value in context.items())

    def __iter__(self):
        yield self
        if self.next is not None:
            yield from self.next

    def accept_interpret(self, interpreter):
        return interpreter.visit_step(self)

    def accept_transform(self, transformer):
        next_result = transformer.transform(self.next)
        return transformer.visit_step(self, next_result)


@dataclass(frozen=True)
class Branch:
    arms: tuple[tuple[Callable, Node], ...]
    default: Node | None = None
    next: Node | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return _format_tree(self)

    def __iter__(self):
        yield self
        if self.next is not None:
            yield from self.next

    def accept_interpret(self, interpreter):
        return interpreter.visit_branch(self)

    def accept_transform(self, transformer):
        transformed_arms = tuple(
            (predicate, transformer.transform(subtree))
            for predicate, subtree in self.arms
        )
        transformed_default = transformer.transform(self.default)
        next_result = transformer.transform(self.next)
        return transformer.visit_branch(
            self, transformed_arms, transformed_default, next_result
        )


def build(declarations: list[Node]) -> Node | None:
    head: Node | None = None
    for declaration in reversed(declarations):
        head = replace(declaration, next=head)
    return head


class Transformer:
    """Bottom-up tree transformer (lark-style). Recurses into each node's
    children first, then calls `visit_step` / `visit_branch` with the
    transformed children as extra arguments. Returns whatever the visit
    method returns — the framework does no combining, so subclasses can
    produce a new tree, a value, or any shape they like.

    Signatures subclasses must define (for declaration trees):
        visit_step(step, next_result)
        visit_branch(branch, transformed_arms, transformed_default, next_result)
    """

    def transform(self, root):
        if root is None:
            return None
        return root.accept_transform(self)


class Reducer:
    """Bottom-up tree fold. Each node's `visit_*` method returns a value
    which is folded into the running accumulator via `combine`. The default
    `initial` / `combine` produce a list of per-node values, but subclasses
    can override them to fold into any shape — a sum, a dict, a string, etc.

    Subclasses must define `visit_step` and `visit_branch`.
    """

    def reduce(self, root):
        accumulator = self.initial()
        node = root
        while node is not None:
            accumulator = self.combine(accumulator, node.accept_reduce(self))
            node = node.next
        return accumulator

    def initial(self):
        return []

    def combine(self, accumulator, value):
        return [*accumulator, value]


class Interpreter:
    """Top-down traversal where the visitor controls descent into branch
    arms manually (typically by calling `self.walk(arm)` inside
    `visit_branch`). Subclasses must define `visit_step` and `visit_branch`;
    return `False` from a visit method to stop the walk."""

    def walk(self, root):
        node = root
        while node is not None:
            if node.accept_interpret(self) is False:
                return
            node = node.next


class Formatter(Interpreter):  # pragma: no cover
    """Interpreter that formats a tree as indented lines for debugging.
    Each level of branch descent adds four spaces of indentation.
    """

    def __init__(self, indent: str = ""):
        self._indent = indent
        self.lines: list[str] = []

    def visit_step(self, step):
        self.lines.append(f"{self._indent}- Step({step.declaration.__name__})")

    def visit_branch(self, branch):
        self.lines.append(f"{self._indent}- Branch")
        for predicate, arm in branch.arms:
            self.lines.append(f"{self._indent}  if {predicate.__name__}:")
            sub = Formatter(self._indent + "    ")
            sub.walk(arm)
            self.lines.extend(sub.lines)
        if branch.default is not None:
            self.lines.append(f"{self._indent}  default:")
            sub = Formatter(self._indent + "    ")
            sub.walk(branch.default)
            self.lines.extend(sub.lines)


def _format_tree(root) -> str:  # pragma: no cover
    formatter = Formatter()
    formatter.walk(root)
    return "\n".join(formatter.lines)


class Mermaid:
    """Renders a declaration tree as a Mermaid ``flowchart TD`` diagram.

    Steps become rectangular nodes labelled with the declaration name;
    branches become decision nodes whose outgoing edges are labelled with
    each arm's predicate name (and ``default`` for the fallback). Arm subtrees
    reconverge on whatever follows the branch, and a branch with no default
    (or an empty arm) grows a direct edge to the next node so the skip path is
    visible.

    Unlike `Formatter`, this is not an `Interpreter`: laying out edges needs
    each subtree's *exit* nodes (the tails that connect to whatever follows),
    which the linear `walk` loop does not surface. `_emit_chain` returns
    ``(entry_id, exit_ids)`` so a parent can wire those reconvergence edges.
    """

    def __init__(self):
        self.lines: list[str] = []
        self._counter = 0

    def render(self, root) -> str:
        self.lines = ["flowchart TD"]
        self._emit_chain(root)
        return "\n".join(self.lines)

    def _new_id(self) -> str:
        node_id = f"n{self._counter}"
        self._counter += 1
        return node_id

    def _emit_chain(self, node):
        entry_id = None
        pending_exits: list[str] = []
        while node is not None:
            node_id, node_exits = self._emit_node(node)
            if entry_id is None:
                entry_id = node_id
            else:
                for source in dict.fromkeys(pending_exits):
                    self._edge(source, node_id)
            pending_exits = node_exits
            node = node.next
        return entry_id, pending_exits

    def _emit_node(self, node):
        if isinstance(node, Step):
            node_id = self._new_id()
            self.lines.append(f'    {node_id}["{node.declaration.__name__}"]')
            return node_id, [node_id]
        return self._emit_branch(node)

    def _emit_branch(self, branch):
        branch_id = self._new_id()
        self.lines.append(f'    {branch_id}{{"Branch"}}')
        exits: list[str] = []
        for predicate, arm in branch.arms:
            self._emit_arm(branch_id, predicate.__name__, arm, exits)
        if branch.default is not None:
            self._emit_arm(branch_id, "default", branch.default, exits)
        else:
            exits.append(branch_id)
        return branch_id, exits

    def _emit_arm(self, branch_id, label, arm, exits):
        entry_id, arm_exits = self._emit_chain(arm)
        if entry_id is None:
            exits.append(branch_id)
            return
        self._edge(branch_id, entry_id, label)
        exits.extend(arm_exits)

    def _edge(self, source, target, label=None):
        if label is None:
            self.lines.append(f"    {source} --> {target}")
        else:
            self.lines.append(f'    {source} -->|"{label}"| {target}')


def mermaid(root) -> str:
    """Render a declaration tree as a Mermaid ``flowchart TD`` source string."""
    return Mermaid().render(root)


class Configurer(Transformer):
    """Transforms a declaration tree by attaching `form_view` classes to each
    Step. For Steps declared with a plain `forms.Form`, generates a `FormView`
    via the supplied `form_view_factory` callable (defaults to
    `gandalf.form_views.form_view_factory`). For Steps declared with an
    explicit `FormView` subclass, uses it directly. Branches are rebuilt with
    their arms, default, and next configured.
    """

    def __init__(
        self,
        *,
        template_name: str | None,
        form_view_factory=form_view_factory,
    ):
        self.template_name = template_name
        self.form_view_factory = form_view_factory

    def visit_step(self, step, next_result):
        if issubclass(step.declaration, forms.Form):
            if self.template_name is None:
                raise ImproperlyConfigured(
                    "Wizard.configure() must receive template_name when "
                    "generating FormView steps from Form classes."
                )
            form_view = self.form_view_factory(
                step.declaration,
                template_name=self.template_name,
            )
        else:
            form_view = step.declaration
        return replace(step, form_view=form_view, next=next_result)

    def visit_branch(self, branch, transformed_arms, transformed_default, next_result):
        return replace(
            branch,
            arms=transformed_arms,
            default=transformed_default,
            next=next_result,
        )


class ContextFinder:
    """Locates steps in a tree (declaration or runtime) matching a context,
    tracking the path of indices to each match. For runtime trees, only the
    active arm is traversed. For declaration trees, every arm is.

    Use `one()` / `all()` for the bare matches, or `one_with_path()` to also
    get the position tuple alongside a single match.

    Pass `require_data=True` to skip matches whose `data` attribute is None
    (only meaningful on runtime trees).
    """

    def __init__(self, context: dict, *, require_data: bool = False):
        self._context = context
        self._require_data = require_data
        self.matches: list[tuple[tuple[int, ...], object]] = []

    def visit(self, root) -> None:
        self._walk(root, ())

    def _walk(self, node, prefix: tuple[int, ...]) -> None:
        index = 0
        while node is not None:
            path = prefix + (index,)
            if hasattr(node, "matches_context"):
                if node.matches_context(**self._context):
                    if (
                        not self._require_data
                        or getattr(node, "data", None) is not None
                    ):
                        self.matches.append((path, node))
            elif hasattr(node, "selected_arm"):
                if node.selected_arm is not None:
                    self._walk(node.selected_arm, path)
            else:
                for _, arm in node.arms:
                    self._walk(arm, path)
                if node.default is not None:
                    self._walk(node.default, path)
            index += 1
            node = node.next

    def one(self):
        path_and_node = self.one_with_path()
        return None if path_and_node is None else path_and_node[1]

    def one_with_path(self):
        if len(self.matches) > 1:
            raise MultipleStepsReturned(
                f"Expected one matching step, found {len(self.matches)}."
            )
        if not self.matches:
            return None
        return self.matches[0]

    def all(self) -> list:
        return [match[1] for match in self.matches]
