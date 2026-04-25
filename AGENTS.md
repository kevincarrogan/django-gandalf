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

## Implementation Ownership

- A human will implement the main package code.
- Agents may suggest production-code changes, outline implementation approaches, and add minimal stubs when needed to make tests importable.
- Agents should not fill out production behavior in `gandalf/` unless explicitly asked to do so by the human.
- Agents may write and update test code, test app fixtures, and documentation that captures expected behavior.

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
