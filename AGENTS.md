# Agent Instructions

## Development Approach

This project follows a test-driven development approach for filling out the required functionality.

- Start each task by describing the intended functionality before implementation.
- Write or update tests first so the expected behavior is captured before production code changes.
- Run the relevant tests and confirm they fail for the expected reason before implementing the functionality.
- Implement the smallest change needed to make the failing tests pass.
- Run the relevant tests again and confirm they pass.
- Refactor after the tests pass, keeping the test suite green.
- Only move on to the next task after the failing-test, implementation, passing-test, and refactor cycle is complete.
- Keep `README.md` in sync where possible, and call out any inconsistencies you notice between it and the implemented behavior.
- Prefer adding reusable developer workflow commands to `justfile` rather than documenting raw shell commands in `README.md`. Keep README prose focused on project behavior and point to the `just` command when a workflow needs to be discoverable.
- In documentation examples, if Django classes/functions are referenced, include the full Django import lines needed for that snippet.

## Django Test Style

- Prefer `pytest-django` fixtures and helpers over manually constructing Django test machinery where possible.
- Use fixtures such as `client`, `rf`, `admin_client`, `settings`, `django_assert_num_queries`, and `django_db_blocker` when they fit the test.
- Use `pytest_django.asserts` helpers such as `assertTemplateUsed`, `assertContains`, and `assertRedirects` instead of hand-rolled checks when they express the behavior clearly.
- Avoid instantiating Django `Client`, `RequestFactory`, or modifying settings manually unless the fixture or helper is insufficient for the test.
- Name tests after observable behavior, not implementation details.
- Prefer one request per test unless the behavior specifically requires multiple requests.
- Keep assertions focused on user-visible or framework-visible outcomes such as status codes, templates used, response context, rendered HTML, redirects, form errors, and persisted state.
- When testing view rendering, prefer proving the complete request/render path: assert the response status, the template used, the expected context object, and a small representative HTML fragment.
- Keep test app fixtures small and explicit. Put scenario-specific views and forms in `tests/testapp/` rather than building large inline test objects.
- Keep tests close to the behavior owner. Put `Wizard` API and step-selection behavior in wizard-focused unit tests, and keep `WizardViewSet` tests focused on request/response integration such as dispatching, rendering, templates, context, redirects, and form errors. Avoid adding viewset-specific routes or fixtures solely to prove a `Wizard` method unless the request boundary itself is the behavior under test.

## Current Implementation Direction

- Wizard steps support two declaration styles. Reach for the simplest one
  that fits the step:
  1. **Plain `forms.Form`** — Gandalf generates the corresponding `FormView`.
     Default for the common case.
  2. **User-supplied `FormView` subclass** — used when a step needs
     view-level configuration (`get_initial()`, `get_form_kwargs()`,
     dynamic `get_form_class()`, etc.). Gandalf reconstructs `cleaned_data`
     through the FormView's composition API, so any of those overrides are
     honored automatically.
- Prefer style 1 in tests and documentation unless the scenario specifically
  exercises style 2 behavior.
- Treat parenthesized, one-builder-call-per-line wizard declarations as the idiomatic style in tests and documentation when the declaration naturally spans multiple steps or arguments:

```python
wizard = (
    Wizard()
    .step(FirstStepForm)
    .step(SecondStepForm)
)
```

When `ruff-format` keeps a short wizard declaration compact, accept that output
as idiomatic too. Do not add `# fmt: off` only to force wizard declaration
wrapping.
- Express class-level configuration constants in uppercase, for example
  `SESSION_KEY`.
- Prefer explicit `if value is None` branches when handling optional mutable
  defaults instead of shortened expressions such as `value or []`. When the
  value is transformed after defaulting, assign the default to the local
  parameter first and then perform the final assignment once.
- Stored state is a full-tree positional mirror of the wizard tree, with
  holes. Each entry in a state list is either `{"step": <form_data>}` for
  a `tree.Step` node (`{"step": null}` marks a hole — a slot with no valid
  answer yet) or `{"branch": {"<arm_id>": [<sub-state entries>, ...]}}`
  for a `tree.Branch` node, keyed per arm by declaration-order index (as a
  string) or `"default"`. The active arm's entries live under its key;
  other keys are dormant memory carried verbatim so answers survive an arm
  change and restore on flip-back. Bare-list branch entries are the legacy
  shape, still readable. `CursorWalker` in `gandalf/runtime.py` owns the
  walk: a lockstep traversal of the wizard tree and the state list that
  validates entries up to the cursor (the first missing or invalid
  answer), then seals and carries the remaining entries verbatim. Branch
  decisions are never persisted; the active arm is always recomputed from
  the preceding step submissions, and the arm id only keys which per-arm
  memory is live. Step context (e.g. `context={"step_name": "account"}`)
  is user-space metadata for lookup and introspection, not a storage key
  mechanism; steps themselves still have no stable identifiers, so
  alignment stays positional.

## Implementation Ownership

- A human will implement the main package code.
- Agents may suggest production-code changes, outline implementation approaches, and add minimal stubs when needed to make tests importable.
- Agents should not fill out production behavior in `gandalf/` unless explicitly asked to do so by the human.
- Agents may write and update test code, test app fixtures, and documentation that captures expected behavior.

## Dependencies

- New package dependencies should be pinned to the latest appropriate minor release using the compatible-release `~=` specifier.
- Prefer a full minor or patch floor such as `pytest~=8.3.5` over an open lower bound such as `pytest>=8.3.5`.
- If a dependency intentionally needs an exact patch pin or a broader range, call out the reason when making the change.
- Refresh `uv.lock` after changing dependencies.

## Commit Messages

When creating commits in this repository, follow the existing project style:

- Use a short imperative subject.
- Start with a capitalized verb.
- Do not use Conventional Commits prefixes like `docs:` or `feat:`.
- Do not end the subject with a period.
- Do not add `Co-Authored-By` trailers.

Preferred examples:

- `Add wizard storage selector`
- `Clarify README condition callback pattern`
- `Refine form view factory defaults`
