# Chapter 13 — Blocked and hidden members

Most task lists are not a flat set. Referees cannot be asked for until the
project has been described. And an application for more than £10,000 has to
say where the rest of the money is coming from — a member that, for most
applicants, does not exist. Those are two different things, and the member
says which it is **itself**.

### Members that unlock

Override `blocked()` on the member's own viewset. It is handed the store the
hub keeps its bookkeeping in, and the rule is one read of it:

```python
class RefereesMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "referees"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, member, store):
        """Unlocks once the project has been described."""
        return not store.has_stash("project")
```

The hub declares nothing about it — `Member("referees",
RefereesMemberViewSet, title="Referees")`, as before. Answered by the member
rather than asked about it, the rule lives with the wizard it gates: it has
a name, a docstring, and a test that needs no hub. A classmethod because the
hub asks from outside the member's own dispatch: there is no instance yet,
and the point of the question is that there must not be a run.

That one answer does both halves. The row renders **Cannot start yet**, and
the door refuses it — a stale link lands back on the task list instead of
starting the run. Being blocked outranks a stash, so a member whose
prerequisite was withdrawn after it was answered reports what the user can
do rather than what they once did. A blocked member keeps the whole hub off
**Complete**, which is why a member that may never unlock is a job for
`hidden()`, below.

### The other rule reads a fact, not a stash

"Only above £10,000" turns on an *answer* given in the project member. The
project member wrote it down when it finished:

```python
class GatedProjectMemberViewSet(WizardMemberMixin, WizardViewSet):
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
and `hidden()`, never a stash's answers.** Reading an answer out of a stash
costs a walk, and a hub row must never walk. `run_done()` is where a member
pays that walk once, on a request that has already walked, and writes what
it decided; every render after reads a string.

### Members that appear

Locked is one thing; *not there yet* is another. Match funding for an
applicant asking for £5,000 is not waiting on anything — it may never apply,
and listing it as **Cannot start yet** makes a promise the journey cannot
keep. For that, override `hidden()`, the sibling of `blocked()` with the
same signature and the same store:

```python
class MatchFundingMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "match_funding"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD
```

A hidden member is gone for that request: not in `hub.rows`, not in
`hub.count`, and its door refuses a stale link. A hub of three members with
one hidden is a hub of two, and finishing those two completes it. Hidden
outranks blocked, since a member that does not exist cannot also be waiting.

Use `hidden()` for a member that may never apply and `blocked()` for one
that will, once the user has done something else first. For a rule spanning
rows — or a collection gating every item at once — the hub has
`member_blocked()` and `member_hidden()` of its own; see the
[Hubs reference](../reference/hubs.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/gated/ (ask for more than
> 10,000 and a member appears) &nbsp;·&nbsp; **Source:** [`ch13_gated.py`](../../tests/testapp/readme/ch13_gated.py)

---

[← Chapter 12 — Collections: add another](12-collections.md) · [Learn](README.md) · [Chapter 14 — Journeys: scope, memory, nesting and an ending →](14-journeys.md)
