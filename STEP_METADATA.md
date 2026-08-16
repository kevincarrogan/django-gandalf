# Step metadata

**Status: built, and on `main`.** `RunDriver.submit(..., metadata=...)`,
`driver.placements()`, `WizardObserver.submission(step, accepted, metadata)`, and
a `meta` key beside each answer. It exists because a measurement found a hole
that no amount of prompting closes.

It briefly included a `WizardViewSet.may_edit_step()` hook, which
[#61](../../pull/61) removed — see *Shape*. The metadata is the capability;
the rule built on it belongs to whoever owns the domain.

## The measurement

The CopilotKit demo lets a person and an agent share one run: the agent fills,
the person reviews, and control passes back and forth. On 2026-08-15 a scenario
was added for the obvious hybrid case — the person changes an answer, then asks
the agent for something else.

1. The agent filled the coverage step with a £500 excess.
2. The person lowered it to £250, in the form, the way the demo intends.
3. The person asked the agent to add cyber cover.
4. The agent added cyber — and set the excess back to £500.

It failed 5 times out of 5. The tool log shows two calls:

```
edit_step  {"step": "coverage", "data": {"cover_types": ["property", "cyber"]}}
edit_step  {"step": "coverage", "data": {"excess": "500"}}
```

The first is a correct minimal edit. The second is deliberate: the person said
"£500 excess" in their opening message, the run says £250, and the agent
repairs what looks to it like drift. It then reported "cyber cover is added"
and said nothing about the excess.

**This is the important part.** The first attempted fix made `edit_step` merge
changed fields over stored ones rather than replacing the step wholesale. That
was a real improvement — the agent immediately started sending minimal diffs —
and it did not help at all, because the failure is not carelessness. Any
instruction to leave stored answers alone fights the same instinct that makes
the agent correctly fix genuine mistakes elsewhere, and a rule in prose is
exactly what we watched split 4–1 on the consent boundary the same day.

The agent is not missing an instruction. It is missing a fact: nothing in the
system records that a person put £250 there. That fact is what this proposes to
add.

## What it is, and what it is not

**Step metadata is a mapping carried with a placement and stored beside the
answer.** Who placed it, how, and anything else the application wants to park
against a step.

**It is not the step's `context`.** Context is declaration data — attached at
`.step(Form, name="email")`, part of the tree, identical for every run of the
wizard. Its staticness is load-bearing: the tree is a pure function of the
wizard plus stored state, and expanded steps are rebuilt on every walk, which
is why `RunDriver` claims steps by name rather than by object identity.
Anything parked on a rebuilt declaration evaporates.

The two have different lifetimes, so they get different names. `context` was
already overloaded once — there is an `ImproperlyConfigured` guard telling
people `context=` is not how a step's context is passed — and reusing the word
for a per-run channel would repeat that mistake at a larger scale.

## Shape

The seams that moved, and how far each one actually went:

- **Placement.** A submission gains an optional mapping alongside the answers.
  `RunDriver.submit(data, step=..., metadata=...)`, and the same on the walk
  the viewset performs.
- **The driver marks itself.** `RunDriver` knows it is not a person, so it sets
  a well-known key by default. Application code overrides or adds to it. This
  is what makes the guarantee free rather than something every adapter has to
  remember.
- **Storage keeps it beside the answer**, so it survives the run and travels
  with dormant branch-arm memory the way answers already do.
- **Reading it back.** `driver.placements()`, keyed by step name: every
  answered step, carrying its answers, its files and its metadata from one
  walk. This started as `driver.metadata()` and was replaced in
  [#69](../../pull/69), because a mapping of metadata alone dropped the steps
  that recorded nothing and so could not tell "a person answered this" from
  "nobody has" — the distinction the whole feature exists to make. `describe()`
  was the other candidate and did not get it: a description is about where the
  run *is*, and metadata is about every answer in it.
- **The observer is told it.** `WizardObserver.submission(step, accepted,
  metadata)`, in [#63](../../pull/63). This was the last seam to move and it
  went further than proposed: no compatible signature, no shim. The argument is
  required, because the walk always passes one, and there is one known user. If
  that changes, note *where* the failure would land — an observer runs inside
  the walk, so a stale signature does not fail on upgrade, it fails in the
  middle of somebody's journey.
- **The policy that motivated it.** ~~`WizardViewSet.may_edit_step()`.~~ Built
  in, then taken out again in [#61](../../pull/61), and the reason is the most
  useful thing in this document. The hook was handed
  `(bound_wizard, step, submission)` at the moment of the walk — every one of
  which a caller already holds *before* it calls `submit()`. So it earned
  nothing, while putting a method that only a driver ever consults onto the
  class that serves wizards over HTTP, where nobody reading it could tell what
  it was for. The rule is three lines in the demo's `edit_step`, asked of
  `driver.placements()`. **Metadata is the capability; the policy is the
  application's.**

## What it cost

Far less than this document first claimed, and the correction is worth
recording. It said every `WizardStorage` implementation would change and
durable users would need a migration. Neither was true: storage persists
`State` opaquely and never inspects an entry, and `visit_step` already writes a
sibling key the same way (`files`). So the answer rides as `meta` beside
`step`, no storage implementation changed, and a run stored before the feature
existed reads fine — a missing key is no metadata.

One real break: a `cursor_walker_class` written from scratch now receives a
`metadata` keyword. Subclassing `CursorWalker` is unaffected.

## Alternatives considered

- **Application-side table, keyed by run and step, populated from the
  observer.** No core change, but the observer is constructed as
  `observer_class(run_id)` and told the step declaration and outcome — it does
  not know the actor either. Something still has to cross the seam, so this
  only moves the problem.
- **Put it in the answers dict.** Pollutes `cleaned_data` with things no form
  declared, and collides with field names.
- **A coarse `may_edit_answered_steps` flag, no provenance.** Cannot tell the
  agent correcting its own earlier answer from the agent overwriting a
  person's, and the first is required — it is the retry loop after a validation
  failure.
- **Leave it to adapters.** `RunDriver` is core and hands out the capability,
  so every adapter would reimplement the guard and a third-party one would
  silently omit it.

## Open questions

- ~~Does re-answering a step replace its metadata or accumulate it?~~
  **Decided: replace**, and pinned by
  `test_re_answering_a_step_replaces_its_metadata`. An audit trail wants
  accumulate, and can have one — the observer is told every placement as it
  happens, which is a better shape for a trail than a growing key in the state.
- What may it hold? JSON-safe values only, which the `Metadata` alias says and
  nothing enforces. No size bound. Still open, and still theoretical: it is
  stored with the state, so a caller stuffing it will find out through the
  session cookie limit rather than through us.
- ~~Does the person's edit lock the field or merely mark it?~~ **Decided: the
  step, whole.** Somebody submitting a form affirms everything on it, so once
  they have answered a step all of it is theirs — including the parts they left
  alone. The agent is redirected rather than blocked: it says what it would
  change and lets them change it, which is the handover the demo is built on.
  The cost is real — it cannot add cyber cover to a step somebody has touched,
  even though that field was never theirs to begin with.
- Whether an application wanting field-level policy can express it. It can
  compare the submission it is about to make against `placements()`, which is
  everything the removed hook was given and in one read. What neither
  can recover is which fields a person *changed* as opposed to submitted —
  that is a fact about a form post, and it is gone by the time anything is
  stored.

## Related

- ~~`answers()` returns cleaned values that `submit()` cannot accept.~~ Fixed:
  `submit()` reduces what it is given to the values a browser would have
  posted, so the round trip holds.
- The scenario that found this is `the person changed an answer first` in
  `examples/scenarios.py`; it stays red until something here lands.
