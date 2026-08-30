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
submission, an unknown run id or an unreachable step comes back as a
`ModelRetry` rather than a result.

### `build_toolset(viewset_class)`

The `FunctionToolset[WizardDeps]` on its own, for an agent you assemble
yourself.

### `build_instructions(viewset_class, profile=None)`

The system prompt. Everything domain-specific comes from the wizard's
`AgentProfile`; pass one to describe a wizard that does not carry its own.

### `profile_for(viewset_class)`

The viewset's `agent` attribute, or `None`.

### `accepts_documents(viewset_class)`

Whether any step of the wizard takes a file upload.

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

A worked CopilotKit front end lives in
[`examples/copilotkit/`](../../examples/copilotkit/), and the design behind the
driver and the toolset is in [`AGENT_ACCESS.md`](../../AGENT_ACCESS.md).

---

**Learn:** [Chapter 16 — Outline, observers and the driver](../learn/16-outline-observers-and-the-driver.md) · **Related:** [Driver](driver.md), [Storage](storage.md)
