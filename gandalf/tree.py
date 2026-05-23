from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


Node = "Step | Branch"


@dataclass(frozen=True)
class Step:
    declaration: type
    form_view: type | None = None
    next: Node | None = None

    def __repr__(self) -> str:
        return "\n".join(self.lines(""))

    def lines(self, indent: str) -> list[str]:
        lines = [f"{indent}- Step({self.declaration.__name__})"]
        if self.next is not None:
            lines.extend(self.next.lines(indent))
        return lines


@dataclass(frozen=True)
class Branch:
    arms: tuple[tuple[Callable, Node], ...]
    default: Node | None = None
    next: Node | None = None

    def __repr__(self) -> str:
        return "\n".join(self.lines(""))

    def lines(self, indent: str) -> list[str]:
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
