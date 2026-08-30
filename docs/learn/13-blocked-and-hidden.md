# Chapter 13 — Blocked and hidden sections

Most task lists are not a flat set. Referees cannot be asked for until the
project has been described. And an application for more than £10,000 has to
say where the rest of the money is coming from — a section that, for most
applicants, does not exist. Those are two different things, and the section
says which it is **itself**.

### A section with behaviour

Chapter 11's sections were plain wizards, wrapped by the library. A
section that has something to say — when it may be opened, what to do when
it finishes — declares its own `SectionViewSet` and goes in the same slot.
Nothing about the task list changes; this is the `Form` to `FormView` step,
one level up.

```python
from gandalf.tasklists import Section, SectionViewSet, TaskList, TaskListViewSet
```

### Sections that unlock

Override `blocked()`. It is handed the store the page keeps its
bookkeeping in, and the rule is one read of it:

```python
class RefereesSection(SectionViewSet):
    """Listed from the start but locked until the project is described: the
    row reads *Cannot start yet* and the door refuses it."""

    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("project")
```

The rule lives with the wizard it gates: it has a name, a docstring, and a
test that needs no page. A classmethod because the page asks from outside
the section's own dispatch: there is no instance yet, and the point of the
question is that there must not be a run.

That one answer does both halves. The row renders **Cannot start yet**, and
the door refuses it — a stale link lands back on the task list instead of
starting the run. Being blocked outranks a stash, so a section whose
prerequisite was withdrawn after it was answered reports what the user can
do rather than what they once did. A blocked section keeps the whole page
off **Complete**, which is why a section that may never unlock is a job for
`hidden()`, below.

### The other rule reads a fact, not a stash

"Only above £10,000" turns on an *answer* given in the project section. The
project section writes it down when it finishes, in `run_done()`:

```python
def record_amount(store, run):
    """The amount is read off the path here — the one moment the run is
    readable and a walk has already been paid — and written to the journey's
    data, where every other section reads it without a walk."""
    project = run.path.find_step(name="project")
    store.data["amount"] = int(project.form.cleaned_data["amount"])


class ProjectSection(SectionViewSet):
    """Decides whether the match funding section exists."""

    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def run_done(self, run):
        record_amount(self.get_journey_store(), run)
        return super().run_done(run)
```

`store.data` is the journey's record of what its sections decided — chapter
14 has the whole of it. **Read `store.data` and `has_stash()` in
`blocked()` and `hidden()`, never a stash's answers.** Reading an answer out
of a stash costs a walk, and a row must never walk. `run_done()` is where a
section pays that walk once, on a request that has already walked, and
writes what it decided; every render after reads a string.

### Sections that appear

Locked is one thing; *not there yet* is another. Match funding for an
applicant asking for £5,000 is not waiting on anything — it may never apply,
and listing it as **Cannot start yet** makes a promise the journey cannot
keep. For that, override `hidden()`, the sibling of `blocked()` with the
same signature and the same store:

```python
class MatchFundingSection(SectionViewSet):
    """Not there until the amount asked for crosses the threshold: not
    listed, not counted, and its door refuses a stale link."""

    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD
```

The list itself declares nothing about any of it — the richer thing is
simply in the slot:

```python
class Gated(TaskList):
    project = Section(ProjectSection, title="Project", reopen="review")
    match_funding = Section(MatchFundingSection, title="Match funding", key="match-funding")
    referees = Section(RefereesSection, title="Referees")
```

A hidden section is gone for that request: not in `tasklist.rows`, not in
`tasklist.count`, and its door refuses a stale link. A list of three
sections with one hidden is a list of two, and finishing those two
completes it. Hidden outranks blocked, since a section that does not exist
cannot also be waiting.

Use `hidden()` for a section that may never apply and `blocked()` for one
that will, once the user has done something else first. For a rule
spanning rows — or one that needs the request — the viewset has
`entry_blocked()` and `entry_hidden()` of its own; see the
[Task lists reference](../reference/tasklists.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/gated/ (ask for more than
> 10,000 and a section appears) &nbsp;·&nbsp; **Source:** [`ch13_gated.py`](../../tests/testapp/readme/ch13_gated.py)

---

[← Chapter 12 — Add another: a list the user grows](12-add-another.md) · [Learn](README.md) · [Chapter 14 — Journeys: scope, memory, groups and an ending →](14-journeys.md)
