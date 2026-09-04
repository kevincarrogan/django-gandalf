# Contributing

If you're exploring this project:

1. Read `README.md`, then `docs/learn/` (the walkthrough) and `docs/reference/` (the API), for the intended developer experience and end-to-end examples.
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

### The shape matrix

`tests/functional/test_shape_matrix.py` runs every seam that reads or
writes a step's answer against every form shape that breaks a naive
implementation of one: a formset, a `MultiWidget`, a widget that names its
own POST keys, a prefixed step, a file, and a plain step as the control. Each awkward shape posts under
keys that are not its field names, which is the assumption this family of
bugs keeps rediscovering.

Add a seam and you add one test, which runs against all five shapes at
once. Add a shape and you add a row to `SHAPES` and a step to
`ShapeMatrixWizardViewSet`. A cell a seam does not handle yet is marked
`xfail(strict=True)` with the reason, so the gap stays visible and the
test starts failing the day somebody closes it.

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

Check the documentation's own links with:

```bash
just check-docs
```

The `check-docs` recipe runs `tools/check_docs.py` over every Markdown file
in `docs/`, `examples/` and the repository root: it resolves each relative
link and each `#anchor` against the headings the target file actually has.
Both failures are silent otherwise — a dead link still renders as a link,
and a stale anchor scrolls to the top of the right page, which looks like
it worked. External `http(s)` links are left alone, so the check never
fails because someone else's site is down. A heading a chapter links to is
therefore part of that chapter's contract: rename it and this is what
tells you.

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
