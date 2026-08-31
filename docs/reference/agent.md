# Agent

`gandalf.contrib.agent` — drive a wizard with a language model. Ships
beside the library rather than inside it: the core stays on Django alone.

```bash
pip install django-gandalf[agent] "pydantic-ai-slim[openai]"   # or any provider pydantic-ai supports
```

```python
from gandalf.contrib.agent import AgentProfile, build_agent
from gandalf.contrib.agent.agui import endpoint_for
```

The extra brings [pydantic-ai](https://ai.pydantic.dev/) and the AG-UI
transport. **No provider is named**: `build_agent` takes whatever pydantic-ai
takes, and the provider extra is yours to install beside this one.

---

## Reference

### `AgentProfile(purpose, notes=None)`

A frozen dataclass declaring what an agent should be told about one wizard.
Attach it to a `WizardViewSet` as `agent`.

- `purpose` — completes the sentence *"you are helping someone with —"*, so
  a noun phrase, not an instruction: `"a community grant application"`.
- `notes` — what the wizard cannot say about itself: that something the
  person needs lives on another page, that one document answers four of the
  questions.

Importing `AgentProfile` does not import pydantic-ai, so a viewset can carry
a profile in a deployment that never installed the extra.

### `build_agent(viewset_class, model, *, wrap=None)`

Returns a `pydantic_ai.Agent[WizardDeps, str]` whose tools are the
[`RunDriver`](driver.md): start or resume a run, read the outline, check a
bag of answers without placing any, prefill, submit or edit a step. It cannot
conclude a run — `done()` is where the irreversible things live, and a
person presses that.

- `model` — a `"provider:model"` string or a pydantic-ai `Model`.
- `wrap` — a callable handed the `FunctionToolset` before the agent gets it,
  for logging, metrics, or a policy that refuses a call.

| Tool | Driver call | Present |
| --- | --- | --- |
| `start_run()` | `RunDriver.begin()` | always |
| `resume_run(run_id)` | `RunDriver.resume()` | always |
| `get_run()` | `describe()` | always |
| `get_outline()` | `RunDriver.outline_for()` | always |
| `check_answers(answers)` | `check()` | always |
| `prefill(answers)` | `prefill()` | always |
| `submit_step(data)` | `submit(data)` | always |
| `edit_step(step, data)` | `submit(merged, step=step)` — `data` is merged over the stored answers | always |
| `attach_document(attachment_id, field, step=None)` | `submit({}, files=..., step=step)` | only when `accepts_documents()` |
| `handoff()` | `run.entry_url()` | only when the viewset has a `url_name` |

Every tool on a run returns its `run_id`, `step`, `schema`, `answers`,
`errors` and `complete`, and snapshots them into `WizardState`
(`get_outline` before any run returns the outline alone). A rejected
submission, an unknown run id, an unreachable step, or a
[door that will not open](driver.md) comes back as a `ModelRetry` rather
than a result.

`answers` is keyed by step name and each value is an
[`Answer`](driver.md) — a mapping of field name to value, or a list of one
such mapping per row for a step that repeats its fields. `submit_step`,
`edit_step`, `prefill` and `check_answers` take the same shape back.
`edit_step` merges what it is given over what is stored, except for rows,
which replace: a step answered with n of them has no field to merge onto,
and merging by position would keep a row the caller meant to drop.

### `build_toolset(viewset_class)`

The `FunctionToolset[WizardDeps]` on its own, for an agent you assemble
yourself.

### `build_instructions(viewset_class, profile=None)`

The system prompt. Everything domain-specific comes from the wizard's
`AgentProfile`; pass one to describe a wizard that does not carry its own.

### `profile_for(viewset_class)`

The viewset's `agent` attribute, or `None`.

### `accepts_documents(viewset_class)`

Whether any step of the wizard takes a file upload — read off the JSON
Schema's `format`, which is the machine-readable half of what a field says
about itself, rather than off the description beside it, which is prose
somebody may reasonably reword.

Two kinds of step answer nothing here. A step with no schema yet — a view
composing its form from answers the run has not got — cannot be asked. And
a step whose schema is an array repeats its fields per row, so a file in one
is addressed as `0-document` and placed with the management form, which
`attach_document` does not do. Neither turns the tool on: a tool an agent
cannot use is one it can only misuse.

### `WizardDeps`, `WizardState`, `Attachment`, `attachments_from(messages)`

The dependency object handed to every tool, the state mirrored into the
AG-UI stream, and the attachments (uploaded documents) pulled out of the
conversation for a step that takes a file.

### `endpoint_for(agent, *, instructions=None, on_complete=None)`

A Django view serving `agent` over AG-UI: one POST in, a stream of events
out. Must be served over **ASGI** (the response streams).

- `instructions(run_input)` — anything the model should be told for this
  run only; AG-UI's `RunAgentInput.context` is not otherwise forwarded.
- `on_complete(run)` — receives the finished run; the stream is watched once
  and gone.

**Caveats**

- The agent is given the browser's session, so `SessionStorage` shows it the
  runs the person started. `SESSION_ENGINE` must keep sessions server-side
  (`db`, `cache`, `cached_db`, `file`) — a cookie session's writes cannot
  survive a streamed response.
- The view refuses forged requests (method, JSON content type, trusted
  origin) and nothing else. **There is no authentication or rate limiting.**
  Wrap it in whatever the rest of the site uses:

  ```python
  from django.contrib.auth.decorators import login_required
  from django.urls import path

  from gandalf.contrib.agent.agui import endpoint_for

  urlpatterns = [path("agent/", login_required(endpoint_for(agent)))]
  ```

---

## Usage

```python
from gandalf.contrib.agent import AgentProfile, build_agent
from gandalf.viewsets import WizardViewSet


class ApplicationViewSet(WizardViewSet):
    url_name = "apply"
    wizard = ...
    agent = AgentProfile(
        purpose="a community grant application",
        notes="Budget lines are added on the budget page, not here.",
    )


agent = build_agent(ApplicationViewSet, "openai:gpt-5.2")
```

### `build_journey_agent(task_list_viewset, model, *, wrap=None)`

An agent that drives a whole [task list](tasklists.md). `build_agent` one
level up, with the same `wrap` hook and a procedure that knows there are
several parts and that one of them may be waiting on another.

### `build_journey_toolset(task_list_viewset)`

The `FunctionToolset[WizardDeps]` over [`JourneyDriver`](driver.md).

| Tool | Driver call |
| --- | --- |
| `start_application()` | `JourneyDriver.begin()` |
| `resume_application(journey_id)` | `JourneyDriver.resume()` |
| `get_application()` | `rows()` |
| `get_part(part)` | `section(part).describe()` |
| `check_part(part, answers)` | `section(part).check()` |
| `fill_part(part, answers)` | `section(part).prefill()` |
| `add_to_list(part, answers)` | `add(part)` then `prefill()` |
| `remove_from_list(part, item_id)` | `remove(part, item_id)` |
| `handoff()` | `url` |

**Every tool names the part it is about.** There is no *current section* in
the state, so nothing can fall out of step with what the person has been
doing in the browser at the same time — which is the failure this shape
exists to avoid, since an agent-filled journey is an ordinary journey the
person may be editing meanwhile.

The verbs are whole parts rather than steps, because that is what
front-loading a journey is: read the shape, ask once, fill what you were
told. There is **no tool that submits an application**, for the reason
there is none that concludes a run.

Every tool returns the page — `journey_id`, `url`, `rows`, `complete` —
and the ones about one part add it under `part`, keyed rather than splatted:
both have a `complete`, and *this part is answered* is not *every part is*.

A part a driver may not open comes back as a `ModelRetry` saying what would
have to change (a part is waiting on another, is not part of this
application, or the application has been submitted), so the model works
around it rather than trying the same thing again.

**Filling a part is not finishing it.** `fill_part` answers a part; ending
it fires that section's own `done()`, and there is no tool that does. A part
an agent filled reads as *Incomplete* until the person confirms it — the
row telling the truth, and the same handover a single wizard makes.

### Pointing one at a task-list section

A section is an ordinary `WizardViewSet`, so it takes an agent like any
other — but it is behind the page's door, and the agent is behind it too:

```python
from gandalf.contrib.agent import build_agent

agent = build_agent(GrantApplicationViewSet.viewset_for("contact"), "openai:gpt-5.2")
```

`start_run` and `resume_run` come back as a `ModelRetry` when the journey
has been submitted, or the section is `hidden()` or `blocked()` — the same
three answers the page gives a browser, in words about the application. See
[the driven door](driver.md).

A worked CopilotKit front end lives in
[`examples/copilotkit/`](../../examples/copilotkit/), and the design behind the
driver and the toolset is in [`AGENT_ACCESS.md`](../../AGENT_ACCESS.md).

---

**Learn:** [Chapter 16 — Outline, observers and the driver](../learn/16-outline-observers-and-the-driver.md) · **Related:** [Driver](driver.md), [Storage](storage.md)
