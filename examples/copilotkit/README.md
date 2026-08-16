# Hybrid demo: a copilot fills it, a person finishes it

A browser chat drives a gandalf wizard, and then hands it back. The agent
does the tedium — outlining a fourteen-step insurance quote, prefilling
everything it can from the conversation and the customer's profile — and
stops at the one thing it should never do for someone: confirming. It
hands over a link, and the person lands on the wizard's own
check-your-answers page, in the ordinary Django UI, with everything
already filled in and a change link beside every answer.

The wizard is `examples/insurance.py` (a three-way company-type branch
whose partnership arm grows a step per partner, a fleet section that
grows a step per vehicle, a claims branch, a summary review step).

## How it is wired

Everything is one Django process:

| Piece | Where |
|---|---|
| AG-UI endpoint (`POST /agent/`) | `views.py` — a Django async view over `AGUIAdapter`, streaming SSE |
| The agent and its tools | `agent.py` — a pydantic-ai `FunctionToolset` over `gandalf.driver.RunDriver` |
| The wizard, at real URLs | `wizards.py` + `urls.py` — `HybridQuoteViewSet.urls()` |
| The run itself | `tests/testapp/durable.py::ModelStorage` — a database row, scoped to its owner |
| The chat UI | `ui/` — React + CopilotKit, proxied to Django by Vite |

Two properties make the handover work, and both come from gandalf rather
than from the agent:

- **Durable, owner-scoped storage.** The run the agent fills is a row in
  the database, not a browser session, so the browser can open it — and
  only its owner can.
- **A run is addressable.** `entry_url("confirm")` is just the wizard's
  own step URL, so the handover is a link. The `handoff` tool returns it;
  the chat panel renders it as a button.

Nothing in `gandalf/` knows any of this is happening.

## Run it

Two terminals:

```sh
just copilotkit-server   # migrates, then serves Django over ASGI on :8100
just copilotkit-ui       # Vite on :5173 (provisions a local node via nodeenv)
```

Both take the Django port if 8100 is taken too — move them together:
`just copilotkit-server 8200` and `just copilotkit-ui 8200`.

Open http://localhost:5173 and ask for a quote — for example *"Get me a
quote: property and vehicle cover, £500 excess, starting 1 September."*
The panel fills as the agent works, then offers **Review and finish →**.
Follow it, change the employee count or a vehicle value, and confirm: the
run re-routes from your edit, keeps every answer that still holds, and
`done()` fires once — on your submission, not the agent's.

### The model key

The agent runs in the **server** process, so that is where the key has to
be. Put it in a `.env` file at the repo root (git-ignored, loaded
automatically by every `just` recipe):

```sh
ANTHROPIC_API_KEY=sk-ant-...
# optional: any provider pydantic-ai supports, plus that provider's key
# GANDALF_AGENT_MODEL=openai:gpt-5.2
```

Exporting it in the shell before `just copilotkit-server` works too. The
key is read once at start-up, so restart the server after adding it.
Without a key the server boots on pydantic-ai's canned `test` model: the
wiring works, the conversation is nonsense.

## What is covered by tests

- `tests/functional/test_hybrid_handoff.py` — the handover itself, with
  no model and no browser: the agent's driver fills a run, the person's
  test client opens it, edits an answer, and confirms to a changed quote.
- `tests/functional/test_copilotkit_spike.py` — the AG-UI stream, with a
  scripted streaming model.

Both run under `just test-agents`, no API key required.

## Caveats

Prototype wiring, on purpose. Everyone is signed in as the same demo user
(`middleware.py`) because a demo has no sign-up; the storage scoping is
real, the identity is a stand-in. The chat endpoint is CSRF-exempt
because it posts JSON from a script — the wizard's own form pages keep
full CSRF protection. And the browser talks to the agent directly, which
is CopilotKit's documented dev-only mode.
