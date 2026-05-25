from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from django import forms
from django.core.exceptions import ImproperlyConfigured

from gandalf.form_views import form_view_factory


Node = "Step | Branch"


@dataclass(frozen=True)
class Step:
    declaration: type
    form_view: type | None = None
    next: Node | None = None

    def __repr__(self) -> str:  # pragma: no cover
        return "\n".join(self.lines(""))

    def lines(self, indent: str) -> list[str]:  # pragma: no cover
        lines = [f"{indent}- Step({self.declaration.__name__})"]
        if self.next is not None:
            lines.extend(self.next.lines(indent))
        return lines

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

    def accept(self, visitor):
        return visitor.visit_step(self)


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

    def accept(self, visitor):
        return visitor.visit_branch(self)


def build(declarations: list[Node]) -> Node | None:
    head: Node | None = None
    for declaration in reversed(declarations):
        head = replace(declaration, next=head)
    return head


def walk(root, visitor):
    """Walk the linked tree starting at `root`, dispatching to `visitor.visit_step`
    or `visitor.visit_branch` for each node. A visit method returning `False`
    stops the walk; any other return value (including `None`) continues."""
    node = root
    while node is not None:
        if node.accept(visitor) is False:
            return
        node = node.next
