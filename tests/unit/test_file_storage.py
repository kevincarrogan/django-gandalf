import tempfile

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile

from gandalf.file_storage import WizardFileStorage


class _OverwritingStorage(FileSystemStorage):
    """As much of an overwriting backend as `WizardFileStorage` can tell.

    django-storages' `S3Boto3Storage` defaults to `file_overwrite=True`:
    it hands back the key it was given and the blob already there is gone.
    `FileSystemStorage` suffixes a colliding name instead, which hides a
    shared key rather than reporting it, so the suite needs a backend that
    behaves the way the deployed one does.
    """

    def get_available_name(self, name, max_length=None):
        return name

    def _save(self, name, content):
        if self.exists(name):
            self.delete(name)
        return super()._save(name, content)


@pytest.fixture
def file_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileSystemStorage(location=tmpdir)
        yield WizardFileStorage(backend=backend)


@pytest.fixture
def overwriting_file_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield WizardFileStorage(backend=_OverwritingStorage(location=tmpdir))


def test_wizard_file_storage_save_returns_ref_with_metadata(file_storage):
    uploaded = SimpleUploadedFile("ada.txt", b"hello", content_type="text/plain")

    ref = file_storage.save("run-1", uploaded)

    assert ref["tmp_name"].startswith("gandalf/run-1/")
    assert ref["tmp_name"].endswith("-ada.txt")
    assert ref["name"] == "ada.txt"
    assert ref["content_type"] == "text/plain"
    assert ref["size"] == 5
    assert ref["charset"] is None


def test_wizard_file_storage_open_returns_uploaded_file_with_content(file_storage):
    uploaded = SimpleUploadedFile("ada.txt", b"hello", content_type="text/plain")
    ref = file_storage.save("run-1", uploaded)

    reopened = file_storage.open(ref)

    assert reopened.name == "ada.txt"
    assert reopened.content_type == "text/plain"
    assert reopened.size == 5
    assert reopened.read() == b"hello"


def test_wizard_file_storage_keys_one_filename_twice_apart(file_storage):
    first_ref = file_storage.save("run-1", SimpleUploadedFile("dup.txt", b"first"))

    second_ref = file_storage.save("run-1", SimpleUploadedFile("dup.txt", b"second"))

    assert first_ref["tmp_name"] != second_ref["tmp_name"]
    assert file_storage.open(first_ref).read() == b"first"
    assert file_storage.open(second_ref).read() == b"second"


def test_wizard_file_storage_keeps_both_uploads_on_an_overwriting_backend(
    overwriting_file_storage,
):
    first_ref = overwriting_file_storage.save(
        "run-1", SimpleUploadedFile("cv.pdf", b"first")
    )

    overwriting_file_storage.save("run-1", SimpleUploadedFile("cv.pdf", b"second"))

    assert overwriting_file_storage.open(first_ref).read() == b"first"


def test_wizard_file_storage_delete_leaves_a_same_named_upload_alone(
    overwriting_file_storage,
):
    first_ref = overwriting_file_storage.save(
        "run-1", SimpleUploadedFile("cv.pdf", b"first")
    )
    second_ref = overwriting_file_storage.save(
        "run-1", SimpleUploadedFile("cv.pdf", b"second")
    )

    overwriting_file_storage.delete(second_ref)

    assert overwriting_file_storage.open(first_ref).read() == b"first"


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
