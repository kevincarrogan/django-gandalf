test:
    uv run pytest

test-unit:
    uv run pytest tests/unit

test-functional:
    uv run pytest tests/functional

coverage:
    uv run pytest --cov=gandalf --cov-report=term-missing

coverage-unit:
    uv run pytest tests/unit --cov=gandalf --cov-report=term-missing --cov-report=xml:coverage-unit.xml

coverage-functional:
    uv run pytest tests/functional --cov=gandalf --cov-report=term-missing --cov-report=xml:coverage-functional.xml

test-django python_version django_version:
    uv run --python {{python_version}} --group dev --with "django~={{django_version}}" pytest

serve:
    PYTHONPATH=. uv run django-admin migrate --settings tests.serve_settings
    PYTHONPATH=. uv run django-admin runserver 127.0.0.1:8000 --settings tests.serve_settings
