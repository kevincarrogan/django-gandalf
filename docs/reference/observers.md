# Observers

`gandalf.observers` — watch a run without changing it.

```python
from gandalf.observers import WizardObserver
```

An observer is told what happened to a run, as it happens, for every run
of the wizard it is configured on — over HTTP, from a
[driver](driver.md), or from a test. It is given the step *declaration*
and the outcome, never the answers: enough to count, group and compare,
and not enough to put somebody's name in a metrics backend.

---

## Reference

### `WizardObserver(run_id)`

The no-op base. Subclass it and override the events you care about; the
default for every wizard is this class, which does nothing.

One instance is built per run, lazily on the first event
(`Run.observer`), from the wizard's `observer_class`. It is not
built for a wizard resolved without a run (`WizardViewSet.resolve()`,
`RunDriver.outline_for()`), because there is no run to watch.

**Attributes** — `run_id`, the run being watched, so no event has to
repeat it.

**Caveats**

- **It must not raise.** Events fire from inside the walk, so an
  exception propagates into the request or driver call that caused it.
  Catch your own.
- **Once per placement, never per validation.** The walk re-proves every
  stored answer on every request; only the submission actually being
  placed on this walk is reported. A GET, a `cursor()`, a read of `path`
  fire nothing.
- **No answers.** `step` is the `tree.Step` declaration; the submission
  and its `cleaned_data` are not passed. Take the answers where you
  already have them — `done()`, or whatever is driving the run.
- **No "run started" event.** A run exists before its wizard is resolved
  (that ordering is what lets a dynamic `get_wizard()` read the run's
  state), so at the moment a run is minted there is no configured wizard
  to hold an observer. Use `WizardViewSet.run_started()` instead — see
  [`WizardViewSet`](viewsets.md) — or count first submissions.

### `submission(step, accepted, metadata)`

An answer was placed at `step`, and either satisfied it or did not.

**Parameters**

- `step` — the `gandalf.tree.Step` declaration, not the answer.
  `step.context["name"]` is the step's name; `step.declaration` and
  `step.form_view` are what the wizard declared. The same object for
  every run of a static wizard; rebuilt each walk for a step grown by
  `.expand()`, so compare by name.
- `accepted` — `True` if the placement satisfied the step, `False` if
  validation rejected it. Counting `False` counts mistakes people made,
  not pages they visited afterwards.
- `metadata` — whatever the placement recorded about itself, or `None`
  for one that recorded nothing. A browser submission carries no such
  claim and always arrives as `None`. `RunDriver` records
  `{"unattended": True}` on its own placements by default, and repeats
  whatever `submit(metadata=...)` was given — `{}` arrives as `{}`, not
  `None`. The library never guesses who is on the other end; it repeats
  what the placement said.

**Fires** from `CursorWalker.visit_step()` in `gandalf/runtime.py`, on
the walk that carries the submission — the step-URL POST in the viewset,
`RunDriver.submit()`, or a direct `Run.walk(claim=..., submission=...)`.
Fires whether or not the walk is then persisted, and reaches a step
inside a branch arm or an expansion through the nested walk.

**Caveats** — a placement whose validation raises an escape is reported
as `accepted=True`, because an escape satisfies its step for the walk.
That holds for `Park` too, whose answer is then not stored.

### `run_completed()`

The run finished and was tombstoned. Fires from `Run.complete()`,
which `WizardViewSet.finish()` calls after `done()` has returned — so it
follows `done()` both on the confirm POST and on `RunDriver.finish()`. A
`done()` that raises leaves the run resumable and this unfired.
`Obliterate`, `run.obliterate()` and stashing do not fire it.

### Installing one

```python
wizard = Wizard().step(...).configure(observer_class=MyObserver)
```

`observer_class` is a [configuration](configuration.md) key on
`ConfiguredWizard`; the default is `WizardObserver`. A dynamic
`get_wizard()` may configure a different observer per run.

| Event | When | Given |
| --- | --- | --- |
| `submission(step, accepted, metadata)` | an answer is placed on a walk | declaration, outcome, the placement's own claim |
| `run_completed()` | after `done()` returns and the run is tombstoned | — |

---

## Usage

### Counting rejections per step

```python
from gandalf.observers import WizardObserver
from gandalf.wizard import Wizard


class CountRejections(WizardObserver):
    def submission(self, step, accepted, metadata):
        if not accepted:
            statsd.increment(
                "grant_application.rejected",
                tags=[f"step:{step.context['name']}"],
            )


wizard = (
    Wizard()
    .step(ApplicantForm, name="applicant")
    .step(BudgetForm, name="budget")
    .configure(
        template_name="applications/step.html",
        observer_class=CountRejections,
    )
)
```

### Telling a person's placements from a driver's

```python
from gandalf.observers import WizardObserver


class WhoAnswered(WizardObserver):
    def submission(self, step, accepted, metadata):
        unattended = bool((metadata or {}).get("unattended"))
        source = "agent" if unattended else "person"
        statsd.increment(f"grant_application.{source}", tags=[f"run:{self.run_id}"])
```

A browser placement arrives with `metadata=None`; a `RunDriver` placement
with `{"unattended": True}` unless the driver was told otherwise.

### Recording completion, without letting the backend break the run

```python
from gandalf.observers import WizardObserver


class RecordOutcome(WizardObserver):
    def run_completed(self):
        try:
            analytics.track("grant_application.completed", run=self.run_id)
        except Exception:
            logger.exception("observer failed for run %s", self.run_id)
```

### Asserting on events in a test

```python
from gandalf.observers import WizardObserver

SEEN = []


class Recorder(WizardObserver):
    def submission(self, step, accepted, metadata):
        SEEN.append((step.context["name"], accepted, metadata))


def test_a_bad_email_is_counted_once(wizard_driver):
    SEEN.clear()
    run = wizard_driver("grant-application").start()
    run.post_step("applicant", {"full_name": "Ada Lovelace"})
    run.post_step("contact", {"email": "not-an-email"})
    run.get_step("contact")

    assert SEEN == [("applicant", True, None), ("contact", False, None)]
```

---

## Troubleshooting

### My counts are inflated — one mistake shows up several times

Something other than an observer is counting. `submission()` fires once
per placement; if you are also hooking a form's `clean()` or a step
view's `form_invalid()`, those run on every replay of the stored answer.
Count in the observer only.

### I need the submitted values in the observer

By design they are not passed. Read them in `done()` via
`run.path`, or in the caller of `RunDriver.submit()`, where the
decision to record personal data is visible.

### My observer's exception took the page down

Observers must not raise; the call sits inside the walk. Wrap the body in
`try`/`except` and log.

### I want an event when a run starts

There is none — see the caveat above. Override
`WizardViewSet.run_started(run)`, which fires exactly once per
run, when it is minted.

### `metadata` is `None` for placements I know came from my script

The script is submitting through the browser path (a test client, an
HTTP call). Only a placement that records metadata carries any:
`RunDriver.submit()` does by default; a POST does not.

---

**Learn:** [Chapter 15 — Outline, observers and the driver](../learn/15-outline-observers-and-the-driver.md) · **Related:** [Driver](driver.md), [`WizardViewSet`](viewsets.md), [Configuration](configuration.md), [Run metadata](run-metadata.md)
