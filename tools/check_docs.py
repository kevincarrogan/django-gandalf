"""Check that every link between the project's Markdown files resolves.

Two doc trees, sixteen chapters and twenty reference pages point at each
other constantly, and a rename moves a heading as easily as a file. Both
failures are silent: a dead link renders as a link, and a stale `#anchor`
scrolls to the top of the right page, which is the worst kind of wrong —
it looks like it worked.

What is checked:

- a relative link naming a file that does not exist;
- a `#fragment` naming no heading in the file it points at.

What is not: external `http(s)` links, because a network is not a fact
about this repository, and CI that fails when someone else's site is down
is CI nobody trusts.

Anchors follow GitHub's own slugger, which is what actually resolves them
when these files are read: lower-case, drop everything but word
characters, spaces and hyphens, then spaces to hyphens — and a repeated
heading gets `-1`, `-2` after the first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Everything that is prose about this project. Vendored JavaScript brings
#: its own READMEs, and they are not ours to keep honest.
ROOTS = ("docs", "examples")
TOP_LEVEL = ("README.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "AGENTS.md")
SKIP = ("node_modules", "dist", ".vite", "__pycache__", ".venv")

LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]*?)>?\s*(?:\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*```")


def markdown_files() -> list[Path]:
    found: list[Path] = [ROOT / name for name in TOP_LEVEL if (ROOT / name).exists()]
    for top in ROOTS:
        for path in sorted((ROOT / top).rglob("*.md")):
            if not any(part in SKIP for part in path.parts):
                found.append(path)
    return found


def anchors(text: str) -> set[str]:
    """Every fragment the headings in `text` offer, GitHub's way."""
    seen: dict[str, int] = {}
    slugs: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        heading = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # link text only
        heading = heading.replace("`", "")
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if not count else f"{slug}-{count}")
    return slugs


def links(text: str) -> list[str]:
    """Every link target outside a fenced code block — a snippet showing
    Markdown is an example, not a claim about this repository."""
    found: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            found.extend(LINK.findall(line))
    return found


def check() -> list[str]:
    files = markdown_files()
    known = {path.resolve() for path in files}
    cache = {path: anchors(path.read_text()) for path in files}
    problems: list[str] = []

    for path in files:
        here = path.relative_to(ROOT)
        for target in links(path.read_text()):
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, fragment = target.partition("#")
            if not file_part:
                if fragment and fragment not in cache[path]:
                    problems.append(
                        f"{here}: #{fragment} — this file has no such heading"
                    )
                continue
            destination = (path.parent / file_part).resolve()
            if not destination.exists():
                problems.append(f"{here}: {file_part} — no such file")
                continue
            if not fragment or destination not in known:
                continue
            other = next(p for p in files if p.resolve() == destination)
            if fragment not in cache[other]:
                problems.append(
                    f"{here}: {file_part}#{fragment} — that file has no such heading"
                )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("Broken documentation links:\n")
        for problem in problems:
            print(f"  {problem}")
        print(f"\n{len(problems)} to fix.")
        return 1
    print(f"Documentation links resolve ({len(markdown_files())} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
