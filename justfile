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

coverage-functional:
    uv run --extra agent pytest tests/functional --cov=gandalf --cov-report=term-missing --cov-report=xml:coverage-functional.xml

# The extra as well as the lint group: `gandalf.contrib.agent` imports
# pydantic-ai, and mypy cannot check what it cannot resolve. Without it
# this passes locally for anyone who has the extra and fails in CI, which
# is the worst of both.
typecheck:
    uv run --group lint --extra agent mypy

bench:
    uv run python -m benchmarks

test-django python_version django_version:
    uv run --python {{python_version}} --group dev --with "django~={{django_version}}" pytest

serve port="8000":
    PYTHONPATH=. uv run django-admin migrate --settings tests.serve_settings
    PYTHONPATH=. uv run django-admin runserver 127.0.0.1:{{port}} --settings tests.serve_settings
