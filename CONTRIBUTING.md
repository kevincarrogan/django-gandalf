# Contributing

If you're exploring this project:

1. Start with the `examples/` package to understand the intended developer experience.
2. Use `implementation.py` to inspect current assumptions and gaps.
3. Open issues or pull requests with concrete branch/tree use-cases, especially where existing wizard tooling becomes hard to maintain.

## Local setup

Install the project and development dependencies:

```bash
uv sync --group dev --group lint
```

## Testing and linting

Run the test suite with:

```bash
uv run pytest
```

Run linting and formatting with:

```bash
pre-commit run --all-files
```

To install the Git hooks locally:

```bash
pre-commit install
```

## Commit messages

Use short imperative commit subjects that match the existing project history.

Examples:

- `Add dynamic get_wizard hook and examples`
- `Clarify FormView configuration extension pattern`
- `Refine README tree data contract`

Guidelines:

- Start with a capitalized imperative verb.
- Keep the subject concise.
- Do not use Conventional Commits prefixes like `docs:` or `feat:`.
- Do not end the subject with a period.
