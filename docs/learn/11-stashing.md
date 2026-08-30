# Chapter 11 — Stashing: leave and come back

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

    def done(self, run):
        SessionStashStore(run.context).put(
            "contact", run.stash(label="contact")
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

Inside `done()`, `run.stash()` returns a small JSON-safe payload of
the run's answers. The payload is yours — a model field, the session,
wherever your bigger flow keeps its pieces; `SessionStashStore` is the helper
for the common case. To re-open it, `resurrect(request, payload)` seeds a
brand-new run from the payload and returns the URL to send the user to; they
land in the ordinary wizard UI with every answer pre-filled, edit whatever
they need, and `done()` fires again for the new run when they finish.

Three things are worth holding onto:

- **It is a fresh, ordinary run**, and every answer is re-proved. A payload
  is trusted no further than a live session's own state.
- **Re-opening is edit-and-re-save.** Every answer already validates, so the
  *next* successful submission — including an edit to step one — walks
  straight to the end and fires `done()` again. A review step does not gate
  that; what it gives you is somewhere to *land*.
- **Same-shaped wizard only.** Stored answers align with the tree
  positionally. The `label` is the guard rail: stamp it at stash time, pass
  `expected_label` at resurrect time, and bump it when a deploy reshapes the
  wizard.

What rides in the payload (metadata) and what does not (uploaded files), and
what happens to a required file field on re-open, are in the
[Stashing reference](../reference/stashing.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/stash/ &nbsp;·&nbsp; **Source:** [`ch11_stash.py`](../../tests/testapp/readme/ch11_stash.py)

---

[← Chapter 10 — Completion hooks and run metadata](10-completion-hooks-and-metadata.md) · [Learn](README.md) · [Chapter 12 — Task lists: sections in any order →](12-task-lists.md)
