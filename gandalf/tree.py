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


@dataclass(frozen=True)
class FlowNode:
    """A node in the output-agnostic flow graph. `kind` is ``"step"`` or
    ``"branch"``; `key` is a stable integer id assigned in structural
    pre-order."""

    key: int
    kind: str
    label: str


@dataclass(frozen=True)
class FlowEdge:
    """A directed edge between two `FlowNode` keys, with an optional label
    (a branch arm's predicate name, or ``"default"``)."""

    source: int
    target: int
    label: str | None = None


@dataclass(frozen=True)
class FlowGraph:
    """An output-agnostic model of a wizard flow: a flat set of `FlowNode`s
    and `FlowEdge`s. Renderers (Mermaid, DOT, …) consume this without ever
    touching the declaration tree, and runtime-path highlighting is just a
    matter of annotating these nodes and edges."""

    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]


class FlowGraphBuilder:
    """Folds a declaration tree into a `FlowGraph`.

    Each subtree reduces to a *fragment* with a single entry node and a set of
    exit nodes — the tails that must connect to whatever follows. Fragments
    compose by two rules:

    - *sequence*: wire every exit of the preceding fragment to the entry of
      the next node;
    - *branch*: fan the decision node out to each arm's entry (labelled with
      the arm's predicate name, or ``"default"``) and union the arm exits,
      adding the decision node itself as an exit for the skip path when an arm
      is empty or there is no default.

    Node keys are allocated in structural pre-order. This is the
    boundary-carrying fold the `Interpreter`/`Transformer`/`Reducer` family
    doesn't express: a subtree reduces to a value that remembers its entry and
    exits so the parent can wire reconvergence.
    """

    def __init__(self):
        self._nodes: list[FlowNode] = []
        self._edges: list[FlowEdge] = []
        self._counter = 0

    def build(self, root) -> FlowGraph:
        self._build_chain(root)
        return FlowGraph(nodes=tuple(self._nodes), edges=tuple(self._edges))

    def _add_node(self, kind, label) -> int:
        key = self._counter
        self._counter += 1
        self._nodes.append(FlowNode(key=key, kind=kind, label=label))
        return key

    def _add_edge(self, source, target, label=None) -> None:
        self._edges.append(FlowEdge(source=source, target=target, label=label))

    def _build_chain(self, node):
        entry = None
        exits: list[int] = []
        while node is not None:
            node_entry, node_exits = self._build_node(node)
            if entry is None:
                entry = node_entry
            else:
                for source in dict.fromkeys(exits):
                    self._add_edge(source, node_entry)
            exits = node_exits
            node = node.next
        return entry, exits

    def _build_node(self, node):
        if isinstance(node, Step):
            key = self._add_node("step", node.declaration.__name__)
            return key, [key]
        return self._build_branch(node)

    def _build_branch(self, branch):
        key = self._add_node("branch", "Branch")
        exits: list[int] = []
        for predicate, arm in branch.arms:
            self._build_arm(key, predicate.__name__, arm, exits)
        if branch.default is not None:
            self._build_arm(key, "default", branch.default, exits)
        else:
            exits.append(key)
        return key, exits

    def _build_arm(self, branch_key, label, arm, exits) -> None:
        arm_entry, arm_exits = self._build_chain(arm)
        if arm_entry is None:
            exits.append(branch_key)
            return
        self._add_edge(branch_key, arm_entry, label)
        exits.extend(arm_exits)


def build_flow_graph(root) -> FlowGraph:
    """Fold a declaration tree into a `FlowGraph`."""
    return FlowGraphBuilder().build(root)


class Mermaid:
    """Serializes a `FlowGraph` as Mermaid ``flowchart TD`` source.

    A pure writer: it owns Mermaid syntax and nothing else. Steps render as
    rectangular nodes, branches as decision nodes, and edges carry their
    optional label. All topology (sequencing, branching, reconvergence, skip
    paths) is already decided in the `FlowGraph` it is handed.
    """

    def render(self, graph) -> str:
        lines = ["flowchart TD"]
        lines.extend(self._node_line(node) for node in graph.nodes)
        lines.extend(self._edge_line(edge) for edge in graph.edges)
        return "\n".join(lines)

    def _node_line(self, node) -> str:
        if node.kind == "branch":
            return f'    n{node.key}{{"{node.label}"}}'
        return f'    n{node.key}["{node.label}"]'

    def _edge_line(self, edge) -> str:
        if edge.label is None:
            return f"    n{edge.source} --> n{edge.target}"
        return f'    n{edge.source} -->|"{edge.label}"| n{edge.target}'


def mermaid(root) -> str:
    """Render a declaration tree as a Mermaid ``flowchart TD`` source string."""
    return Mermaid().render(build_flow_graph(root))


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


def iter_nodes(root):
    """Yield every node of a tree — declaration or runtime — in pre-order.

    Descends `.next` chains, yielding each node before its children. For a
    runtime branch only the selected arm is followed; for a declaration branch
    every arm and the default are. This is the one place that knows how to
    walk *either* tree representation; callers filter the stream for whatever
    they're after.
    """
    node = root
    while node is not None:
        yield node
        if hasattr(node, "selected_arm"):
            if node.selected_arm is not None:
                yield from iter_nodes(node.selected_arm)
        elif hasattr(node, "arms"):
            for _, arm in node.arms:
                yield from iter_nodes(arm)
            if node.default is not None:
                yield from iter_nodes(node.default)
        node = node.next


class ContextFinder:
    """Finds steps matching a context across a tree (declaration or runtime).

    A thin filter over `iter_nodes`: it owns the match predicate and result
    arity, not the traversal. For runtime trees only the active arm of each
    branch is reached; for declaration trees every arm is.

    Pass `require_data=True` to skip matches whose `data` attribute is None
    (only meaningful on runtime trees).
    """

    def __init__(self, context: dict, *, require_data: bool = False):
        self._context = context
        self._require_data = require_data
        self.matches: list = []

    def visit(self, root) -> None:
        self.matches = [node for node in iter_nodes(root) if self._is_match(node)]

    def _is_match(self, node) -> bool:
        if not hasattr(node, "matches_context"):
            return False
        if not node.matches_context(**self._context):
            return False
        if self._require_data and getattr(node, "data", None) is None:
            return False
        return True

    def one(self):
        if len(self.matches) > 1:
            raise MultipleStepsReturned(
                f"Expected one matching step, found {len(self.matches)}."
            )
        if not self.matches:
            return None
        return self.matches[0]

    def all(self) -> list:
        return list(self.matches)
