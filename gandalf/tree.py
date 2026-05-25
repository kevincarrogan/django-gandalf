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
        return "\n".join(self.lines(""))

    def lines(self, indent: str) -> list[str]:  # pragma: no cover
        lines = [f"{indent}- Step({self.declaration.__name__})"]
        if self.next is not None:
            lines.extend(self.next.lines(indent))
        return lines

    def matches_context(self, **context) -> bool:
        own = self.context or {}
        return all(own.get(key) == value for key, value in context.items())

    def configure(self, *, template_name: str | None) -> Step:
        configured_next = (
            self.next.configure(template_name=template_name)
            if self.next is not None
            else None
        )

        if issubclass(self.declaration, forms.Form):
            if template_name is None:
                raise ImproperlyConfigured(
                    "Wizard.configure() must receive template_name when "
                    "generating FormView steps from Form classes."
                )
            form_view = form_view_factory(
                self.declaration,
                template_name=template_name,
            )
        else:
            form_view = self.declaration

        return replace(self, form_view=form_view, next=configured_next)

    def __iter__(self):
        yield self
        if self.next is not None:
            yield from self.next

    def accept_visit(self, visitor):
        return visitor.visit_step(self)

    def accept_interpret(self, interpreter):
        return interpreter.visit_step(self)


@dataclass(frozen=True)
class Branch:
    arms: tuple[tuple[Callable, Node], ...]
    default: Node | None = None
    next: Node | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return "\n".join(self.lines(""))

    def lines(self, indent: str) -> list[str]:  # pragma: no cover
        lines = [f"{indent}- Branch"]
        for predicate, subtree in self.arms:
            lines.append(f"{indent}  if {predicate.__name__}:")
            lines.extend(subtree.lines(indent + "    "))
        if self.default is not None:
            lines.append(f"{indent}  default:")
            lines.extend(self.default.lines(indent + "    "))
        if self.next is not None:
            lines.extend(self.next.lines(indent))
        return lines

    def configure(self, *, template_name: str | None) -> Branch:
        configured_arms = tuple(
            (
                predicate,
                subtree.configure(template_name=template_name)
                if subtree is not None
                else None,
            )
            for predicate, subtree in self.arms
        )
        configured_default = (
            self.default.configure(template_name=template_name)
            if self.default is not None
            else None
        )
        configured_next = (
            self.next.configure(template_name=template_name)
            if self.next is not None
            else None
        )
        return replace(
            self,
            arms=configured_arms,
            default=configured_default,
            next=configured_next,
        )

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
