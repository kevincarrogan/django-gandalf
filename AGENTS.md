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

## Current Implementation Direction

- For now, prefer the generated `FormView` route: wizard steps should be declared with plain Django `forms.Form` subclasses and Gandalf should generate the corresponding step view.
- Do not prioritize explicit user-supplied `FormView` step classes unless the human asks to expand the declaration API in that direction.
- When choosing the next test, strengthen the generated-form path before broadening to alternate step declaration styles.

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

Preferred examples:

- `Add wizard storage selector`
- `Clarify README condition callback pattern`
- `Refine form view factory defaults`
