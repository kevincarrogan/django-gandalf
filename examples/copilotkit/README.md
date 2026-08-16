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

### The licence check

http://localhost:5173/#licence is the same machinery with the arrows
reversed. Instead of the page handing the agent a profile to type in, you
hand it a photograph and it does the reading: take or choose a picture of
a driving licence, and it attaches the image to the run, transcribes the
four fields printed on the card, and stops — because a misread character
looks exactly like a correctly read one, and only you can tell.

There are four ways to hand over the picture and they all end up in the
same place. The button takes a photo and sends it immediately — it keeps
`capture`, which opens the camera rather than a picker and is the
difference between one tap and three. The chat itself takes a drag, a
paste, or its own attach button, all of which come from CopilotKit: set
`attachments={{ enabled: true }}` on `CopilotChat` and it handles the drop
zone, scoped paste, thumbnails and a 20MB size check, then sends the file
as an AG-UI `InputContentDataSource` — the same part the Django side reads
either way.

Best seen from a phone, where the button opens the camera. Point the Vite
dev server at your machine's address on the network to reach it from one.

For the same thing without a browser, over an image you already have:

```
just licence-demo ~/Pictures/licence.jpg
```

It prints what the agent read, where the run stopped, and what the call
cost. An image is worth roughly a thousand tokens, so that is the bulk of
it.

### The identity check

http://localhost:5173/#identity is the same idea with nothing stored. Five
pages, one question each — name, date of birth, licence number, address,
then check your answers — which is the shape a real service of this kind
takes. Every one of those answers is printed on a driving licence, so a
photo of one fills the lot.

The wizard behind it has no `FileField` anywhere, so there is nowhere a
document could be kept and the agent is offered no way to add one. It only
ever *reads* the picture. That is the common case and it needs nothing from
the library: what makes the agent ask for a licence is one sentence in that
wizard's `agent_notes`.

http://localhost:5173/identity/ is the same five pages as a plain form, if
you want to feel what the shortcut is worth.

Pass `identity` as a second argument for the wizard that has no file step
at all:

```
just licence-demo ~/Pictures/licence.jpg identity
```

Same four fields, no `FileField`, no attach tool — the photograph is only
ever *read*, and the agent submits four ordinary strings. That is the
common case: a wizard need not know anything about documents for an agent
to fill it from one. What makes it ask for a licence is a sentence in
that wizard's `agent_notes`, not anything in the library.

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

## Decided, and not worth re-litigating

Two rules this demo settled the hard way. Both are the application's, not
the library's — `gandalf.contrib.agent` has an opinion about neither.

**The agent never confirms.** A finishing tool was removed from this demo
entirely. It broke the "never confirm on their behalf" rule one run in
five — not from unreliability, but because the tool's own description said
the opposite of the prompt, and someone asking it to submit was exactly
the case both spoke to. A rule a model can break is a tool it should not
have. `handoff` returns a link instead, and there is nothing else.

**A step somebody answered is theirs, whole.** Submitting a form affirms
everything on it, so an agent editing one field would be re-affirming the
rest on the person's behalf. The agent is redirected rather than blocked:
it says what it would change and lets them change it. The cost is real —
it cannot add cyber cover to a step somebody has touched, even though that
field was never theirs. This lives in `edit_step` here, asked of
`driver.placements()`, because whose an answer is is a question about a
domain rather than about wizards; the library records who placed what and
stops there.

## What the evaluation measured

**Taken at `6b6e33d`, and history rather than the current state** — see
[#78](../../issues/78). Sonnet 5, five repeats per scenario, $1.93; Haiku
4.5 the same for $0.58.

- Front-loading works: 0 questions when the context has the answers,
  exactly 1 when it does not — and that one asks for everything missing at
  once.
- Sonnet held every boundary 5/5 except consent (4/5, now structural).
- Haiku is 3.3× cheaper and held consent 5/5, but handed back only 1/5 in
  two scenarios and asked unnecessary questions 3/5 — worse at exactly the
  things the design exists for. Protocol discipline, not cost, is the
  deciding factor.
- `just agent-cost` reports what describing a wizard costs an agent: 1,524
  tokens for the insurance wizard, of which the biggest single entry is
  the *switch* (463). An agent is told about every arm it might land in,
  so branching costs more to describe than to walk.

The evaluation reports **rates, not pass/fail**, and is a script rather
than a pytest suite because it costs money and must never run in CI.

## Caveats

Prototype wiring, on purpose. Everyone is signed in as the same demo user
(`middleware.py`) because a demo has no sign-up; the storage scoping is
real, the identity is a stand-in. The chat endpoint is CSRF-exempt
because it posts JSON from a script — the wizard's own form pages keep
full CSRF protection. And the browser talks to the agent directly, which
is CopilotKit's documented dev-only mode.
