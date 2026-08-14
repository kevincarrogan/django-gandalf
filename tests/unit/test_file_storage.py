import tempfile

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile

from gandalf.file_storage import WizardFileStorage


@pytest.fixture
def file_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileSystemStorage(location=tmpdir)
        yield WizardFileStorage(backend=backend)


def test_wizard_file_storage_save_returns_ref_with_metadata(file_storage):
    uploaded = SimpleUploadedFile("ada.txt", b"hello", content_type="text/plain")

    ref = file_storage.save("run-1", uploaded)

    assert ref["name"] == "ada.txt"
    assert ref["content_type"] == "text/plain"
    assert ref["size"] == 5
    assert ref["charset"] is None


def test_wizard_file_storage_save_key_is_not_guessable_from_the_run_id(file_storage):
    """The run id travels in wizard URLs — history, referrers, access logs —
    so knowing it must not be enough to construct the storage path."""
    ref = file_storage.save("run-1", SimpleUploadedFile("ada.txt", b"hello"))

    assert ref["tmp_name"] != "gandalf/run-1/ada.txt"
    assert ref["tmp_name"].startswith("gandalf/run-1/")
    assert ref["tmp_name"].endswith("-ada.txt")


def test_wizard_file_storage_save_uses_a_fresh_key_per_upload(file_storage):
    first = file_storage.save("run-1", SimpleUploadedFile("dup.txt", b"first"))

    second = file_storage.save("run-1", SimpleUploadedFile("dup.txt", b"second"))

    assert first["tmp_name"] != second["tmp_name"]
    assert file_storage.open(first).read() == b"first"
    assert file_storage.open(second).read() == b"second"


def test_wizard_file_storage_keeps_a_runs_files_flat(file_storage):
    """`delete_run` sweeps with a non-recursive `listdir`, so the per-upload
    key may never introduce a subdirectory."""
    file_storage.save("run-1", SimpleUploadedFile("ada.txt", b"hello"))

    directories, files = file_storage.backend.listdir("gandalf/run-1")

    assert directories == []
    assert len(files) == 1


def test_wizard_file_storage_open_returns_uploaded_file_with_content(file_storage):
    uploaded = SimpleUploadedFile("ada.txt", b"hello", content_type="text/plain")
    ref = file_storage.save("run-1", uploaded)

    reopened = file_storage.open(ref)

    assert reopened.name == "ada.txt"
    assert reopened.content_type == "text/plain"
    assert reopened.size == 5
    assert reopened.read() == b"hello"


def test_wizard_file_storage_opens_a_ref_saved_under_an_older_key(file_storage):
    """Refs live verbatim in wizard state, so runs already in flight when the
    key scheme changes must keep resolving."""
    file_storage.backend.save("gandalf/run-1/legacy.txt", ContentFile(b"legacy"))
    ref = {
        "tmp_name": "gandalf/run-1/legacy.txt",
        "name": "legacy.txt",
        "content_type": "text/plain",
        "size": 6,
        "charset": None,
    }

    assert file_storage.open(ref).read() == b"legacy"


def test_wizard_file_storage_delete_removes_single_file(file_storage):
    ref = file_storage.save("run-1", SimpleUploadedFile("gone.txt", b"x"))

    file_storage.delete(ref)

    assert not file_storage.backend.exists(ref["tmp_name"])


def test_wizard_file_storage_delete_run_removes_all_files(file_storage):
    file_storage.save("run-1", SimpleUploadedFile("a.txt", b"a"))
    file_storage.save("run-1", SimpleUploadedFile("b.txt", b"b"))

    file_storage.delete_run("run-1")

    _, files = file_storage.backend.listdir("gandalf/run-1")
    assert files == []


def test_wizard_file_storage_delete_run_does_not_touch_other_runs(file_storage):
    other_ref = file_storage.save("run-2", SimpleUploadedFile("keep.txt", b"keep"))
    file_storage.save("run-1", SimpleUploadedFile("a.txt", b"a"))

    file_storage.delete_run("run-1")

    assert file_storage.open(other_ref).read() == b"keep"


def test_wizard_file_storage_delete_run_tolerates_missing_prefix(file_storage):
    file_storage.delete_run("never-existed")


def test_wizard_file_storage_defaults_to_django_default_storage():
    from django.core.files.storage import default_storage

    file_storage = WizardFileStorage()

    assert file_storage.backend is default_storage
