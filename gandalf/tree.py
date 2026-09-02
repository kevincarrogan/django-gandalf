from __future__ import annotations

from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypeAlias, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured

from gandalf.context import WizardContext
from gandalf.form_views import form_view_factory
from gandalf.types import Context


if TYPE_CHECKING:
    from gandalf.form_views import StepDeclaration, StepViewClass
    from gandalf.runtime import Run
    from gandalf.wizard import Wizard


Node: TypeAlias = "Step | Branch | Expand"

#: A branch arm's guard, called with the run's context mid-walk. It reads
#: the answers behind it through `context.run`, and whoever is answering
#: through `context.actor` — neither of which needs a browser to be true.
Predicate: TypeAlias = Callable[["WizardContext"], bool]

#: An expansion's builder, called with the run's context mid-walk to produce
#: the wizard whose steps are spliced in.
Builder: TypeAlias = Callable[["WizardContext"], "Wizard"]

#: A switch's selector, called with the run's context mid-walk to name which
#: case applies. Arbitrary code, exactly like a predicate — what changes is
#: that it returns *which* rather than *whether*.
Selector: TypeAlias = Callable[["WizardContext"], str]

# The visitors below are duck-typed rather than tied to a protocol: the same
# `accept_*` plumbing carries both declaration trees (this module) and
# runtime trees (`gandalf.runtime`), whose `visit_*` methods take different
# arguments and return different shapes. `Any` is the honest annotation for
# a hook whose signature its subclass chooses.


class MultipleStepsReturned(ValueError):
    """Raised when a context-based step lookup matches more than one step."""


@dataclass(frozen=True)
class Step:
    declaration: StepDeclaration
    form_view: StepViewClass | None = None
    next: Node | None = None
    context: dict[str, Any] | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return _format_tree(self)

    def matches_context(self, **context: Any) -> bool:
        own = self.context or {}
        return all(own.get(key) == value for key, value in context.items())

    def __iter__(self) -> Iterator[Node]:
        yield self
        if self.next is not None:
            yield from self.next

    def accept_interpret(self, interpreter: Any) -> Any:
        return interpreter.visit_step(self)

    def accept_transform(self, transformer: Any) -> Any:
        next_result = transformer.transform(self.next)
        return transformer.visit_step(self, next_result)


@dataclass(frozen=True)
class Branch:
    arms: tuple[tuple[Predicate, Node | None], ...]
    default: Node | None = None
    next: Node | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return _format_tree(self)

    def __iter__(self) -> Iterator[Node]:
        yield self
        if self.next is not None:
            yield from self.next

    def accept_interpret(self, interpreter: Any) -> Any:
        return interpreter.visit_branch(self)

    def accept_transform(self, transformer: Any) -> Any:
        transformed_arms = tuple(
            (predicate, transformer.transform(subtree))
            for predicate, subtree in self.arms
        )
        transformed_default = transformer.transform(self.default)
        next_result = transformer.transform(self.next)
        return transformer.visit_branch(
            self, transformed_arms, transformed_default, next_result
        )

    def arm_id(self, index: int) -> str:
        """The storage key for the arm at `index` — its declaration-order
        position, since a predicate arm has no other name."""
        return str(index)


@dataclass(frozen=True)
class CaseGuard:
    """One switch case, wearing a branch predicate's clothes.

    A `Switch` is a `Branch`, so its arms have to be guards — and this is
    the honest one: "did the selector name me?". The walk never actually
    calls it (it asks the selector once and matches the answer), but
    anything else that evaluates a declaration tree keeps working, and the
    equivalence is not a fiction.
    """

    selector: Selector
    case: str

    @property
    def __name__(self) -> str:  # pragma: no cover - debug formatting only
        name = getattr(self.selector, "__name__", type(self.selector).__name__)
        return f"{name} == {self.case!r}"

    def __call__(self, context: WizardContext) -> bool:
        # Asked through the run rather than directly, so the selector is
        # called once for the switch however many cases ask.
        run = cast("Run", context.run)
        return run.switch_value(self.selector, context) == self.case


@dataclass(frozen=True)
class Switch(Branch):
    """A branch whose arms are named by the value that selects them.

    The difference from `Branch` is not expressiveness — a selector is the
    same arbitrary code a predicate is — but that the *outcomes* are
    declared. One call decides the route however many cases there are,
    exactly one case can apply, and each arm has a name instead of a
    position: `cases[i]` names `arms[i]`, and that name is what the arm's
    answers are stored under, so reordering the cases cannot strand them.
    """

    selector: Selector = dataclass_field(kw_only=True)
    cases: tuple[str, ...] = dataclass_field(kw_only=True)

    def arm_id(self, index: int) -> str:
        """The storage key for the arm at `index` — the case that selects
        it, so reordering the cases cannot strand their answers."""
        return self.cases[index]


@dataclass(frozen=True)
class Expand:
    """A point where the tree grows during the walk.

    `builder(context)` returns a `Wizard` whose steps are spliced in here.
    It is called mid-walk, behind a fully-validated prefix — the same
    contract a branch predicate has — so it can read prior answers
    (`context.run.path.find_step(...).answer`) and produce however
    many steps they imply. The declared node carries only the builder; the
    subtree does not exist until the walk reaches it, which is why an
    expansion's steps are validated when built rather than at resolve time.
    """

    builder: Builder
    next: Node | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return _format_tree(self)

    def __iter__(self) -> Iterator[Node]:
        yield self
        if self.next is not None:
            yield from self.next

    def accept_interpret(self, interpreter: Any) -> Any:
        return interpreter.visit_expand(self)

    def accept_transform(self, transformer: Any) -> Any:
        next_result = transformer.transform(self.next)
        return transformer.visit_expand(self, next_result)


def build(declarations: list[Node]) -> Node | None:
    head: Node | None = None
    for declaration in reversed(declarations):
        head = replace(declaration, next=head)
    return head


def iter_nodes(root: Node | None) -> Iterator[Node]:
    """Yield every node in a declaration tree, descending branch arms and
    the default. An `Expand`'s subtree is built at walk time and so has
    nothing to descend into; the `Expand` node itself is still yielded."""
    node = root
    while node is not None:
        yield node
        if isinstance(node, Branch):
            for _, arm in node.arms:
                yield from iter_nodes(arm)
            yield from iter_nodes(node.default)
        node = node.next


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

    def transform(self, root: Any) -> Any:
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

    def reduce(self, root: Any) -> Any:
        # `run.path` is a `Path` wrapper; reduce over its head chain.
        # Raw runtime nodes and None have no `head`, so they pass through.
        root = getattr(root, "head", root)
        accumulator = self.initial()
        node = root
        while node is not None:
            accumulator = self.combine(accumulator, node.accept_reduce(self))
            node = node.next
        return accumulator

    def initial(self) -> Any:
        return []

    def combine(self, accumulator: Any, value: Any) -> Any:
        return [*accumulator, value]


class Interpreter:
    """Top-down traversal where the visitor controls descent into branch
    arms manually (typically by calling `self.walk(arm)` inside
    `visit_branch`). Subclasses must define `visit_step` and `visit_branch`.
    The walk always visits every node at its level; visitors that lose
    interest partway (e.g. a sealed cursor walk) track that in their own
    state."""

    def walk(self, root: Any) -> None:
        node = root
        while node is not None:
            node.accept_interpret(self)
            node = node.next


class Formatter(Interpreter):  # pragma: no cover
    """Interpreter that formats a tree as indented lines for debugging.
    Each level of branch descent adds four spaces of indentation.
    """

    def __init__(self, indent: str = "") -> None:
        self._indent = indent
        self.lines: list[str] = []

    def visit_step(self, step: Step) -> None:
        self.lines.append(f"{self._indent}- Step({step.declaration.__name__})")

    def visit_branch(self, branch: Branch) -> None:
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

    def visit_expand(self, expand: Expand) -> None:
        self.lines.append(f"{self._indent}- Expand({expand.builder.__name__})")


def _format_tree(root: Node | None) -> str:  # pragma: no cover
    formatter = Formatter()
    formatter.walk(root)
    return "\n".join(formatter.lines)


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
        form_view_factory: Callable[..., StepViewClass] = form_view_factory,
    ) -> None:
        self.template_name = template_name
        self.form_view_factory = form_view_factory

    def visit_step(self, step: Step, next_result: Node | None) -> Step:
        if issubclass(step.declaration, forms.Form):
            if self.template_name is None:
                raise ImproperlyConfigured(
                    f"A step declared from {step.declaration.__name__} needs "
                    "template_name to generate its view. Set template_name on "
                    "the WizardViewSet, or declare the step with a FormView "
                    "of its own."
                )
            form_view = self.form_view_factory(
                step.declaration,
                template_name=self.template_name,
            )
        else:
            form_view = step.declaration
        return replace(step, form_view=form_view, next=next_result)

    def visit_branch(
        self,
        branch: Branch,
        transformed_arms: tuple[tuple[Predicate, Node | None], ...],
        transformed_default: Node | None,
        next_result: Node | None,
    ) -> Branch:
        return replace(
            branch,
            arms=transformed_arms,
            default=transformed_default,
            next=next_result,
        )

    def visit_expand(self, expand: Expand, next_result: Node | None) -> Expand:
        # The builder's subtree does not exist yet; it is configured when the
        # walk builds it. Only the node's position in the chain is set here.
        return replace(expand, next=next_result)


class ContextFinder:
    """Locates steps in a tree (declaration or runtime) matching a context,
    tracking the path of indices to each match. For runtime trees, only the
    active arm is traversed. For declaration trees, every arm is.

    Use `one()` for a single match or `all()` for every match; both track the
    path of indices to each, which is what makes nested matches addressable.
    """

    def __init__(self, context: Context) -> None:
        self._context = context
        self.matches: list[tuple[tuple[int, ...], Any]] = []

    def visit(self, root: Any) -> None:
        self._walk(root, ())

    def _walk(self, node: Any, prefix: tuple[int, ...]) -> None:
        index = 0
        while node is not None:
            path = prefix + (index,)
            if hasattr(node, "matches_context"):
                if node.matches_context(**self._context):
                    self.matches.append((path, node))
            elif hasattr(node, "selected_arm"):
                if node.selected_arm is not None:
                    self._walk(node.selected_arm, path)
            elif hasattr(node, "builder"):
                # A declaration Expand: its subtree is built at walk time, so
                # there is nothing to descend into statically.
                pass
            else:
                for _, arm in node.arms:
                    self._walk(arm, path)
                if node.default is not None:
                    self._walk(node.default, path)
            index += 1
            node = node.next

    def one(self) -> Any:
        path_and_node = self.one_with_path()
        return None if path_and_node is None else path_and_node[1]

    def one_with_path(self) -> tuple[tuple[int, ...], Any] | None:
        if len(self.matches) > 1:
            raise MultipleStepsReturned(
                f"Expected one matching step, found {len(self.matches)}."
            )
        if not self.matches:
            return None
        return self.matches[0]

    def all(self) -> list[Any]:
        return [match[1] for match in self.matches]
