# File uploads

`gandalf.file_storage` — where a step's uploads go, the ref state keeps in
their place, and what the walk does with them.

```python
from gandalf.file_storage import FileRef, StoredUpload, WizardFileStorage
```

---

## Reference

Uploaded bytes cannot live in the session. A step that receives files has
them saved through a `WizardFileStorage` before the walk, and state keeps
one small `FileRef` per field. On every later walk the refs are reopened as
`StoredUpload`s and put into `request.FILES`, so the step's form validates
the same shape of file it validated the first time.

### `WizardFileStorage(backend=None)`

Wraps a Django `Storage` and scopes every key under a per-run prefix. The
class is step-agnostic: the runtime embeds refs in the step's state entry,
so the step-to-file binding lives in state, not in the storage path.

**Parameters**

- `backend` — a `django.core.files.storage.Storage`. Default
  `default_storage`.

**Attributes**

- `prefix = "gandalf"` — the top of every key.
- `backend` — the wrapped storage.

**Methods**

| Method | Contract |
| --- | --- |
| `save(run_id, uploaded_file)` | Save one upload at `gandalf/<run_id>/<uuid4>-<original name>` and return its `FileRef`. The UUID segment is what keeps two uploads of `cv.pdf` apart on an overwriting backend (S3 with `file_overwrite=True`), where the filename alone would hand both the same key and deleting one ref would take the other's bytes |
| `open(ref)` | The upload as a `StoredUpload` — fetched from the backend only if something reads it |
| `delete(ref)` | Delete `ref["tmp_name"]` from the backend |
| `delete_run(run_id)` | Delete every file under `gandalf/<run_id>/`. A prefix that does not exist is not an error |

Configure a subclass on the viewset:

```python
class ApplicationViewSet(WizardViewSet):
    file_storage_class = TenantFileStorage
```

`WizardViewSet.file_storage_class` defaults to `WizardFileStorage`.
`Run.file_storage` instantiates it with no arguments, once per
run, so a subclass supplies its backend from `__init__`.

### `FileRef`

A `TypedDict` — the JSON-safe record of one stored upload, embedded in the
step's state entry under `"files"`, keyed by form field name.

| Key | Holds |
| --- | --- |
| `tmp_name` | the storage key `backend.save()` returned |
| `name` | the original filename, for display |
| `content_type` | as the browser sent it |
| `size` | in bytes |
| `charset` | usually `None` |

### `StoredUpload(backend, ref)`

A Django `UploadedFile` built from a ref, with the bytes left on the
backend. `name`, `size`, `content_type` and `charset` come from the ref, so
a plain `FileField` — which only reads name and size — validates without a
backend read. The first access to `.file` (through `read()`, `chunks()`,
`ImageField`, a MIME sniff, or `form_valid()` handing the file on) calls
`backend.open(tmp_name, "rb")`.

- `open()` rewinds a live handle, or forgets a closed one so the next read
  fetches again; it returns `self`. Rewinding a file nothing has read
  fetches nothing.
- `close()` closes the handle if one was opened, and costs nothing
  otherwise — Django closes every `request.FILES` entry at the end of a
  request.

**Attributes** — `backend`, `ref`.

### Replay

On every walk the runtime reopens each answered step's refs
(`file_storage.open(ref)` per field, in a `MultiValueDict`) and sets them
as the synthetic POST request's `FILES` before dispatching the step view.
Validators see the same `content_type` and `size` they saw on the first
POST; only one that reads content touches the backend. A run's requests
therefore cost the same whether its uploads are a kilobyte or a hundred
megabytes.

`RuntimeStep.form` does the same reopening, so a summary page or `done()`
reading `step.form.cleaned_data["document"]` gets a `StoredUpload` it can
read. `render_step()` (a GET of an answered step) passes the reopened
files as the form's `initial` instead.

### Keep or replace on edit

Browsers never re-send a file input, so a submission arrives with either a
new upload for a field or nothing. Per field:

| The edit sends | Stored ref |
| --- | --- |
| a new file | replaced; the old ref is deleted **after** the new state is persisted, so nothing deletes a live file |
| no file | kept |

`Run.store_uploads(request.FILES)` returns `None` rather than `{}`
for an empty upload, and the walk reads a missing `files` as "this
submission says nothing about files". A submission that fails validation
is still placed, upload included, so correcting a text field afterwards
keeps the file that came with the rejected attempt. An upload posted to a
step the run cannot reach is deleted immediately.

### Cleanup

The run's files are removed by `run.cleanup_files()` —
`file_storage.delete_run(run_id)` — from `WizardViewSet.finish()` after
`done()` returns, together with the run's [proofs](proofs.md), which are
claims on the same answers completion discards:

- when `done()` returns a `SimpleTemplateResponse`, as a post-render
  callback, so a completion template can still read an uploaded file back;
- for any other response, immediately.

Before either, `finish()` calls `keep_readable()`, which pins the run's
tree so the completion template can walk it after the state is
tombstoned. A programmatic caller that drops an unrendered
`TemplateResponse` from `finish()` leaves the run's uploads behind.

### `RuntimeStep.files`

`FileRefs | None` — the refs stored for this step, keyed by field name, or
`None` for a step without uploads. `done()` and summary rows read it
directly; `step.files["document"]["name"]` is the original filename.

### Escapes

| | Files |
| --- | --- |
| `Park` | the escaping submission's uploads are deleted; stored refs are untouched |
| `Advance` | the submission is persisted, uploads included, exactly as a normal answer |
| `Obliterate` | `cleanup_files()` then `delete_run()` — every file under the run's prefix goes |

### The driver

`RunDriver.open_file(ref)` opens a ref from `placements()` as a
`StoredUpload`, for a caller that has to look at what was uploaded rather
than only the fact that something was. `ref["size"]` is there before the
bytes are. See [Driver](driver.md).

---

## Usage

### A step with an upload

```python
from django import forms
from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class GoverningDocumentForm(forms.Form):
    document = forms.FileField(label="Your governing document")


class OrganisationViewSet(WizardViewSet):
    url_name = "organisation"
    template_name = "grants/step.html"
    wizard = (
        Wizard()
        .step(OrganisationForm, name="organisation")
        .step(GoverningDocumentForm, name="governing-document")
    )

    def done(self, run):
        document = run.path.find_step(name="governing-document")
        return HttpResponse(f"Received {document.files['document']['name']}")
```

The step template needs `enctype="multipart/form-data"` on its form.

### Keeping the file after the run

```python
from django.shortcuts import redirect


class OrganisationViewSet(WizardViewSet):
    ...

    def done(self, run):
        step = run.path.find_step(name="governing-document")
        organisation = Organisation.objects.get(pk=run.metadata["organisation_id"])
        organisation.governing_document.save(
            step.files["document"]["name"],
            step.form.cleaned_data["document"],
        )
        return redirect("organisation-detail", pk=organisation.pk)
```

`cleaned_data["document"]` is a `StoredUpload`; `FieldFile.save()` reads
it in chunks. The run's own copy is deleted once the response is done.

### Storing uploads per tenant on S3

```python
from storages.backends.s3 import S3Storage

from gandalf.file_storage import WizardFileStorage


class TenantFileStorage(WizardFileStorage):
    prefix = "grant-applications"

    def __init__(self):
        super().__init__(backend=S3Storage(bucket_name="applications-in-progress"))


class DocumentsViewSet(WizardViewSet):
    url_name = "documents"
    template_name = "grants/upload_step.html"
    file_storage_class = TenantFileStorage
    wizard = Wizard().step(GoverningDocumentForm, name="governing-document")
```

Keys land at `grant-applications/<run_id>/<uuid>-<name>`. The UUID
segment makes an overwriting backend safe.

### Showing the filename on a summary row

```django
{% for step in wizard.path %}
  {% if step.files %}
    <dd>{{ step.files.document.name }} ({{ step.files.document.size }} bytes)</dd>
  {% endif %}
{% endfor %}
```

---

## Troubleshooting

### The completion page raised `FileNotFoundError` reading an upload

`done()` returned a plain `HttpResponse` or a pre-rendered response, so
the files were deleted before whatever read them ran. Read the file inside
`done()`, or return an unrendered `TemplateResponse` and read it in the
template.

### Every request reads my uploads off S3

Something in the step's validation reaches for the bytes — `ImageField`,
a MIME sniff, a `clean_<field>()` that calls `read()`. That is by design:
the ref answers name, size and content type for free, and only content
costs a backend read. Move the byte-reading check to `form_valid()` if it
only needs to run once, or accept the cost.

### Editing a step lost the file I had uploaded

A GET of an answered step renders the stored file as `initial`, but a
browser cannot pre-fill a file input; submitting without choosing a file
*keeps* the stored ref. If it was lost, the submission carried a new file
for that field — check the field name — or the step was escaped with
`Park`, which discards the escaping submission's uploads.

### Two uploads with the same name overwrote each other

Only possible on a subclass that changed the key in `save()`. Keep the
`uuid4()` segment; `FileSystemStorage` suffixes collisions away, but an
overwriting backend hands back the same key for both.

### Files are left behind under `gandalf/<run_id>/`

Either a run was never finished — the session expired with it — or a
programmatic caller dropped an unrendered `TemplateResponse` from
`finish()`. Nothing sweeps abandoned runs; a lifecycle rule on the bucket,
or a periodic `delete_run()` for runs the storage no longer holds, is the
project's to add.

---

**Learn:** [Chapter 9 — File uploads](../learn/09-file-uploads.md) · **Related:** [`Run`](run.md), [Configuration](configuration.md), [Escapes](escapes.md), [Stashing](stashing.md), [Driver](driver.md), [Walk costs](walk-costs.md)
