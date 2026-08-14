from __future__ import annotations

import secrets
from io import BytesIO
from typing import TypedDict

from django.core.files.storage import Storage, default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile, UploadedFile


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


class WizardFileStorage:
    """File-backed sibling of `SessionStorage` for wizard uploads.

    Wraps a Django `Storage` (defaulting to `default_storage`) and scopes
    all keys under a per-run prefix. The class is step-agnostic: callers
    (the runtime) embed file refs in the cursor's state entry, so the
    step↔file binding lives in state structure, not in the storage path.

    A "ref" is a dict of `{tmp_name, name, content_type, size, charset}`
    capturing both the storage key and enough metadata to reconstitute an
    `InMemoryUploadedFile` with the same shape as the original upload — so
    form validators that inspect `content_type` (image checks, MIME
    sniffing) see the same value on replay as on first POST.
    """

    prefix = "gandalf"

    def __init__(self, backend: Storage | None = None) -> None:
        self.backend = backend or default_storage

    def token(self) -> str:
        """The unguessable part of an upload's storage key.

        A run id is a *routing* identifier — it sits in every wizard URL, so
        it reaches browser history, referrer headers and access logs. Keying
        uploads on it alone would make a leaked run URL enough to fetch the
        bytes straight from a public media domain, with no session at all.
        The token breaks that chain: the path cannot be derived from anything
        the user's browser hands out.

        It prefixes the filename rather than nesting a directory, because
        `delete_run` sweeps a run with a non-recursive `listdir`. Hex keeps
        the `-` separator unambiguous: a urlsafe token may contain one
        itself, which would leave the original filename unrecoverable.
        """
        return secrets.token_hex(16)

    def save(self, run_id: str, uploaded_file: UploadedFile) -> FileRef:
        target = f"{self.prefix}/{run_id}/{self.token()}-{uploaded_file.name}"
        tmp_name = self.backend.save(target, uploaded_file)
        return {
            "tmp_name": tmp_name,
            "name": uploaded_file.name,
            "content_type": uploaded_file.content_type,
            "size": uploaded_file.size,
            "charset": uploaded_file.charset,
        }

    def open(self, ref: FileRef) -> InMemoryUploadedFile:
        with self.backend.open(ref["tmp_name"], "rb") as stored:
            content = stored.read()
        buffer = BytesIO(content)
        return InMemoryUploadedFile(
            file=buffer,
            field_name=None,
            name=ref["name"],
            content_type=ref["content_type"],
            size=ref["size"],
            charset=ref["charset"],
        )

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
