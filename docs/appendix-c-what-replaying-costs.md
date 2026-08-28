# Appendix C — What replaying costs

Gandalf re-proves stored submissions rather than trusting a recorded position.
The rule is small enough to keep in your head:

> The walk runs a form's `clean()` **once per completed step per HTTP
> request** — and each step whose answers the request *reads back* costs one
> more.

So with `k` answers stored, a request costs `k` replays, and a POST costs one
more for the answer being submitted; completing an `N`-step run costs `N²`
validations end to end, spread over `2N` requests.

Reading answers back is the second clause. Proving an answer and displaying
it are separate passes over the same form — the walk dispatches the step's
view to prove it, `RuntimeStep.form` reconstructs one to hand back
`cleaned_data` — so a check-your-answers page costs **two validations per
answered step**. A branch predicate that dereferences an earlier answer is
charged the same way, on every request that resolves its arm.

Within one read, the form is built once per step however many fields you
render from it. What does add up is reading *again*: `path` builds fresh step
nodes on each access, so iterate the steps you hold rather than re-reading
`wizard.path` per field. Outside a render — in `done()`, a completion page, or
a driver reading a run — every `path` access walks: looking each of `k` steps
up separately costs `k²` validations in that one request, where iterating
once costs `k`.

**The number that matters is not `N`, it is how many of your steps are
expensive** — each completed step is validated once per request whether the
user is on step 5 or step 29, so `N²` only bites when *most* steps do real
work in `clean()`.

Measured on a 2023 laptop with `just bench`, for a linear wizard:

| steps | `clean()` | whole run | final POST |
|---|---|---|---|
| 30 | free | 72ms | 1.1ms |
| 30 | 5ms on *every* step | 6.7s | 222ms |

Gandalf's own share is about a millisecond per request at 30 steps;
everything else is your forms. If expensive `clean()` becomes a problem, move
the work into `done()` (where it runs once), store a cheaply-recheckable
token, or accept that some checks belong only at submission time. `just
bench` measures your own shapes, and `tests/functional/test_walk_cost.py`
pins the counts so they cannot regress unnoticed.

A hub row (chapter 11) deliberately pays none of this: two storage reads and
a `reverse()`, never a walk. That is why what a section decided is written to
`store.data` at completion rather than read out of a stash at render time.

---

[← Appendix B — Configuration](appendix-b-configuration.md) · [README](../README.md) · [Appendix D — Coming from `django-formtools` →](appendix-d-coming-from-django-formtools.md)
