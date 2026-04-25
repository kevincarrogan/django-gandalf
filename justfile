test:
    uv run pytest || test $? -eq 5
