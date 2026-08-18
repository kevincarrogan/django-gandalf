from __future__ import annotations

import uuid
from typing import IO, Any, TypedDict, cast

from django.core.files.storage import Storage, default_storage
from django.core.files.uploadedfile import UploadedFile


class FileRef(TypedDict):
    """The JSON-safe record of one stored upload, embedded in wizard state.

    `tmp_name` is the storage key; the rest is the metadata needed to hand
    a replayed form the same shape of file it validated the first time.
    """

    tmp_name: str
    name: str | None
    content_type: str | None
    size: int | None
    charset: str | None


class StoredUpload(UploadedFile):
    """A stored upload handed back as a file, without the bytes attached.

    Everything a replayed form usually asks of an upload — `name`, `size`,
    `content_type`, `charset` — the ref already knows, so this answers
    those from the ref and goes to the backend only when something reaches
    for the content. That matters because the walk re-proves every
    answered step on every request: a run with three uploads would
    otherwise read all three off the backend to re-derive facts it had
    written down, and the cost of a request would scale with the size of
    the files rather than with the length of the run.

    A validator that does read the bytes (`ImageField`, a MIME sniff) or a
    `form_valid()` that hands the file on to storage still gets them, at
    the moment it asks. So does anything reading it a second time: `open()`
    rewinds a live handle and drops a closed one, so the next read fetches
    it again rather than raising at a spent file.
    """

    def __init__(self, backend: Storage, ref: FileRef) -> None:
        self.backend = backend
        self.ref = ref
        self._file: IO[Any] | None = None
        super().__init__(
            file=None,
            name=ref["name"],
            content_type=ref["content_type"],
            size=ref["size"],
            charset=ref["charset"],
        )

    @property
    def file(self) -> IO[Any]:
        if self._file is None:
            # A Django `File` is the byte-reading protocol this attribute
            # is for; it is `IO`-shaped without being an `IO` by name.
            opened = self.backend.open(self.ref["tmp_name"], "rb")
            self._file = cast("IO[Any]", opened)
        return self._file

    @file.setter
    def file(self, value: IO[Any] | None) -> None:
        # `File.__init__` assigns through here with the `None` passed
        # above; the setter is what stops that assignment shadowing the
        # property and taking the laziness with it.
        self._file = value

    def open(self, mode: str | None = None, *args: Any, **kwargs: Any) -> StoredUpload:
        if self._file is not None:
            if self._file.closed:
                self._file = None
            else:
                self._file.seek(0)
        return self

    def close(self) -> None:
        if self._file is not None:
            self._file.close()


class WizardFileStorage:
    """File-backed sibling of `SessionStorage` for wizard uploads.

    Wraps a Django `Storage` (defaulting to `default_storage`) and scopes
    all keys under a per-run prefix, one unique key per stored upload. The
    class is step-agnostic: callers (the runtime) embed file refs in the
    cursor's state entry, so the step↔file binding lives in state
    structure, not in the storage path.

    A "ref" is a dict of `{tmp_name, name, content_type, size, charset}`
    capturing both the storage key and enough metadata to reconstitute a
    file of the same shape as the original upload — so form validators
    that inspect `content_type` (image checks, MIME sniffing) see the same
    value on replay as on first POST, without the bytes being read to tell
    them.
    """

    prefix = "gandalf"

    def __init__(self, backend: Storage | None = None) -> None:
        self.backend = backend or default_storage

    def save(self, run_id: str, uploaded_file: UploadedFile) -> FileRef:
        """Store one upload under this run, on a key nothing else can hold.

        The key carries a uuid segment because the filename cannot be
        trusted to separate two uploads: a user who re-uploads `cv.pdf`
        when editing a step would otherwise be handed the key the first
        `cv.pdf` already has. `FileSystemStorage` suffixes a collision
        away, but an overwriting backend (django-storages' `S3Boto3Storage`
        defaults to `file_overwrite=True`) hands back the same key for
        both, and deleting either ref then takes the other's blob with it.
        The original filename stays in the ref's `name` for display.
        """
        target = f"{self.prefix}/{run_id}/{uuid.uuid4()}-{uploaded_file.name}"
        tmp_name = self.backend.save(target, uploaded_file)
        return {
            "tmp_name": tmp_name,
            "name": uploaded_file.name,
            "content_type": uploaded_file.content_type,
            "size": uploaded_file.size,
            "charset": uploaded_file.charset,
        }

    def open(self, ref: FileRef) -> StoredUpload:
        """The stored upload as a file, fetched only if it is read.

        See `StoredUpload`: the ref carries the metadata, so replaying an
        answered step costs nothing on the backend unless the form's own
        validation reaches for the content.
        """
        return StoredUpload(self.backend, ref)

    def delete(self, ref: FileRef) -> None:
        self.backend.delete(ref["tmp_name"])

    def delete_run(self, run_id: str) -> None:
        run_prefix = f"{self.prefix}/{run_id}"
        try:
            _, files = self.backend.listdir(run_prefix)
        except FileNotFoundError:
            return
        for name in files:
            self.backend.delete(f"{run_prefix}/{name}")
