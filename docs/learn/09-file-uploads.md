# Chapter 9 — File uploads

An organisation uploads its governing document. Uploaded bytes cannot live in
the session, so Gandalf persists them through a companion
`WizardFileStorage`; the session carries only a small ref (storage key plus
original name, content type and size).

```python
class GoverningDocumentForm(forms.Form):
    document = forms.FileField(label="Your governing document")


organisation_details = ch04.organisation_details.step(
    GoverningDocumentForm, name="governing-document", label="Governing document"
)


class DocumentedApplicationViewSet(WizardViewSet):
    url_name = "readme-upload"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def done(self, run):
        document = run.path.find_step(name="governing-document")
        if document is None:
            return HttpResponse("Application received (no document needed)")
        return HttpResponse(f"Received {document.files['document']['name']}")
```

The step template just needs the usual `enctype="multipart/form-data"`. Here
`done()` does guard its `find_step()`, because an individual never sees the
document step — it is on the organisation arm.

On replay, Gandalf reopens each stored file and re-injects it into
`request.FILES` before re-validating the step, so validators see the same
value they saw originally. The bytes stay on the backend until something
asks for them — a plain `FileField` reads only the name and size, which the
ref already carries — so a run costs the same whether its uploads are a
kilobyte or a hundred megabytes. Editing respects keep-vs-replace per field,
and the run's files are cleaned up once `done()`'s response has rendered.

The default storage writes under a `gandalf/<run_id>/` prefix of Django's
default storage; point it elsewhere by subclassing `WizardFileStorage` and
passing it to `.configure(file_storage_class=...)`.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/upload/ &nbsp;·&nbsp; **Source:** [`ch09_uploads.py`](../../tests/testapp/readme/ch09_uploads.py) &nbsp;·&nbsp; **Reference:** [File uploads](../reference/file-uploads.md)

---

[← Chapter 8 — Escapes](08-escapes.md) · [Learn](README.md) · [Chapter 10 — Completion hooks and run metadata →](10-completion-hooks-and-metadata.md)
