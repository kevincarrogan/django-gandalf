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


def build(declarations: list[Node]) -> Node | None:
    head: Node | None = None
    for declaration in reversed(declarations):
        head = replace(declaration, next=head)
    return head


def walk(node: Node | None):
    while node is not None:
        yield node
        node = node.next
