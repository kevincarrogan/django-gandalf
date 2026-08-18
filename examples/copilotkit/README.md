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
| Forms the agent draws | `ui/src/GeneratedForm.jsx` — a frontend tool; nothing server-side knows |

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

**Restart the Vite server after switching branches.** `main` has no
`examples/` directory, so checking it out while the dev server is running
makes `vite.config.js` vanish underneath it. Vite restarts against a
default config and comes back without the proxy — every `/…-agent/` call
404s — and without the React plugin, so JSX compiles to
`React.createElement` rather than the automatic runtime. Both look like
the demo breaking rather than the server being misconfigured, which is how
an hour goes missing.

Open http://localhost:5173 and ask for a quote — for example *"Get me a
quote: property and vehicle cover, £500 excess, starting 1 September."*
The panel fills as the agent works, then offers **Review and finish →**.
Follow it, change the employee count or a vehicle value, and confirm: the
run re-routes from your edit, keeps every answer that still holds, and
`done()` fires once — on your submission, not the agent's.

### The adaptive quote

http://localhost:5173/#adaptive is the same quote wizard, asked however
suits the person answering. Chat is a queue — one question, one answer,
repeat — and for somebody who finds that hard it is the wrong shape. So
this agent has a second way to ask: it draws a form, in the conversation,
and decides for itself what is on it.

Tell it how you would rather be asked and watch what it makes. Driven
against Sonnet, the same wizard and the same tool gave:

| Told | Drew |
|---|---|
| *"I've never bought insurance before and I find these back-and-forth chats really hard. Can you just give me things to fill in?"* | all fourteen steps flattened into one form, with the branch-dependent fields marked *"Only needed if you're a limited company"* |
| *"I'm getting business insurance for the first time and I genuinely don't know what any of these words mean. Please go slowly and explain things."* | an explanation in chat, then **four** fields for the first step alone, each option annotated — *"A separate legal entity registered at Companies House"* |

It reads the wizard before it draws: `get_outline` gives it every step and
every schema, so the options it offers are the wizard's own and the values
behind them are exact.

**None of this is in Django.** `collect_with_a_form` is a *frontend* tool,
declared by the browser with `useHumanInTheLoop` and carried to the model
in the run input — AG-UI passes the client's tools along, and pydantic-ai's
adapter hands them to the agent like any other. No new wizard, no new
viewset, nothing server-side that knows a form was drawn. Collecting is the
front end's business; what comes back is placed with the ordinary wizard
tools and re-proved by the walk exactly as a typed answer would be. As far
as gandalf is concerned, it was typed.

Which is also why there is no paranoia here about what a drawn form may
ask. A radio group the agent invented is no more trusted than a sentence it
read in the chat: both end at `submit_step`, and the form is the authority
on what holds. The **widgets** are ours, though, and deliberately: the
agent picks the fields, their order, their grouping and their words, and
`GeneratedForm.jsx` decides that a group of choices is a real `fieldset`
with a `legend`, that help text is tied to its input with
`aria-describedby`, and that everything has a label. A form generated per
person is only worth having if it is well built, and that is not something
to leave to a sentence in a prompt.

Everything it collects lands on an ordinary run, and the panel links
straight to it — *"Open in the Django form"* opens the same `run_id` in the
wizard's own pages, wherever the walk has stopped. That link is the claim
this demo is making, so it is worth clicking. **Hide panel** folds the
instrumentation away for the view somebody using this would actually have:
a conversation, and nothing else.

#### Talking instead of typing

There is a third way to collect, and it is a tool for the same reason the
form is: a microphone in the corner is something you have to notice and
then guess the purpose of, whereas a press-to-talk panel that appears at
the moment somebody says they would rather talk is an offer that explains
itself. `ask_out_loud` puts one in the conversation and reads the question
out; `collect_with_a_form` takes `speak` to read a whole form aloud and
`dictate` per field for a microphone on that answer.

Both are the browser's own — `speechSynthesis` and `SpeechRecognition` —
so there is no key, no per-minute charge and no transcription service
anywhere in this. Two caveats that are not about money: **Chrome sends the
audio to Google's servers** (Safari uses its own, Firefox cannot listen at
all and everything degrades to typing), and free recognition is worst on
exactly this wizard's content — registrations, reference numbers, surnames.

Which is why what comes back is a **transcript and nothing else**. The
design does not need the recogniser to be good, because the model reads
the transcript and hands back a form with its understanding filled in for
checking. Driven against Sonnet with somebody saying

> *"yeah so it's analytical engines limited it's a limited company um we
> started back in december 1837 there's twelve of us we want property cover
> and public liability five hundred excess starting first of september and
> no claims ever email is ada at analyticalengines dot example"*

it produced `excess: "500"`, `["property", "liability"]`,
`ada@analyticalengines.example`, ran the lot through `check_answers`, and
drew **one** form carrying its reading of the date (`1837-12-01`, labelled
*"if unsure, just pick the 1st"*) beside the two things the speech never
covered — the Companies House number and VAT registration, which it knew
to want because the answer routed down the limited-company arm.

A rough transcript plus a person confirming beats a good transcript nobody
checks. That is the same conclusion the licence check reached about reading
a photograph, and for the same reason.

#### The fleet, which used to be where it went quiet

Vehicles are not steps of the quote. They are a **collection** — a list the
person grows, one wizard run per vehicle, behind its own page — and
`gandalf.driver` drives one run. So an agent holding only `RunDriver` could
fill a fourteen-step quote and not add a van, and `examples/insurance.py`
said so in a comment while the wizard's `AgentProfile` said so out loud.

`fleet.py` lifts that, and needs no new library API to do it. A collection
page is an ordinary Django view whose four verbs — add, change, remove,
declare done — are ordinary methods: `add_item()` mints and registers an id,
`get_item_ids()` is the registry, `get_section_rows()` is what the person
sees. Set it up against a fabricated request and they all answer. The item
id is then just a URL kwarg, and `RunDriver.begin(ItemViewSet, item=…)`
already takes those. Same driver, same walk, a different run.

What it *did* need was durable storage on both halves. The agent drives a
fabricated request, and this demo keeps sessions in a signed cookie, so
there is no session it could share even in principle. `HybridVehicleItem…`
and `HybridVehicleCollection…` swap `storage_class` **and**
`section_store_class` — the durable-storage docstring warns that one without
the other gives you "durable answers nobody can find" — and both sides then
see one fleet, scoped to the user. `fleet_values` reads the values off the
collection's own stashes rather than the session copy `insurance.py` keeps,
so there is no second copy to disagree.

Two decisions neither obvious nor forced:

- **It finishes what it adds.** Everywhere else this demo stops short of
  confirming, and that rule is about the quote — `done()` is where the price
  is struck. A vehicle is a row on the person's own list, removable, and
  committing them to nothing; and an unfinished item has no title, shows as
  *not started* and prices as zero. Half a vehicle is not a smaller vehicle.
- **It never declares the fleet complete.** That is the answer to *any more
  to add?*, the one thing storage genuinely cannot infer, so there is no
  tool for it and the agent hands over the page.

Everything it adds is marked `{"unattended": True}`, so a row's provenance
survives.

One honest caveat. Asked directly — *"add my van AE01 CAB, worth 18000"* —
it calls `get_the_fleet` then `add_a_vehicle` and the row lands, titled and
priced. Mentioned in passing, inside a general quote request, three runs of
one prompt gave three answers: a form covering the whole quote, a chat
reply, and a form again. The tools are reliable; noticing that a sentence
about vans is a job for them is not yet.

#### Checking it without a browser

```sh
just collect-demo "I would rather just talk than type all this out."
just collect-demo "yeah so it's analytical engines limited um we started..." heard
```

Prints which of the three ways to collect the agent picked and what it
drew. With `heard`, the sentence arrives as the *result* of an
`ask_out_loud` call — which is what the browser posts once somebody stops
speaking, and the half most worth re-checking, since it is where a rough
transcript has to come back as a form with the right things already in it.
No microphone and no browser.

It posts to `/adaptive-agent/` rather than driving the agent in-process,
because the tools under test are the browser's: they reach the model only
by way of the run input. Same shape as `just photo-demo`, and for the same
reason — the model's judgement is the output, so the only way to know it is
any good is to read what came out beside what went in.

Two things that cost an afternoon each and are easy to hit again:

- **Send through the core, not the agent.** `agent.runAgent()` posts what
  the agent holds, and the frontend tools a page registers are attached by
  `copilotkit.runAgent({ agent })`. Call the agent directly and the run
  goes out with `tools: []` — so the model never learns it can draw a form
  and writes one out in prose instead. Nothing errors and the reply is
  perfectly coherent; it looks exactly like the model choosing not to.
- **`TestModel` goes quiet once it has spoken.** It calls every tool it is
  offered, but only in a conversation with no assistant turn in it — and
  this page greets you. So the free CI run cannot see a drawn form, and the
  smoke test asserts the *request* instead. Against a real model the
  greeting changes nothing.

### The licence check

http://localhost:5173/#licence is the same machinery with the arrows
reversed. Instead of the page handing the agent a profile to type in, you
hand it a photograph and it does the reading: take or choose a picture of
a driving licence, and it attaches the image to the run, transcribes the
four fields printed on the card, and stops — because a misread character
looks exactly like a correctly read one, and only you can tell.

There are four ways to hand over the picture and they all end up in the
same place, though they do not all send at the same moment. The button takes a photo and sends it immediately — it keeps `capture`,
which opens the camera rather than a picker and is the difference between
one tap and three. The chat itself takes a drag, a paste, or its own
attach button; those attach to the composer and go when you press send,
which is what you want when you have something to say with the picture.
All three come from CopilotKit: set `attachments={{ enabled: true }}` on
`CopilotChat` and it handles the drop zone, scoped paste, thumbnails and a
20MB size check, then sends the file as an AG-UI `InputContentDataSource`
— the same part the Django side reads either way.

Best seen from a phone, where the button opens the camera. Point the Vite
dev server at your machine's address on the network to reach it from one.

For the same thing without a browser, over an image you already have:

```
just photo-demo ~/Pictures/licence.jpg
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
wizard's `AgentProfile`.

http://localhost:5173/identity/ is the same five pages as a plain form, if
you want to feel what the shortcut is worth.

Pass `identity` as a second argument for the wizard that has no file step
at all:

```
just photo-demo ~/Pictures/licence.jpg identity
```

Same four fields, no `FileField`, no attach tool — the photograph is only
ever *read*, and the agent submits four ordinary strings. That is the
common case: a wizard need not know anything about documents for an agent
to fill it from one. What makes it ask for a licence is a sentence in
that wizard's `AgentProfile`, not anything in the library.

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

- `ui/tests/smoke.spec.js` — the pages, in a real browser: each one
  mounts, none of them throws, the composer still opens a file chooser,
  and Vite is still proxying Django. `just test-ui` starts both servers
  itself, or uses them if the demo is already up.

That last one exists because `npm run build` only checks syntax: it
cannot see an undefined identifier, a component that fails to mount, or a
button that renders and does nothing, and four failures of exactly those
kinds shipped past a green build in one afternoon. It runs in CI too
(`.github/workflows/ui-smoke.yml`), on any change to this directory or to
`gandalf/contrib/agent/`.

It starts Vite with CopilotKit's dev inspector switched off — see
`src/inspector.js`. With it off these pages make no request that does not
go to localhost, which is what lets the suite fail on *any* console error
instead of on a curated list of them.

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
field was never theirs. This lives in `TheirAnswersToolset` here — the
wrapper `build_agent` puts round the library's tools — which asks
`driver.placements()` who answered a step before letting any call place
anything at it, and hands back a link to that step instead. It reads the
step a call names rather than the tool's name, so it covers a document as
well as an edit: putting a photograph over somebody's own re-affirms their
step the same way, and would relabel their answer as the agent's into the
bargain. The same wrapper tells the agent the rule, through the toolset's
own instructions, so the words and the enforcement cannot drift apart — a
refusal it can predict is one it can explain, rather than a tool it reports
as having said no. It is here rather than in the library because whose an
answer is is a question about a domain rather than about wizards; the
library records who placed what and stops there.

**What that second rule cost to learn**, because it is the argument for the
library recording anything at all. On 2026-08-15 the scenario for the
obvious hybrid case — the person changes an answer, then asks for something
else — failed five times out of five. The agent added the cyber cover it
was asked for and set the excess back to £500 in the same breath, then
reported the cyber and said nothing about the excess. The first fix made
`edit_step` merge changed fields over stored ones rather than replacing the
step wholesale; the agent immediately started sending minimal diffs, and it
did not help at all. The failure is not carelessness: the person said "£500
excess" in their opening message, the run said £250, and repairing what
looks like drift is the same instinct that makes an agent correctly fix a
genuine mistake elsewhere. Any instruction to leave stored answers alone
fights it. The agent was not missing an instruction — it was missing a
fact, because nothing in the system recorded that a *person* put £250
there. Step metadata is that fact, and the rule above is what reads it.

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
full CSRF protection, and the endpoint checks the method, the content type
and the origin in the token's place. It is still unauthenticated and
unthrottled, which is a demo's choice and not one to copy. And the browser
talks to the agent directly, which is CopilotKit's documented dev-only
mode.

The page context the chat sends (`useAgentContext`, turned into
instructions by `run_instructions` in `views.py`) is *the browser's*, so a
real deployment must not let it carry anything the server is meant to have
established — resolve that from `request.user` inside `instructions`
instead.
