"""The core must not import what only `contrib` depends on.

`pip install django-gandalf` brings Django and nothing else. That holds
only while no module outside `gandalf/contrib/` reaches for pydantic-ai
or ag-ui, and the failure mode if it breaks is unpleasant: an ImportError
at startup for somebody who never wanted an agent.

Checked statically so it runs everywhere, including the environments that
*do* have the extra installed — which is every environment the rest of
this suite runs in, and so exactly the ones a runtime check could not
tell apart.
"""

import ast
from pathlib import Path

import gandalf

FORBIDDEN = {"pydantic_ai", "ag_ui", "pydantic"}
CORE = Path(gandalf.__file__).parent


def _imported_names(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_nothing_outside_contrib_imports_an_agent_dependency():
    offences = [
        (path.relative_to(CORE), name)
        for path in CORE.rglob("*.py")
        if "contrib" not in path.parts
        for name in _imported_names(path)
        if name.split(".")[0] in FORBIDDEN
    ]

    assert offences == []


def test_contrib_is_the_only_place_that_may():
    """The other half of the same claim: if this ever stops being true,
    the extra has become pointless and the split should go."""
    agent_imports = [
        name
        for path in (CORE / "contrib").rglob("*.py")
        for name in _imported_names(path)
        if name.split(".")[0] in FORBIDDEN
    ]

    assert agent_imports
