# Chapter 9 — Completion hooks and run metadata

An application is a record in a database, not a string in a response. This
chapter opens one when the run starts, submits it when the run finishes, and
makes sure both happen exactly once.

```python
class RecordedApplicationViewSet(WizardViewSet):
    url_name = "readme-record"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def run_started(self, bound_wizard):
        application = Application.objects.create()
        bound_wizard.metadata["application_id"] = application.pk

    def done(self, bound_wizard):
        application = Application.objects.get(pk=bound_wizard.metadata["application_id"])
        answers = MergeCleanedData().reduce(bound_wizard.path)
        application.submit(answers["email"])
        return redirect("readme-received", pk=application.pk)

    def run_unavailable(self, bound_wizard, reason):
        if reason == "completed":
            return redirect("readme-received", pk=bound_wizard.metadata["application_id"])
        raise Http404("That application has expired.")
```

### `done()` runs exactly once

A run finishes the first time it is walked and every step is satisfied:
`done()` is called and the run is retired — its answers are dropped and a
small completion marker takes their place. After that, every request for it
is answered by `run_unavailable()` without reaching the wizard. So a stale
tab cannot submit twice, and a refreshed completion page cannot re-charge a
card. Put side effects in `done()` and they happen once. The marker is
written *after* `done()` returns, so a `done()` that raises leaves the run
intact and resumable.

`run_unavailable(bound_wizard, reason)` answers everything that cannot be
run — `reason` is `"completed"` or `"unknown"`. The default redirects to the
start URL; here a completed run goes to its own received page instead.

### `run_started()`: the once-per-run hook

A wizard's state is answers, and every answer is re-proved from scratch on
every request. That leaves nowhere to keep the other kind of fact a run
accumulates: the record it opened somewhere else. Nobody typed it, no form
validates it, and doing it twice is the bug.

`run_started(bound_wizard)` fires when a fresh run is minted, and only then.
Re-opening a stash (chapter 10) does not fire it — a re-opened run brings
its metadata back with it, so the record it created is already there.

### `bound_wizard.metadata`: what it remembers

A dict, readable and writable from anywhere holding the run — a step view, a
branch predicate, `done()`. Every write goes straight to storage, which is
the point: a walk persists nothing on a GET, yet a GET still replays every
step view, so a record id written into *state* during a GET would be thrown
away and the next GET would open a second record. The bag survives all of
that, survives completion (so `run_unavailable()` above can still name the
application), and rides along in a stash.

Two things to know before leaning on it: values must be JSON-safe, and only
*assignment* writes through — a read hands back a copy, so mutate-in-place
changes nothing. The full semantics are in the
[Run metadata reference](../reference/run-metadata.md).

### Storage

Everything above is session-backed by default. An application the applicant
comes back to over days needs somewhere better than a session, and Gandalf
ships no durable backend — that would mean models, migrations and a retention
policy. Instead `storage_class` on the viewset is a seam small enough to
swap; a worked, tested `ModelStorage` lives in the test app. The contract is
in the [Storage reference](../reference/storage.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/record/ &nbsp;·&nbsp; **Source:** [`ch09_records.py`](../../tests/testapp/readme/ch09_records.py) &nbsp;·&nbsp; **Reference:** [`WizardViewSet` hooks](../reference/viewsets.md)

---

[← Chapter 8 — File uploads](08-file-uploads.md) · [Learn](README.md) · [Chapter 10 — Stashing: leave and come back →](10-stashing.md)
