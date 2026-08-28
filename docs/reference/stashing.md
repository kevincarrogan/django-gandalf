# Stashing

`BoundWizard.stash()` and `WizardViewSet.resurrect()` — take a run's
answers out as a payload, and seed a fresh run from one later.

```python
from gandalf.runtime import STASH_VERSION, InvalidStash
from gandalf.storage import SessionStashStore, StashNotFound
from gandalf.types import Stash
```

`InvalidStash` is also re-exported from `gandalf.wizard`.

---

## Reference

### `BoundWizard.stash(label=None)`

A caller-owned, JSON-safe payload of this run's answers. Callable inside
`done()` — completion tears the run down only after `done()` returns, so
the final state is still readable there.

**Parameters**

- `label` — an opt-in guard, stamped into the payload when given. State
  aligns with the wizard tree positionally, so a payload should be refused
  when it was stashed by a differently-shaped wizard; `resurrect()` checks
  it against `expected_label`.

**Returns** a `Stash` (a plain dict):

| Key | Present | Holds |
| --- | --- | --- |
| `version` | always | `STASH_VERSION` (currently `1`) |
| `state` | always | the stored state list, stripped as below |
| `meta` | when the run's metadata bag is non-empty | the whole bag envelope, as `get_run_metadata()` returns it |
| `label` | when `label` was given | the label |

What the state keeps and drops, at every depth — active and dormant branch
arms, the legacy bare-list branch shape, and expansion sub-lists:

- Each step's submission (`"step"`) is kept verbatim, including interior
  holes (`{"step": None}`).
- Placement metadata (`"meta"` on a step entry) is kept.
- `"files"` refs are stripped. A stash outlives the run but the bytes do
  not — completion deletes them — so a payload must not carry refs to files
  that no longer exist.
- A `csrfmiddlewaretoken` stored by an earlier version is swept out.

The stored state is never mutated; the payload is built from new
structures.

### `BoundWizard.resurrect(payload, expected_label=None)`

Seed a fresh run from a payload and return the new run id. Storage-only:
the wizard need not be resolved yet. The payload is vetted before any run
is created, so a refusal leaves nothing behind. `state` and `meta` are
deep-copied in, so resurrecting one payload twice gives two fully
independent runs and leaves the payload untouched. Nothing is walked here.

**Raises** `InvalidStash` when:

- `payload` is not a dict, or its `state` is not a list;
- `payload["version"]` is not `STASH_VERSION`;
- `expected_label` is given and `payload.get("label")` does not equal it
  (a payload with no label fails this too).

Most callers want the viewset classmethods below, which build the
`BoundWizard` for you.

### `WizardViewSet.reopen(request, payload, expected_label=None, **url_kwargs)`

A fresh run seeded from `payload`, returned as a `BoundWizard` rather than
redirected to. The wizard is resolved *after* seeding, so a dynamic
`get_wizard()` reads the state the payload just supplied. `url_kwargs` are
mount-prefix context (a tenant slug), forwarded into URL reversing.

`run_started()` does **not** fire: a run seeded from a stash is a
continuation, and its metadata bag comes back with it.

**Raises** `InvalidStash` before any run is created.

### `WizardViewSet.resurrect(request, payload, step=None, expected_label=None, **url_kwargs)`

`reopen()` followed by `entry_url(step)`: seed the run and return the URL
to send the user to.

**Parameters**

- `step` — the URL segment of the step to land on; walks nothing. Without
  it the new run is walked once and the URL is the cursor's step, or — for
  a payload whose every answer validates — the first step on the active
  route.
- `expected_label`, `url_kwargs` — as `reopen()`.

**Returns** a step URL, never the bare run URL. `None` only when the
viewset has no URL reverser, which cannot happen through this door.
Falls back to the bare run URL for a wizard with no steps at all.

### `InvalidStash`

`ValueError` raised by `resurrect()` and `reopen()` for a payload that
cannot seed a run: not a stash envelope, an unsupported version, or a label
that does not match. A hub turns it into `stash_unusable()`; by hand,
catch it alongside `StashNotFound` and start fresh.

### `SessionStashStore(context, home=None)`

Keyed payloads in the session — the shipped home for a stash a caller
keeps by hand, and what a hub keeps its members' stashes in. Server-side,
so a payload cannot be tampered with in transit.

**Parameters**

- `context` — the `WizardContext`.
- `home` — optional `(read, write)` pair of callables returning the mapping
  to keep payloads in. Without it the store uses its own session key.
  `read()` must return the mapping or an empty one without creating
  anything, so a render cannot dirty the session; `write()` returns it,
  creating it on the way. `SessionJourneyStore` passes the `"stashes"`
  mapping inside a journey's record, which is how a hub's stashes are this
  class too, scoped to the journey and torn down with it.

**Attributes** — `SESSION_KEY = "gandalf_stashes"`.

| Method | Contract |
| --- | --- |
| `put(key, payload)` | Store `payload` under `key`, replacing any existing stash |
| `get(key)` | The stash under `key`, or raise `StashNotFound` |
| `has(key)` | Whether a stash is held under `key`, without an exception to catch |
| `pop(key)` | Remove and return the stash under `key`, or raise `StashNotFound` |
| `delete(key)` | Forget the stash under `key`. Idempotent |
| `keys()` | The stored keys, in insertion order |

Every write calls `context.session_changed()`.

### `StashNotFound`

`LookupError` raised by `get()` and `pop()` when a key names no stored
payload — never stashed, already popped, or lost with an expired session.

### What resurrection guarantees

- **A fresh, ordinary run.** Standard URLs, editing, escapes. The original
  run's tombstone is untouched, so the once-per-run `done()` guarantee
  holds: re-completion fires `done()` for the *new* run.
- **Every answer is re-proved.** A payload is trusted no further than a live
  session's own state. A tampered answer parks the cursor on that step,
  rendered with its errors, rather than completing silently.
- **Metadata rides along.** A re-opened run still knows which record it
  created and does not open a second one; `run_started()` does not fire.
- **Files are stripped.** The step's other answers survive. An *optional*
  file field validates without its upload; a *required* one parks the
  cursor at that step, which is where the user has to re-upload.
- **A step URL, never the run URL.** A stashed run's answers all validate,
  so a GET of the bare run URL would walk straight to completion and fire
  `done()` before the user touched anything.
- **The next submission re-fires `done()`.** Every answer already validates,
  so the next successful submission — including an edit to the first step —
  walks to the end. A review step does not gate that; it gives the user
  somewhere to land (`step="review"`), and `SummaryMixin` drops the step
  doing the summarising from its own rows.
- **Same-shaped wizard only.** Stored answers align with the tree
  positionally. Stamp a `label` at stash time, pass `expected_label` at
  resurrect time, and bump the label when a deploy reshapes the wizard.

---

## Usage

### Save on completion, re-open later

```python
from django.http import HttpResponse
from django.shortcuts import redirect

from gandalf.context import WizardContext
from gandalf.runtime import InvalidStash
from gandalf.storage import SessionStashStore, StashNotFound
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ContactDetailsViewSet(WizardViewSet):
    url_name = "contact"
    template_name = "grants/step.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="email")
    )

    def done(self, bound_wizard):
        SessionStashStore(bound_wizard.context).put(
            "contact", bound_wizard.stash(label="contact-v1")
        )
        return HttpResponse("Contact details saved.")


def reopen_contact_details(request):
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.get("contact")
        url = ContactDetailsViewSet.resurrect(request, payload, expected_label="contact-v1")
    except (StashNotFound, InvalidStash):
        return redirect("contact")  # nothing usable — start fresh
    return redirect(url)
```

### Keeping the stash on a model

```python
from django.shortcuts import get_object_or_404, redirect


class BudgetViewSet(WizardViewSet):
    url_name = "budget"
    ...

    def done(self, bound_wizard):
        application = Application.objects.get(pk=bound_wizard.metadata["application_id"])
        application.budget_stash = bound_wizard.stash(label="budget")
        application.save(update_fields=["budget_stash"])
        return redirect("application-overview", pk=application.pk)


def edit_budget(request, pk):
    application = get_object_or_404(Application, pk=pk, applicant=request.user)
    url = BudgetViewSet.resurrect(
        request, application.budget_stash, step="review", expected_label="budget"
    )
    return redirect(url)
```

`budget_stash` is a `JSONField`. The run that re-opens carries
`application_id` in its metadata, so `done()` finds the same record.

### Reading a re-opened run before sending the user in

```python
wizard = BudgetViewSet.reopen(request, payload, expected_label="budget")
total = sum(
    step.form.cleaned_data["amount"] for step in wizard.path.filter_steps(name="line")
)
return redirect(wizard.entry_url("review"))
```

`reopen()` hands back the run; `path` walks it once.

---

## Troubleshooting

### `InvalidStash: Stash label 'contact' does not match expected label 'contact-v2'`

The payload was stashed under an older label. That is the guard working:
the wizard's shape changed and the answers may no longer line up. Discard
the stash and start a fresh run, or migrate the payload's `state` by hand
if the change was additive.

### `InvalidStash: A stash payload is a dict with a state list`

`resurrect()` was handed something other than a `stash()` payload — a
model field that was never written, or the `state` list on its own. Store
and pass the whole payload.

### Re-opening a run fired `done()` straight away

The user was sent to the bare run URL. Every answer in a stash validates,
so the cursor is at the end and a GET there completes. Always send them to
what `resurrect()` returns, or to `entry_url(step)`.

### The user edited one field and the run completed

That is edit-and-re-save: after a resurrection every step is satisfied, so
any successful submission walks to the end. Land them on a review step
(`step="review"`) so they can look before re-submitting.

### The re-opened run asks for a file again

The stash dropped its file refs because completion deleted the bytes. A
required `FileField` parks the cursor there; make the field
`required=False` if a re-upload should not be demanded, or keep the file
somewhere permanent from `done()` and record where in the metadata bag.

### `StashNotFound` on the second visit

`pop()` removes the payload as it returns it. Use `get()` for a stash that
should stay re-openable, and `pop()` only when re-opening consumes it.

---

**Learn:** [Chapter 10 — Stashing: leave and come back](../learn/10-stashing.md) · **Related:** [`BoundWizard`](bound-wizard.md), [`WizardViewSet`](viewsets.md), [Storage](storage.md), [Run metadata](run-metadata.md), [Hubs](hubs.md), [Journey store](journey-store.md)
