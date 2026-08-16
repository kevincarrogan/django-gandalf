# Where `agent-access` is, and what to do next

A handover note. The branch is 5 commits ahead of `main`, everything is
committed and pushed, and the gates are green **in CI** — all 1,004 tests, 100%
coverage in both the unit and functional configs, mypy strict clean, `just
bench` runs.

Trust `gh pr checks` over a local run. An earlier version of this file claimed
every gate was green while the functional job had been failing on GitHub for
four commits; later, a green CI run hid a broken branch because the three
suites that would have caught it were skipped there. That second gap is closed
— the functional job installs the `agents` group, so there is no longer a
count of tests that CI does not run — but the habit is still the right one.

**The library half of this branch is finished and merged.** Five PRs —
[#59](../../pull/59) the driver, [#60](../../pull/60) the test-driver rename,
[#61](../../pull/61) taking the driver's policy back off `WizardViewSet`,
[#62](../../pull/62) JSON-safe answers, [#63](../../pull/63) metadata for the
observer. This branch is rebased onto all of them and holds no library changes
at all: `git diff main -- gandalf/` is empty, and it is meant to stay that way.

Everything left here is the demo and the evaluation.

Read `AGENT_ACCESS.md` for the architecture and `STEP_METADATA.md` for the
reasoning behind the metadata. This file is only "what is unfinished and what
was decided", so nothing has to be re-derived from a conversation.

## What is in the library now

All of it default-safe, and none of it aware that agents exist:

- **`RunDriver`** — the headless driver (`begin`/`resume`/`describe`/`submit`/
  `prefill`/`check`/`answers`/`metadata`/`outline_for`/`finish`). Nothing in it
  imports anything beyond Django and gandalf.
- **`answers(json_safe=True)`** and **`describe(json_safe=True)`** — the same
  answers rendered as JSON holds them, because `cleaned_data` has `date`s in it
  and most of what a driver is for cannot hold one. It is the cleaned answer
  that is rendered, so a ticked checkbox is `True` and not the `"on"` a browser
  posted.
- **`RunDriver.may_finish`**, default `False`; `finish()` raises
  `ConfirmationRequired` without it. On the *driver*, not the wizard: whether a
  run may be concluded unattended depends on what is holding it, and the caller
  being guarded is not the one that should hold the switch.
- **Step metadata** — a placement carries a mapping stored as `meta` beside the
  answer. `RunDriver.submit(..., metadata=...)` defaults to
  `{"unattended": True}` and `driver.placements()` reads it back, beside the
  answers and files stored with it.
- **`WizardObserver.submission(step, accepted, metadata)`** — so one observer
  watching a shared run can tell a person's answer from an agent's, without the
  library having to guess who was on the other end.

**There is deliberately no edit policy in core.** Whose an answer is is a
question about a domain rather than about wizards, and metadata is everything a
caller needs to answer it — see *Decided* below.

**One breaking change to note in release notes:** a `cursor_walker_class`
written from scratch now receives a `metadata` keyword. Subclassing
`CursorWalker` is unaffected.

## Decided, so please don't re-litigate

- **The agent never confirms.** `complete_run` was removed from the CopilotKit
  demo entirely. It broke the "never confirm on their behalf" rule 1 run in 5 —
  not from unreliability but because the tool's own description said the
  opposite of the prompt. A rule a model can break is a tool it should not
  have.
- **A step somebody answered is theirs, whole.** Submitting a form affirms
  everything on it. The agent is redirected rather than blocked: it says what
  it would change and lets them change it. Cost: it cannot add cyber cover to a
  step somebody has touched, even though that field was never theirs.
- **That rule lives in the demo, not the library.** It was briefly a
  `WizardViewSet.may_edit_step` hook and #61 removed it. The hook saw nothing
  the caller cannot see before it submits, and a method on the class that
  serves wizards over HTTP, consulted only by a driver, is a thing nobody
  reading `WizardViewSet` could make sense of. It is now four lines in
  `edit_step`, asked of `driver.placements()`.
- **The evaluation reports rates, not pass/fail**, and is a script rather than
  a pytest suite because it costs money and must never run in CI.

## Next

The cheap one first, because it changes what the expensive one is worth.

### 1. Scenarios — done, bar one that should not be written

Fourteen now, from eight. Three came with the behaviour they measure —
*asked for the link part way through*, *asked about an answer they changed
themselves*, and *the run id is lost between turns*, the last needing one
new field, `forget_run`, which drops the run id before the follow-up the
way a page reload does. The harness reads back the run the agent
*started*, so beginning a fresh one over the top cannot score as a pass.

Three closed the holes this file listed. *The agent changes its own
earlier answer* is the one that mattered: seven of the eight scorers are
negatives, so an agent that refused every edit — or a policy bug
rejecting all of them — scored perfectly, and correctly protective looked
exactly like uselessly protective. *A partnership* finally walks the arm
with the `.expand()` in it, and *a sole trader* the third arm, which is
described to every agent at the switch's expense and had never been
walked.

**The rejected-submission scenario is deliberately not written.** This
file said to check first whether the insurance wizard has a form-level
`clean()` that can reject a value `check()` would pass. It does not —
every constraint in it is field-level, and `check()` binds each form
standalone, so it catches all of them. There is no honest way to stage
the `ModelRetry` path against this wizard, and inventing a trap would
measure the trap. It would need a wizard whose steps disagree with each
other, which is a different demo.

### 2. Re-run the whole evaluation

**7 of the 8 scenarios have not been run since the changes that matter.** The
last full sweep was at `6b6e33d`; since then `complete_run` was removed,
`edit_step` began merging rather than replacing, the edit policy landed and
then moved out of the library, and the driver's serialisation changed.

```
just agent-eval 5          # ~$2 for 8 scenarios, ~15 minutes
```

Two things to watch. `DidNotConfirmOnTheirBehalf` should hold 5/5 for free —
the tool it guards no longer exists — and if it does not, a finishing tool has
come back. And an agent correcting *its own* earlier answer must still be
allowed; that is pinned by a test either way, so a failure in the sweep means
the agent stopped retrying rather than that the policy broke.

None of the library work since `6b6e33d` should move the numbers on its own —
the round trip was a behaviour-identical swap of where a value is converted,
and the edit rule moved without changing what it decides — so treat a change in
the rates as a real finding rather than as drift.

### 3. Decide about `examples/copilotkit/ui/package-lock.json`

14,839 lines — about three quarters of what PR #55 shows. Keeping it makes the
demo reproducible; ignoring it makes the PR reviewable. This is the cheapest
thing that changes how #55 reads.

## For `main`, not for here

What the demo turned up that is library work rather than demo work. Each is a
PR to `main` and a rebase here second, the way the other five went; none of
them blocks the sweep, and none is a reason to touch `gandalf/` on this
branch. Four have gone that way already — see *Done*.

**Several functional tests arrange state with `seed_state()`** and raw state
lists where filling the run with a `RunDriver` would do. Not all of them —
`seed_state`'s stated purpose is arranging what the request cycle *cannot*
produce, and a driver produces only legitimate states. Ten call sites across
three files, and every one of them a library test rather than a demo one, which
is why it was in the wrong document until now.

## Done

- **The driver reads and writes a whole placement** — five PRs to `main`,
  [#64](../../pull/64) `describe()` in one walk instead of two,
  [#69](../../pull/69) `placements()`, [#66](../../pull/66) `open_file()`,
  [#67](../../pull/67) `submit(files=...)`, and [#68](../../pull/68) the
  schema note that had been telling a caller to send a file the one way
  that raises. What started as "reading the
  metadata costs a second walk" turned out not to be about walks. `metadata()`
  dropped the steps that recorded nothing, so it could not tell a person's
  answer from an unanswered step, and the demo's `edit_step` read the run
  three times to reconstruct what neither mapping could say alone. A placement
  has three parts; the driver exposed one and a half.
  - It also surfaced a bug nothing had hit: `cleaned_data` for a `FileField`
    is an open upload, so `describe(json_safe=True)` — the call both adapters
    make on every tool call — raised `TypeError` on any run whose file step
    had been answered. Worth remembering as the shape of thing 100% coverage
    does not catch: every line ran, on runs that had no files in them.
  - `metadata()` is gone rather than deprecated, so anything still calling it
    fails loudly. The demo's `edit_step` is the one caller and is now three
    lines and one read.
- **The evaluation keeps its own evidence** — `fill()` writes the run to
  `runs/` the way the browser path always has. It paid a real model and
  threw the transcript away, which twice meant re-running a sweep to
  recover something it had already had in hand. The privacy question it
  was waiting on answers itself: the rule about not logging answers is
  about a *person's* answers, and every answer in a scenario is an
  invented company at an invented address. `runs/` is gitignored.
- **The demo's tests run in CI** — `coverage-functional` installs the `agents`
  group, so the functional job goes from 393 passed and 3 skipped to 408 and
  none. The two obvious fixes were not equal: a job running `just test-agents`
  would have left `test_hybrid_handoff.py` out, because that recipe names its
  files and was never told about the file its own commit added. Taking the
  whole directory instead cannot go stale that way — a fourth suite needing the
  group is picked up by existing config. `test-agents` was fixed too, but it is
  a convenience now rather than the thing being trusted.
- **The driver, extracted to `main`** ([#59](../../pull/59)) — a fresh branch
  off `main` holding the final state of the library files, not a cherry-pick.
  The history here is not separable: nearly every commit touching `gandalf/`
  also touches `examples/`. The four `test_driver_journeys.py` tests that drive
  `examples/insurance.py` stayed behind, because `main` has no `examples/`
  package at all — its examples live in `tests/testapp/readme_examples.py`.
- **`WizardDriver` → `WizardTestDriver`** ([#60](../../pull/60)) — a naming
  problem rather than a duplication one, and worth recording because the
  obvious answer was wrong. The two share no code: `testing.py` pokes
  `SessionStorage` directly and goes through the test client; `RunDriver` never
  touches storage and skips HTTP deliberately. One proves the stack, the other
  is the non-browser path in production, so consolidating either into the other
  would delete the reason it exists. `Test` is the right half to add — not
  because it is the one used in tests, since `RunDriver` is used in tests too,
  but because it takes a `django.test.Client` and cannot work without one. The
  `wizard_driver` fixture kept its name: roughly 340 uses against 2 of the
  class name.
- **The driver's policy off the viewset** ([#61](../../pull/61)) — see
  *Decided*.
- **JSON-safe answers** ([#62](../../pull/62)) — both adapters had grown the
  same four-line helper independently, and it was the only function they had in
  common. Of the twelve places they wrapped, nine were wrapping things that
  were already JSON.
- **Metadata for the observer** ([#63](../../pull/63)) — required argument, no
  default and no compatibility shim, because there is one known user. Worth
  re-checking if that changes: an observer runs *inside the walk*, so a stale
  signature does not fail on upgrade, it fails in the middle of somebody's
  journey on the request meant to store their answer.
- **`answers()` could not be fed back into `submit()`** — fixed at the driver's
  door, which is the only door a non-string can enter through. Worth recording
  that the original diagnosis was wrong: nothing raised at `submit()`. The
  `date` was stored happily and the run only failed when its state was
  *written*, by which time nothing could say which answer caused it.

## Working on this branch

Two conventions that are not visible from the code.

**Five commits, and each one builds.** The branch is deliberately squashed
into one commit per idea — the wizard, the toolset, the hosted demo, the
evaluation, the documents — in dependency order, and the suite passes at every
one of them (989 → 995 → 1,004 → 1,004 → 1,004). When `main` moves and this
has to change with it, **fold the change into the commit that owns the file**
rather than appending a sixth. A trailing "adapt to the library change" commit
is the history-that-lies the squash existed to remove: the adapters should read
as though they were written against the current API, because there is no
released version where they were written against anything else.

`git rebase -i main`, `edit` the target commit, `git checkout <tip> -- <file>`,
amend, continue. Check the working tree after every `rebase --continue`: a
conflict there is silent until the next `commit --amend` swallows the following
commit into the current one, which has happened.

**No merge commits.** `main` is linear and PRs are merged with `--rebase`,
which preserves the commit message as written rather than replacing it with the
PR body.

**Keep `git diff main -- gandalf/` empty.** If a change wants to touch the
library, it is a PR to `main` first and a rebase here second. Five have gone
that way; the branch is better for it every time.

**The venv prunes.** `uv run --group agents ...` installs the agents group and
*removes* the lint group, which takes `pre-commit` with it and makes the next
`git commit` fail with `No module named pre_commit`. Use
`uv sync --all-groups` once and `uv run --no-sync ...` after that.

## Measurements

**Taken at `6b6e33d` — treat the rates as history, not as the current state of
the branch.** See *Re-run the whole evaluation*.

Sonnet 5, 5 repeats per scenario, $1.93; Haiku 4.5 the same for $0.58.

- Front-loading works: 0 questions when the context has the answers, exactly 1
  when it does not — and that one question asks for everything missing at once.
- Sonnet held every boundary 5/5 except consent (4/5, now structural).
- Haiku is 3.3× cheaper and held consent 5/5, but handed back only 1/5 in two
  scenarios and asked unnecessary questions 3/5 — worse at exactly the things
  the design exists for. Protocol discipline, not cost, is the deciding factor.
- `just agent-cost` reports what describing a wizard costs an agent: 1,524
  tokens for the insurance wizard, of which the biggest single entry is the
  *switch* (463) — an agent is told about every arm it might land in, so
  branching costs more to describe than to walk.

## Running it

```
just test              # 1,004 with the agents group, no network, no model
just agent-eval 5      # real model, ~$1.93, five repeats
just agent-eval 1 cover   # one scenario by name fragment
just agent-cost        # token weight of the wizard; generates nothing
just bench
```

`just` loads `.env`; a bare `uv run` does not, and a script that resolves the
model without it silently gets pydantic-ai's canned `test` model. That cost an
hour of chasing phantom failures — if a probe reports nonsense arguments like
`step: "a"`, that is what happened.

**A green local run does not mean a green CI run**, and this branch has proved
it twice, in both directions. A developer who has ever run `just test-agents`
has `pydantic-ai` in their venv permanently: first that made three suites pass
locally and error on import in CI, and then — once they were guarded — it made
them pass locally and *not run* in CI while the branch was broken.

The second of those is why `coverage-functional` installs the `agents` group.
Between them the two coverage jobs now run every test:

```
just coverage-unit          # 596
just coverage-functional    # 408, none skipped
```

`just test-django` still installs only the default groups, so the three suites
skip there; it varies the Django version, which is not what they measure. To
reproduce a default-group venv exactly — the one that hid the breakage —
`uv run --exact --group dev pytest`. The `--exact` is the whole point: without
it the extra groups already in the venv come along.
