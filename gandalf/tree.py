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

    def accept_visit(self, visitor):
        return visitor.visit_step(self)

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

    def accept_visit(self, visitor):
        visitor.visit_branch(self)
        for _, arm in self.arms:
            visitor.visit(arm)
        visitor.visit(self.default)

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


class Visitor:
    """Top-down, read-only tree traversal. Auto-descends into branch arms
    (all arms and default for declaration branches; the selected arm for
    runtime branches). Subclasses must define `visit_step` and `visit_branch`."""

    def visit(self, root):
        node = root
        while node is not None:
            node.accept_visit(self)
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
            accumulator = self.combine(
                accumulator, node.accept_reduce(self)
            )
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


class Configurer(Transformer):
    """Transforms a declaration tree by attaching `form_view` classes to each
    Step. For Steps declared with a plain `forms.Form`, generates a `FormView`
    via `form_view_factory`. For Steps declared with an explicit `FormView`
    subclass, uses it directly. Branches are rebuilt with their arms, default,
    and next configured.
    """

    def __init__(self, *, template_name: str | None):
        self.template_name = template_name

    def visit_step(self, step, next_result):
        if issubclass(step.declaration, forms.Form):
            if self.template_name is None:
                raise ImproperlyConfigured(
                    "Wizard.configure() must receive template_name when "
                    "generating FormView steps from Form classes."
                )
            form_view = form_view_factory(
                step.declaration,
                template_name=self.template_name,
            )
        else:
            form_view = step.declaration
        return replace(step, form_view=form_view, next=next_result)

    def visit_branch(
        self, branch, transformed_arms, transformed_default, next_result
    ):
        return replace(
            branch,
            arms=transformed_arms,
            default=transformed_default,
            next=next_result,
        )


class ContextFinder(Visitor):
    """Visitor that collects every Step whose context matches the provided kwargs.

    Inherits Visitor's auto-descent, so the search covers the full declared
    tree (all arms and default), regardless of which arm a runtime would select.
    """

    def __init__(self, context: dict):
        self._context = context
        self.matches: list[Step] = []

    def visit_step(self, step: Step):
        if step.matches_context(**self._context):
            self.matches.append(step)

    def visit_branch(self, branch: Branch):
        pass

    def one(self) -> Step | None:
        if len(self.matches) > 1:
            raise MultipleStepsReturned(
                f"Expected one matching step, found {len(self.matches)}."
            )
        if not self.matches:
            return None
        return self.matches[0]

    def all(self) -> list[Step]:
        return list(self.matches)
