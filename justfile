test:
    uv run pytest || test $? -eq 5

serve:
    PYTHONPATH=. uv run django-admin migrate --settings tests.serve_settings
    PYTHONPATH=. uv run django-admin runserver 127.0.0.1:8000 --settings tests.serve_settings
