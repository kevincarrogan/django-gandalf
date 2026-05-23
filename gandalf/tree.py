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
        return "\n".join(_render(self))


@dataclass(frozen=True)
class Branch:
    arms: tuple[tuple[Callable[..., bool], Node | None], ...] = ()
    default: Node | None = None
    next: Node | None = None

    def __repr__(self) -> str:
        return "\n".join(_render(self))


def _render(node: Node | None, indent: str = "") -> list[str]:
    lines: list[str] = []
    current = node
    while current is not None:
        if isinstance(current, Step):
            lines.append(f"{indent}- Step({current.declaration.__name__})")
        else:
            lines.append(f"{indent}- Branch")
            for predicate, subtree in current.arms:
                lines.append(f"{indent}  if {predicate.__name__}:")
                lines.extend(_render(subtree, indent + "    "))
            if current.default is not None:
                lines.append(f"{indent}  default:")
                lines.extend(_render(current.default, indent + "    "))
        current = current.next
    return lines
