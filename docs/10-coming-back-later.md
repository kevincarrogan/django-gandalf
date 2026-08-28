# Chapter 10 — Coming back later

Completion is terminal — `done()` fires once and the run's answers are gone.
An application is not filled in one sitting, though: the contact details
should be saved *and* stay editable. That is a **stash**.

```python
from gandalf.storage import SessionStashStore, StashNotFound
from gandalf.wizard import InvalidStash


class ContactDetailsViewSet(WizardViewSet):
    url_name = "readme-stash"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
    )

    def done(self, bound_wizard):
        SessionStashStore(bound_wizard.context).put(
            "contact", bound_wizard.stash(label="contact")
        )
        return HttpResponse("Contact details saved.")


def reopen_contact_details(request):
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.get("contact")
        url = ContactDetailsViewSet.resurrect(request, payload, expected_label="contact")
    except (StashNotFound, InvalidStash):
        return redirect("readme-stash")  # nothing stashed — start fresh
    return redirect(url)
```

Inside `done()`, `bound_wizard.stash()` returns a small JSON-safe payload of
the run's answers. The payload is yours — a model field, the session,
wherever your bigger flow keeps its pieces; `SessionStashStore` is the helper
for the common case (`put` / `get` / `pop` / `delete` / `keys`), server-side
so it cannot be tampered with in transit. To re-open it,
`resurrect(request, payload)` seeds a brand-new run from the payload and
returns the URL to send the user to; they land in the ordinary wizard UI with
every answer pre-filled, edit whatever they need, and `done()` fires again
for the new run when they finish.

What resurrection promises:

- **A fresh, ordinary run.** Standard URLs, editing, escapes. Resurrecting the
  same payload twice yields two independent runs. The original run's tombstone
  is untouched, so the once-per-run `done()` guarantee holds: re-completion
  fires `done()` for the *new* run.
- **Every answer is re-proved.** A payload is trusted no further than a live
  session's own state — a mangled answer parks the run on that step with its
  errors rather than completing silently.
- **What the run did elsewhere comes back with it.** The metadata bag rides
  in the payload, so a re-opened run still knows which record it created and
  does not open a second one; `run_started()` deliberately does not fire.
  File refs are stripped: the bytes are deleted at completion. An *optional*
  file field sails through; a *required* one parks the run at that step for
  the user to re-upload.
- **A step URL, never the bare run URL.** A stashed run's answers all
  validate, so `resurrect()` lands the user on a step (`step="..."` to choose
  which; default is the first). The bare run URL of a run whose every answer
  validates would fire `done()` on a GET.
- **Re-opening is edit-and-re-save.** Every answer already validates, so the
  *next* successful submission — including an edit to step one — walks
  straight to the end and fires `done()` again. A review step does not gate
  that; what it gives you is somewhere to *land*, and `SummaryMixin` drops the
  step doing the summarising from its own rows so a review page revisited
  this way does not offer to change itself.
- **Same-shaped wizard only.** Stored answers align with the wizard tree
  positionally, so a payload only resurrects correctly against a tree shaped
  like the one that stashed it. The `label` is the guard rail: stamp it at
  stash time, pass `expected_label` at resurrect time, and bump the label when
  a deploy reshapes the wizard — a mismatch raises `InvalidStash` before any
  run is created.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/stash/ &nbsp;·&nbsp; **Source:** [`ch10_stash.py`](../tests/testapp/readme/ch10_stash.py)

---

[← Chapter 9 — Finishing, and what it leaves behind](09-finishing-and-what-it-leaves-behind.md) · [README](../README.md) · [Chapter 11 — A task list →](11-a-task-list.md)
