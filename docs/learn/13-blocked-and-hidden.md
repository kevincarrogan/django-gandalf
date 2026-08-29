# Chapter 13 — Blocked and hidden members

Most task lists are not a flat set. Referees cannot be asked for until the
project has been described. And an application for more than £10,000 has to
say where the rest of the money is coming from — a member that, for most
applicants, does not exist. Those are two different things, and the
declaration says which it is, on the row it gates.

### Members that unlock

Give the member a `blocked` rule. It is handed the store the hub keeps its
bookkeeping in, and the rule is one read of it:

```python
referees = Wizard().step(RefereeForm, name="referee", label="Referee")
```

```python
        # Listed from the start but locked until the project is described:
        # the row reads *Cannot start yet* and the door refuses it.
        .member(
            "referees",
            referees,
            title="Referees",
            blocked=lambda store: not store.has_stash("project"),
        )
```

The rule sits on the row it gates, so reading the declaration top-down
tells you which members wait on which. It is a plain function of the
store — name it and test it without a hub, if it grows past a lambda.

That one answer does both halves. The row renders **Cannot start yet**, and
the door refuses it — a stale link lands back on the task list instead of
starting the run. Being blocked outranks a stash, so a member whose
prerequisite was withdrawn after it was answered reports what the user can
do rather than what they once did. A blocked member keeps the whole hub off
**Complete**, which is why a member that may never unlock is a job for
`hidden`, below.

### The other rule reads a fact, not a stash

"Only above £10,000" turns on an *answer* given in the project member. The
project member writes it down when it finishes, through its `done`:

```python
def record_amount(store, bound_wizard):
    """The amount is read off the path here — the one moment the run is
    readable and a walk has already been paid — and written to the journey's
    data, where every other member reads it without a walk."""
    project = bound_wizard.path.find_step(name="project")
    store.data["amount"] = int(project.form.cleaned_data["amount"])
```

```python
        .member(
            "project", project, title="Project", reopen="review", done=record_amount
        )
```

`store.data` is the journey's record of what its members decided — chapter
14 has the whole of it. **Read `store.data` and `has_stash()` in a
`blocked` or `hidden` rule, never a stash's answers.** Reading an answer out
of a stash costs a walk, and a hub row must never walk. `done` is where a
member pays that walk once, on a request that has already walked, and
writes what it decided; every render after reads a string.

### Members that appear

Locked is one thing; *not there yet* is another. Match funding for an
applicant asking for £5,000 is not waiting on anything — it may never apply,
and listing it as **Cannot start yet** makes a promise the journey cannot
keep. For that, give the member a `hidden` rule, the sibling of `blocked`
with the same signature and the same store:

```python
        # Not there until the amount asked for crosses the threshold: not
        # listed, not counted, and its door refuses a stale link.
        .member(
            "match_funding",
            match_funding,
            title="Match funding",
            hidden=lambda store: store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD,
        )
```

A hidden member is gone for that request: not in `hub.rows`, not in
`hub.count`, and its door refuses a stale link. A hub of three members with
one hidden is a hub of two, and finishing those two completes it. Hidden
outranks blocked, since a member that does not exist cannot also be waiting.

Use `hidden` for a member that may never apply and `blocked` for one that
will, once the user has done something else first. For a rule spanning
rows — or one that needs the request — the viewset has `member_blocked()`
and `member_hidden()` of its own; see the
[Hubs reference](../reference/hubs.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/gated/ (ask for more than
> 10,000 and a member appears) &nbsp;·&nbsp; **Source:** [`ch13_gated.py`](../../tests/testapp/readme/ch13_gated.py)

---

[← Chapter 12 — Collections: add another](12-collections.md) · [Learn](README.md) · [Chapter 14 — Journeys: scope, memory, nesting and an ending →](14-journeys.md)
