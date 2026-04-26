test:
    uv run pytest

test-django python_version django_version:
    uv run --python {{python_version}} --group dev --with "django~={{django_version}}" pytest

serve:
    PYTHONPATH=. uv run django-admin migrate --settings tests.serve_settings
    PYTHONPATH=. uv run django-admin runserver 127.0.0.1:8000 --settings tests.serve_settings
