# Chapter 16 — Outline, observers and the driver

The application is done. Three things are worth knowing about it from the
outside.

### What shape is it

A configured wizard can describe itself, as data:

```python
ExpandingApplicationViewSet.wizard.configure(template_name="...").outline()
# [{"kind": "step", "name": "applying-as", ...},
#  {"kind": "branch", "arms": [{"steps": [..., {"kind": "switch", ...},
#                                         ..., {"kind": "expand"}]}],
#   "default": [{"kind": "step", "name": "about-you", ...}]},
#  {"kind": "step", "name": "contact", ...}]
```

It is the data counterpart of the tree `repr()` you get while debugging:
every step in order, every fork with **all** of its possible routes, and a
marker wherever `.expand()` grows the tree from an answer. It describes the
declaration, so it needs no run, no request and no storage. Useful for a
progress indicator that has to cope with branches, for a diagram, and for a
test that pins a wizard's shape.

### How is it going

Which step do applicants get wrong most often? Declare an observer and it is
told what happens, for every run of that wizard — over HTTP, from a script,
or from a test. Chapter 15's setup wizard carries one:

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
fires only when an answer is actually placed.

**Observers see what happened, never what was said.** A step's answers are
somebody's name and address, so an observer is handed the step *declaration*
and the outcome — enough to count, group and compare, and not enough to leak
personal data into a metrics backend.

### Filling it in without a browser

`RunDriver` is the same wizard without a browser: it walks a run by calling
the runtime directly, so a data import, a management command, an admin
action — or an AI agent holding somebody's details — can answer steps as
data.

```python
from gandalf.driver import RunDriver

driver = RunDriver.begin(FirstApplicationViewSet, may_finish=True)

driver.describe().schema        # JSON Schema for the current step's form
driver.submit({"full_name": "Ada"})
result = driver.submit({"email": "ada@example.com"})
if result.status == "complete":
    driver.finish()             # fires done() exactly once
```

Nothing here is a second implementation. Every operation is the one a
request performs, so a run filled programmatically is an ordinary run: same
`run_id`, same stored state, same re-validation. With a durable storage
backend you can fill a run from a script and hand somebody a step URL to
check and confirm in the browser.

Two things follow from a caller that is not a person. **Concluding a run is
opt-in**: `done()` is where the irreversible things live, so `finish()`
refuses unless the driver was built with `may_finish=True`. And **every
placement records who made it**, so a rule like "never overwrite what a
person typed" can be written — and is yours to write, because whose answer
this is is a question about your domain rather than about wizards.

And a wizard is not always the whole thing. A journey is a task list of
them, and which sections are open, which are finished and what the whole
application is waiting on are the page's to say — so there is a driver for
that too:

```python
from gandalf.driver import JourneyDriver

journey = JourneyDriver.begin(GrantApplicationViewSet, actor=user)

journey.rows()                     # the page, as a person would see it
contact = journey.section("contact")   # the row, opened
journey.url                        # where to send them to check it over
```

`section()` goes through the page's door, so a section the row shows as
*Cannot start yet* is refused here too. That is the same rule and not a
second copy of it: what the browser is refused, a script is refused, and
[chapter 14](14-blocked-and-hidden.md)'s gates need writing once.

`gandalf.contrib.agent` is the other half: an agent built on the driver,
which ships beside the library rather than inside it.

> **Source:** the driver against these wizards is
> [`test_driver_wizards.py`](../../tests/functional/test_driver_wizards.py), and
> against a task list [`test_driver_task_lists.py`](../../tests/unit/test_driver_task_lists.py) &nbsp;·&nbsp; **Reference:** [`outline()`](../reference/wizard.md), [Observers](../reference/observers.md), [Driver](../reference/driver.md), [Agent](../reference/agent.md)

---

[← Chapter 15 — Journeys: scope, memory, groups and an ending](15-journeys.md) · [Learn](README.md) · [Coming from `django-formtools` →](coming-from-django-formtools.md)
