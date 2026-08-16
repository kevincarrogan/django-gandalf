# Loads a git-ignored .env if present, so demo credentials (ANTHROPIC_API_KEY)
# live in a file rather than in your shell history.
set dotenv-load := true

test:
    uv run pytest

test-unit:
    uv run pytest tests/unit

test-functional:
    uv run pytest tests/functional

coverage:
    uv run pytest --cov=gandalf --cov-report=term-missing

coverage-unit:
    uv run --extra agent pytest tests/unit --cov=gandalf --cov-config=coverage-unit.ini --cov-report=term-missing --cov-report=xml:coverage-unit.xml

# The agents group is here for the demo's suites, not for the library's: three
# functional tests `importorskip` without it and a broken branch reports green.
# They need no model key — each one scripts a FunctionModel or uses the canned
# `test` model — so this costs install time and nothing else.
coverage-functional:
    uv run --extra agent --group agents pytest tests/functional --cov=gandalf --cov-report=term-missing --cov-report=xml:coverage-functional.xml

# The extra as well as the lint group: `gandalf.contrib.agent` imports
# pydantic-ai, and mypy cannot check what it cannot resolve. Without it
# this passes locally for anyone who has the extra and fails in CI, which
# is the worst of both.
typecheck:
    uv run --group lint --extra agent mypy

# The demo's suites on their own, for a faster loop than `just
# coverage-functional`. Add a file here when you add one that needs the group,
# or this reports a false all-clear; the CI gate is coverage-functional, which
# takes the whole directory and cannot go stale this way.
test-agents:
    uv run --extra agent --group agents pytest tests/functional/test_copilotkit_spike.py tests/functional/test_hybrid_handoff.py

# Port 8000 is busy on most machines (and `just serve` wants it too), so the
# hybrid demo lives at 8100. Override on both recipes together if you move it.
copilotkit-server port="8100":
    PYTHONPATH=. uv run --extra agent --group agents django-admin migrate --settings examples.copilotkit.settings
    uv run --extra agent --group agents uvicorn examples.copilotkit.asgi:application --port {{port}}

copilotkit-ui django_port="8100":
    [ -d .nodeenv ] || uvx nodeenv --prebuilt .nodeenv
    PATH="{{justfile_directory()}}/.nodeenv/bin:$PATH" npm --prefix examples/copilotkit/ui install
    GANDALF_DJANGO_URL="http://localhost:{{django_port}}" PATH="{{justfile_directory()}}/.nodeenv/bin:$PATH" npm --prefix examples/copilotkit/ui run dev

# What describing the wizard costs an agent (counts tokens, generates none)
agent-cost:
    PYTHONPATH=. uv run --extra agent --group agents python -m examples.costs

# Run the scenarios against a real model and score what happened. Needs a
# model key; costs real money. Pass a number to repeat each scenario.
agent-eval repeats="1" only="":
    PYTHONPATH=. uv run --extra agent --group agents django-admin migrate --settings examples.copilotkit.settings
    uv run --extra agent --group agents python -m examples.evals {{repeats}} {{only}}

# Show the agent a photograph of a driving licence and print what it read
# off it, beside where the run stopped. Needs a model key; costs a real
# call, and an image is worth about a thousand tokens of one.
# `check` keeps the picture on the run; `identity` is the wizard with no
# file step at all — five pages of plain text, read from the photo.
photo-demo image wizard="check":
    PYTHONPATH=. uv run --group agents django-admin migrate --settings examples.copilotkit.settings
    PYTHONPATH=. uv run --group agents python -m examples.photo_demo {{image}} {{wizard}}

# Read back the most recent agent run: what it called, what it said, what
# it cost, and the events either side of it. Pass a number for more runs.
agent-log runs="1":
    uv run --extra agent --group agents python -m examples.agentlog {{runs}}

bench:
    uv run python -m benchmarks

test-django python_version django_version:
    uv run --python {{python_version}} --group dev --with "django~={{django_version}}" pytest

serve port="8000":
    PYTHONPATH=. uv run django-admin migrate --settings tests.serve_settings
    PYTHONPATH=. uv run django-admin runserver 127.0.0.1:{{port}} --settings tests.serve_settings
