# Proofs

`run.proof()` — what a step's dispatch established, kept only while the
answers behind it are unchanged. For a check that cannot be performed
twice.

```python
from gandalf.runtime import StepProof
```

`StepProof` is the bag `run.proof()` hands back; you rarely name the class.

---

## The constraint this exists for

> A step's `clean()` must be a pure function of its submission and durable
> state.

Gandalf stores submissions rather than a position and re-proves every one
of them on every request. That is what makes an edit to an early answer
re-decide everything after it, and it assumes validating an answer twice
gives the same result twice.

Some checks are not like that. Proving them *consumes* them:

- a one-time password — the device's counter moves on
- a card authorisation — you do not authorise twice
- a claimed reference number, a redeemed voucher, a nonce

Give one of those to a plain step and the wizard does not walk at all. The
POST that submits the answer dispatches it, the request after that
dispatches it again, and the second one fails. The user is parked at a step
they have already passed, with no way through and nothing on the page to
explain it.

A proof is where the durable half of such a check goes: perform it once,
record what it established, and re-check *that* on every later dispatch.
Validation still runs, the step still produces `cleaned_data`, and the walk
still decides where the user is. The step is handed what it needs to
succeed again — not excused from trying.

---

## Reference

### `run.proof(name)`

**Parameters** — `name`: a step name.

**Returns** a `StepProof` for that step, scoped to the answers proved before
it on the route in hand.

Reads the same from three places, because all three hold the same prefix:
inside the step's own dispatch (where the step is not on the walked prefix
yet), inside a later step's, and in `done()`. A name no step on the route
carries is not an error — it is a bag nothing else reads.

**Cost** — one pass over the stored submissions before the step. Not
`path`, which would build a form per answered step on a step that reads its
proof on every dispatch. See [Walk costs](walk-costs.md).

### `StepProof`

A [`MetadataBag`](run-metadata.md#metadatabagread-write-path) over the
`proofs` bucket of the run's metadata envelope, with one addition: every
write is stamped with a digest of the answers before its step, and a read
whose digest no longer matches sees an **empty bag**.

```python
{
    "run":    {"application_id": 42},
    "steps":  {"referees": {"emailed": True}},
    "proofs": {"token": {"digest": "9f86d0…", "data": {"token": "123456"}}},
}
```

Everything else is `MetadataBag`'s: JSON-safe values, deep copies out, only
assignment writes through, `update()` for several keys in one write.

### What voids a proof

| Change | The proof | Why |
| --- | --- | --- |
| an answer *before* the step changes | **void** | it was established behind answers that are no longer there |
| a branch ahead of it takes a different arm | **void** | same reason: the prefix is different |
| the step's own answer changes | stands | a proof is about what came *before* its step; the new submission is a new claim, and the form checks it |
| an earlier answer changes and changes back | stands | the digest describes the answers, not how many times they moved |
| the run is stashed and resurrected | **not carried** | a stash carries answers to a different run; see [Stashing](stashing.md) |

The first row is the whole point, and it is why this is not a convention
over `metadata.for_step()`. A durable note saying "this token is verified"
still stands after the user goes back and picks a different device — so the
step waves through a token proved against something else. Written by hand
that invalidation is a line everyone forgets; here it is the default.

If you know React hooks: a proof is a memo and the digest is its dependency
array. The difference is who writes the deps. React has you list them and
lints the list when it is wrong; a proof takes *every* answer before its
step, always. The asymmetry decides it — a dep left off is a check that
should have been re-performed and was not, and one left on is a check
performed once more than it had to be. Only one of those is a security bug.

The cost of that choice is the same one React spent years on: over-eager
invalidation. An answer three steps back that has nothing to do with the
check still voids it, and the user re-enters a code for no reason they can
see. If that ever needs fixing the shape is already known — a way to say
which earlier answers are *reactive*, listed explicitly at the step, never
inferred. Until something real needs it, the safe default is the whole
prefix.

Two other things the comparison gets right. The digest is taken over stored
submissions, not `cleaned_data` — the equivalent of React's advice to keep
unstable objects out of a deps array, since a model instance has neither a
stable identity nor a JSON form. And losing a proof degrades rather than
corrupts: the check is performed again and, for a consuming one, fails
loudly and parks the user. Nothing is silently waved through.

### What a proof is not

- **Not a way to skip validation.** The form still runs, still cleans, still
  can reject. Nothing is trusted stale, and arriving at a step is still the
  authorisation.
- **Not durable.** For a fact that must survive an earlier edit — a record
  this run opened, an invoice it raised — use
  [`run.metadata`](run-metadata.md). The two live in adjacent buckets and
  cannot tread on each other.
- **Not a cache.** It holds what a check established, not what a lookup
  returned. Caching an expensive-but-repeatable lookup is
  `metadata.for_step()`'s job, and voiding on an earlier edit is usually
  what you want there too — in which case a proof is the better fit anyway.

---

## Usage

### A check that consumes what it checks

The form takes what was already proved and re-checks it, instead of
performing the check again:

```python
class OneTimePasswordForm(forms.Form):
    token = forms.CharField()

    def __init__(self, device, already_proven=None, **kwargs):
        super().__init__(**kwargs)
        self.device = device
        self.already_proven = already_proven

    def clean_token(self):
        token = self.cleaned_data["token"]
        if token == self.already_proven:
            return token                       # a re-check: free, and safe
        if not self.device.verify_token(token):  # the act: happens once
            raise forms.ValidationError("That code is not valid.")
        return token
```

The step reads the proof on the way in and records it on the way out. Both
are unconditional — the walk replays this step on every later request, and
writing the same proof again behind the same answers is a write of what is
already there:

```python
class OneTimePasswordStepView(StepFormView):
    form_class = OneTimePasswordForm
    template_name = "signin/token.html"

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "device": self.request.run.metadata["device_id"],
            "already_proven": self.request.run.proof("token").get("token"),
        }

    def form_valid(self, form):
        self.request.run.proof("token")["token"] = form.cleaned_data["token"]
        return super().form_valid(form)
```

Change the phone number two steps earlier and the proof falls away on its
own: the code is verified again, the device rejects a code it has already
seen, and the user is parked at the token step to enter a fresh one. Which
is exactly right.

### A side effect that must happen on arrival

Sending the code is the same shape as proving it — do it once, but do it
again if what it was sent about changes:

```python
class SendCodeStepView(StepFormView):
    form_class = ConfirmSendForm
    template_name = "signin/send.html"

    def get_initial(self):
        proof = self.request.run.proof("send-code")
        if not proof.get("sent"):
            send_code(self.request.run.path.find_step(name="phone"))
            proof["sent"] = True
        return super().get_initial()
```

Written against `metadata.for_step()` this needs a guard comparing the
number it last sent to, by hand, and gets it wrong the day a second thing
starts mattering. The proof's scope is every earlier answer at once.

### The whole thing, ported from a real wizard

`tests/testapp/from_formtools/two_factor.py` is django-two-factor-auth's
setup wizard translated whole — a registry deciding the shape per request, a
minted key in `run.metadata`, and the code step above. It is the case this
primitive was built for, and
[Coming from django-formtools](../learn/coming-from-django-formtools.md)
walks through what it replaced.

### Reading it at the end

```python
def done(self, run):
    verified = run.proof("token")["token"]
    ...
```

`done()` holds the same answers before the token step that the step's own
dispatch did, so the proof reads back there unchanged.

---

## Troubleshooting

### My proof always reads empty

Two different causes, and `repr()` tells them apart:

```python
>>> run.proof("token")
StepProof('token', nothing proved)                              # never written
StepProof('token', voided by a change to the answers before it)  # written, then voided
```

*Nothing proved* means the write is not happening — see the next entry.
*Voided* means something before the step changed between the write and the
read; check whether an earlier step is being re-answered, or a branch ahead
of it is resolving to a different arm. If the fact is meant to survive that,
it is not a proof: use [`run.metadata.for_step()`](run-metadata.md).

### My check still runs twice on the POST that makes it

The proof is written in `form_valid()` and read in `get_form_kwargs()`, and
a POST dispatches the step twice — once placing the answer, once on the
walk that follows. Both halves have to be there. Reading the proof without
writing it, or writing it without reading it back, leaves the check running
every time.

### A resurrected run asks for the token again

Working as intended. A stash carries answers to a *different* run, and
carrying the proof would assert that a consuming check made in the old run
still stands in the new one. Take the proof out of `done()` and into
whatever the stash is seeding if the fact genuinely outlives the run.

### `TypeError: Object of type ... is not JSON serializable`

Same rule as the rest of a run's storage: proofs hold JSON-safe values.
Record the identifier, not the object.

---

**Learn:** [Chapter 10 — Completion hooks and metadata](../learn/10-completion-hooks-and-metadata.md) · **Related:** [Run metadata](run-metadata.md), [Walk costs](walk-costs.md), [Step views](step-views.md), [Stashing](stashing.md)
