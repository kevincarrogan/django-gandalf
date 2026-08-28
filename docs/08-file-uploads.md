# Chapter 8 — File uploads

An organisation uploads its governing document. Uploaded bytes cannot live in
the session, so Gandalf persists them through a companion
`WizardFileStorage`; the session carries only a small ref (storage key plus
original name, content type and size).

```python
class GoverningDocumentForm(forms.Form):
    document = forms.FileField(label="Your governing document")


organisation_details = ch04.organisation_details.step(
    GoverningDocumentForm, name="governing_document", label="Governing document"
)


class DocumentedApplicationViewSet(WizardViewSet):
    url_name = "readme-upload"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def done(self, bound_wizard):
        document = bound_wizard.path.find_step(name="governing_document")
        if document is None:
            return HttpResponse("Application received (no document needed)")
        return HttpResponse(f"Received {document.files['document']['name']}")
```

The step template just needs the usual `enctype="multipart/form-data"`. Here
`done()` does guard its `find_step()`, because an individual never sees the
document step — it is on the organisation arm.

On replay, Gandalf reopens each stored file and re-injects it into
`request.FILES` before re-validating the step, so validators that inspect the
upload see the same value they saw originally. The bytes stay on the backend
until something asks for them: a plain `FileField` only reads the name and
the size, both of which the ref already carries, so a run's requests cost the
same whether its uploads are a kilobyte or a hundred megabytes. A validator
that does read the content — `ImageField`, a MIME sniff — still gets it,
fetched at the moment it asks. Editing respects keep-vs-replace per field.

The run's files are cleaned up automatically once `done()`'s response has
been rendered — so a `done()` that hands back a `TemplateResponse` can still
read the finished run back in the template, even though Django renders that
response after the view has returned.

The default storage writes under a `gandalf/<run_id>/` prefix of Django's
default storage; point it elsewhere (S3, a per-tenant location) by
subclassing `WizardFileStorage` and passing it to
`.configure(file_storage_class=...)`.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/upload/ &nbsp;·&nbsp; **Source:** [`ch08_uploads.py`](../tests/testapp/readme/ch08_uploads.py)

---

[← Chapter 7 — Step views and escapes](07-step-views-and-escapes.md) · [README](../README.md) · [Chapter 9 — Completion hooks and run metadata →](09-completion-hooks-and-metadata.md)
