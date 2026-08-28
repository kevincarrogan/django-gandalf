# Chapter 15 — Knowing what you built

The application is done. Three things are worth knowing about it from the
outside.

### What shape is it

> **Optional to know about.** `wizard.outline()` is a read of the declaration.

A configured wizard can describe itself, as data:

```python
ExpandingApplicationViewSet.wizard.configure(template_name="...").outline()
# [{"kind": "step", "name": "applying_as", ...},
#  {"kind": "branch", "arms": [{"steps": [..., {"kind": "switch", ...},
#                                         ..., {"kind": "expand"}]}],
#   "default": [{"kind": "step", "name": "about_you", ...}]},
#  {"kind": "step", "name": "contact", ...}]
```

It is the data counterpart of the tree `repr()` you get while debugging:
every step in order, every fork with **all** of its possible routes, and a
marker wherever `.expand()` grows the tree from an answer. Since it describes
the declaration, it needs no run, no request and no storage. A dynamic
`get_wizard()` is described as it currently resolves.
`WizardViewSet.resolve(request)` is the third door alongside `begin()` and
`inspect()`: it binds the wizard without creating a run. Useful for a
progress indicator that has to cope with branches, for documentation or a
diagram, and for a test that pins a wizard's shape.

### How is it going

> **Optional module.** `gandalf.observers` is a hook and a no-op base class.

Which step do applicants get wrong most often? Declare an observer and it is
told what happens, for every run of that wizard — over HTTP, from a script,
or from a test. Chapter 14's setup wizard carries one:

```python
from gandalf.observers import WizardObserver


class CountRejections(WizardObserver):
    def submission(self, step, accepted, metadata):
        if not accepted:
            rejections.append(step.context["name"])
```

**One event per placement, not per validation.** A run re-proves every stored
answer on every request, so an observer told about validations would count
one mistyped answer again on every page that followed it. `submission()`
fires only when an answer is actually placed, so counting `accepted=False`
counts mistakes people made.

**Observers see what happened, never what was said.** A step's answers are
somebody's name and address, so an observer is handed the step *declaration*
and the outcome — enough to count, group and compare, and not enough to leak
personal data into a metrics backend. `metadata` is whatever the placement
claimed about itself: `None` for a browser submission, `{"unattended": True}`
for one a driver made. There is no "run started" event here, because a run
exists before its wizard is resolved; the viewset's `run_started()` is for
that. An observer must not raise.

### Filling it in without a browser

> **Optional module.** `gandalf.driver` needs nothing but Django and is never
> imported unless you ask for it.

`RunDriver` is the same wizard without a browser: it walks a run by calling
the runtime directly, so a data import, a management command, an admin action
— or an AI agent holding somebody's details — can answer steps as data.

```python
from gandalf.driver import RunDriver

driver = RunDriver.begin(FirstApplicationViewSet, may_finish=True)

driver.describe().schema        # JSON Schema for the current step's form
driver.submit({"full_name": "Ada"})
result = driver.submit({"email": "ada@example.com"})
if result.status == "complete":
    driver.finish()             # fires done() exactly once
```

`submit()` reports `"advanced"`, `"invalid"` (with `errors` in
`form.errors.get_json_data()` shape), `"complete"`, or `"escaped"`;
`submit(data, step="applying_as")` edits an earlier answer and lets the walk
re-route from it. `outline()` describes the declared journey before any
answers exist; `check(answers)` says what a bag of answers *would* do without
placing any of it; `prefill(answers)` places as many as the tree will take
and reports the residue; `answers()` hands back cleaned values, and
`answers(json_safe=True)` serialisable ones.

Nothing here is a second implementation. Every operation is the one a request
performs, so a run filled programmatically is an ordinary run: same `run_id`,
same stored state, same re-validation. With a durable storage backend you can
fill a run from a script and hand somebody `bound_wizard.entry_url("review")`
to check and confirm in the browser.

Two things follow from a caller that is not a person. **Concluding a run is
opt-in**: `done()` is where the irreversible things live, so `finish()`
raises `ConfirmationRequired` unless the driver was built with
`may_finish=True`. And **every placement records who made it**: the driver
marks its own `{"unattended": True}`, `submit(..., metadata={...})` records
anything else, and `placements()` reads it all back — so a rule like "never
overwrite what a person typed" can be written, and is yours to write, because
whose answer this is is a question about your domain rather than about
wizards. Files go both ways: `open_file(ref)` gets from a stored reference to
the bytes, and `submit({}, files={"document": uploaded})` places one.

> **Source:** the driver against the README's own wizards is
> [`test_driver_journeys.py`](../tests/functional/test_driver_journeys.py).
> **See also:** [AGENT_ACCESS.md](../AGENT_ACCESS.md) for the design behind
> this, and `gandalf.contrib.agent` for the other half — an agent built on
> the driver, which ships beside the library rather than inside it.

---

[← Chapter 14 — One application, start to submit](14-one-application-start-to-submit.md) · [README](../README.md) · [Appendix A — Testing your wizards →](appendix-a-testing-your-wizards.md)
