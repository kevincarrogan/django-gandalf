# Chapter 13 — Blocked and hidden members

Most task lists are not a flat set. Referees cannot be asked for until the
project has been described. And an application for more than £10,000 has to
say where the rest of the money is coming from — a member that, for most
applicants, does not exist. Those are two different things, and the member
says which it is **itself**.

### Members that unlock

Override `blocked()` on the member's own viewset. It is handed the store the
hub keeps its bookkeeping in, and the two rules that cover nearly every task
list are each one read of it:

```python
class RefereesMemberViewSet(RunMemberMixin, WizardViewSet):
    member_key = "referees"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, member, store):
        """Unlocks once the project has been described."""
        return not store.has_stash("project")
```

The hub declares nothing about it — `Member("referees",
RefereesMemberViewSet, title="Referees")`, as before. Answered by the
member rather than asked about it, the rule lives with the wizard it gates:
it has a name, a docstring, a subclass, and a test that needs no hub. A hub
method taking a `member` is a method with a key in scope, and a task list
that grows becomes a chain of `if member.key == ...`. Here there is no key
to branch on.

A classmethod because the hub asks from outside the member's own dispatch,
exactly as it asks `begin()` and `inspect()`: there is no instance yet, and
the point of the question is that there must not be a run. `member` is the
row being asked about — what one viewset mounted per item of a collection
needs to tell its items apart.

That one answer does both halves. The row renders `BLOCKED` with the label
**Cannot start yet**, and the door refuses it — a stale link or a hand-typed
URL lands back on the task list instead of starting the run. This is the one
place display and dispatch have to agree, so the door asks for the *status*
rather than the hook.

Being blocked **outranks** a stash, so a member whose prerequisite was
withdrawn after it was answered reports what the user can do rather than what
they once did. And a blocked member keeps the whole hub off `COMPLETE`,
which is why a member that may never unlock is a job for `hidden()`, below,
rather than a lock that never opens. `blocked()` runs once per row when the
page renders and once more at the door, so keep it cheap.

### The other rule reads a fact, not a stash

"Only above £10,000" turns on an *answer* given in the project member. The
project member wrote it down when it finished:

```python
class GatedProjectMemberViewSet(RunMemberMixin, WizardViewSet):
    member_key = "project"
    hub_url_name = "readme-gated"
    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def run_done(self, bound_wizard):
        project = bound_wizard.path.find_step(name="project")
        self.get_journey_store().data["amount"] = int(project.form.cleaned_data["amount"])
        return super().run_done(bound_wizard)
```

`store.data` is the journey's record of what its members decided — chapter
14 has the whole of it. **Read `store.data` and `has_stash()` in `blocked()`
and `hidden()`, never a stash's state.** A stash is positional against a
tree whose shape may depend on a branch predicate nobody has evaluated, so
reading an answer out of one costs a walk — and a hub row must never walk.
`run_done()` is where a member pays that walk once, while the run is
still readable and on a request that has already walked, and writes what it
decided; every render after reads a string.

### Members that appear

Locked is one thing; *not there yet* is another. Match funding for an
applicant asking for £5,000 is not waiting on anything — it may never apply,
and listing it as **Cannot start yet** makes a promise the journey cannot
keep. For that, override `hidden()`, the sibling of `blocked()` with the same
signature and the same store:

```python
class MatchFundingMemberViewSet(RunMemberMixin, WizardViewSet):
    member_key = "match_funding"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD
```

A hidden member is gone for that request: not in `hub.rows`, not in
`hub.count` or `hub.completed`, and its door refuses a stale link exactly as
it refuses a key the hub never declared. A hub of three members with one
hidden is a hub of two, and finishing those two completes it. Hidden outranks
blocked, since a member that does not exist cannot also be waiting.

Use `hidden()` for a member that may never apply and `blocked()` for one
that will, once the user has done something else first. The hub keeps
`member_blocked()` and `member_hidden()` for what a member cannot answer
alone — a rule spanning rows, or a collection gating every item at once. Each
is the question rather than a vote joined to the members', so an override
that does not call `super()` replaces their answers. `get_members()` keeps
its own job — choosing the members by user, plan or feature flag — and is not
where a member hides from an answer.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/gated/ (ask for more than
> 10,000 and a member appears) &nbsp;·&nbsp; **Source:** [`ch13_gated.py`](../tests/testapp/readme/ch13_gated.py)

---

[← Chapter 12 — Collections: add another](12-collections.md) · [README](../README.md) · [Chapter 14 — Journeys: scope, memory, nesting and an ending →](14-journeys.md)
