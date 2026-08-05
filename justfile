test:
    uv run pytest

test-unit:
    uv run pytest tests/unit

test-functional:
    uv run pytest tests/functional

coverage:
    uv run pytest --cov=gandalf --cov-report=term-missing

coverage-unit:
    uv run pytest tests/unit --cov=gandalf --cov-config=coverage-unit.ini --cov-report=term-missing --cov-report=xml:coverage-unit.xml

coverage-functional:
    uv run pytest tests/functional --cov=gandalf --cov-report=term-missing --cov-report=xml:coverage-functional.xml

bench:
    uv run python -m benchmarks

test-django python_version django_version:
    uv run --python {{python_version}} --group dev --with "django~={{django_version}}" pytest

serve port="8000":
    PYTHONPATH=. uv run django-admin migrate --settings tests.serve_settings
    PYTHONPATH=. uv run django-admin runserver 127.0.0.1:{{port}} --settings tests.serve_settings
