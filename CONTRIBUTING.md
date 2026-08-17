# Contributing

If you're exploring this project:

1. Read `README.md` for the intended developer experience and end-to-end examples.
2. Read `ARCHITECTURE.md` for the runtime structure and how the pieces fit together.
3. Browse `tests/testapp/` for working `WizardViewSet` examples that exercise the real API.
4. Open issues or pull requests with concrete branch/tree use-cases, especially where existing wizard tooling becomes hard to maintain.

## Local setup

Install the project and development dependencies:

```bash
uv sync --group dev --group lint
```

`.python-version` pins the default environment to Python 3.12, which is what
every CI workflow installs — so `just coverage-unit` locally is the gate CI
runs, not an approximation of it. It is committed rather than left to
whoever checked out the repo because without it uv picks the newest Python
it can find, and the lock's floor Django (4.2) does not run on 3.14: the
default environment fails 221 tests before anyone has changed a line.

The pin is the *default* only. `just test-django` passes `--python`
explicitly, so the compatibility matrix still spans 3.10 to 3.14 as
`requires-python` promises.

## Testing and linting

Run the test suite with:

```bash
just test
```

The `test` recipe runs `uv run pytest`.

Run the separated suites with:

```bash
just test-unit
just test-functional
```

The unit suite exercises package behavior directly. The functional suite
exercises the package through Django's test client.

Check package coverage with:

```bash
just coverage
```

The `coverage` recipe tracks branch-aware coverage for `gandalf` and fails if
coverage drops below the configured threshold.

Check coverage for each separated suite with:

```bash
just coverage-unit
just coverage-functional
```

Each separated coverage recipe independently tracks branch-aware coverage for
`gandalf` and fails below the configured threshold.

Run a specific Python and Django compatibility check with:

```bash
just test-django 3.12 6.0
```

The `test-django` recipe runs the suite with uv using the requested Python version
and a compatible-release Django constraint.

Check types with:

```bash
just typecheck
```

The `typecheck` recipe runs mypy over `gandalf` with the django-stubs plugin.
The package is strictly typed and ships `py.typed`, so annotations are part of
what a release publishes: new code needs them, and CI fails without them.
`gandalf/runtime.py` is the one lenient module — its signatures are annotated
like everywhere else, but its internals are exempt from `disallow_untyped_defs`
rather than paying for the casts the walk would otherwise need.

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
