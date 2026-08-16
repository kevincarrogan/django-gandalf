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

import pytest

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


def test_declaring_a_profile_does_not_need_the_extra():
    """A profile is a declaration, and it sits on a Django class that a
    production deployment imports to serve ordinary forms.

    Run in a subprocess with the agent packages hidden, because this
    suite's own environment has them installed and so cannot tell the
    difference — the same reason the import check above is static.
    """
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import sys

        class Blocked:
            def find_module(self, name, path=None):
                if name.split(".")[0] in {"pydantic_ai", "ag_ui"}:
                    raise ImportError(f"{name} is not installed")

        sys.meta_path.insert(0, Blocked())

        from gandalf.contrib.agent import AgentProfile

        assert AgentProfile(purpose="x").purpose == "x"
        assert "gandalf.contrib.agent.toolset" not in sys.modules
        assert "gandalf.contrib.agent.deps" not in sys.modules
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_asking_for_something_that_is_not_there_still_says_so():
    """The lazy hook must not turn a typo into an obscure import error."""
    import gandalf.contrib.agent as agent

    with pytest.raises(AttributeError, match="no attribute 'nonsense'"):
        agent.nonsense
