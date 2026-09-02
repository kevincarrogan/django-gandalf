# Walk costs

What re-proving a run costs, and where it adds up. Gandalf stores raw
submissions rather than a recorded position, and replays them through their
forms on every request.

---

## The rule

> The walk runs a form's `clean()` **once per completed step per HTTP
> request** — and each step whose answers the request *reads back* costs one
> more.

With `k` answers stored, a request costs `k` replays, and a POST costs one
more for the answer being submitted. Completing an `N`-step run end to end
costs `N²` validations spread over `2N` requests.

## Reading back

Proving an answer and displaying it are separate passes over the same form:
the walk dispatches the step's view to prove it, and
[`RuntimeStep.form`](run.md) reconstructs one to hand back
`cleaned_data`. So:

- A check-your-answers page ([`SummaryMixin`](summary.md)) costs **two
  validations per answered step**.
- A branch predicate that dereferences an earlier answer is charged one read
  on every request that resolves its arm.
- An `.expand()` builder that reads the count is charged the same way.

Within one read, the form is built once per step however many fields you
render from it — `RuntimeStep.form` is cached per step per request. What
adds up is reading *again*: `path` builds fresh step nodes on each access, so
iterate the steps you hold rather than re-reading `wizard.path` per field.
Outside a render — in `done()`, a completion page, a driver reading a run —
every `path` access walks: looking each of `k` steps up separately costs `k²`
validations in that one request, where iterating once costs `k`.

## What matters

The number that matters is not `N`, it is **how many of your steps are
expensive**. Each completed step is validated once per request whether the
user is on step 5 or step 29, so `N²` only bites when *most* steps do real
work in `clean()`.

Measured on a 2023 laptop with `just bench`, for a linear wizard:

| steps | `clean()` | whole run | final POST |
|---|---|---|---|
| 30 | free | 72ms | 1.1ms |
| 30 | 5ms on *every* step | 6.7s | 222ms |

Gandalf's own share is about a millisecond per request at 30 steps;
everything else is your forms.

## When re-proving is not a cost but a bug

Everything above is about how *much* work re-proving does. There is one
case where the problem is not the work:

> A step's `clean()` must be a pure function of its submission and durable
> state.

Some checks are not. Proving them consumes them — a one-time password, a
card authorisation, a redeemed voucher — so the second dispatch of the same
answer fails where the first succeeded. That is not a slow wizard, it is a
wizard that does not walk: the POST placing the answer dispatches the step,
the request after it dispatches the step again, and the user is parked at a
step they have already passed with no way through.

Put the durable half of such a check in a [proof](proofs.md): perform it
once, record what it established, re-check that on every later dispatch.
Validation still runs and still decides — the step is handed what it needs
to succeed again.

A check that is merely *expensive* and repeatable does not need this; the
tactics below are enough.

## Keeping it cheap

- Move expensive work into `done()`, where it runs once.
- Store a cheaply-recheckable token rather than re-running the check — a
  lookup result written to [`run.metadata`](run-metadata.md) is read
  back for free, and a [proof](proofs.md) is the same trick scoped to the
  answers it was established behind.
- Accept that some checks belong only at submission time.
- A [task list](tasklists.md) row deliberately pays none of this: two storage
  reads and a `reverse()`, never a walk. That is why what a section decided is written to
  [`store.metadata`](journey-store.md) at completion rather than read out of a
  stash at render time.

`just bench` measures your own shapes, and `tests/functional/test_walk_cost.py`
pins the counts so they cannot regress unnoticed.

---

**Learn:** [Chapter 1 — Steps and completion](../learn/01-steps-and-completion.md) · **Related:** [The run](run.md), [Proofs](proofs.md), [Summary](summary.md), [Task lists](tasklists.md)
