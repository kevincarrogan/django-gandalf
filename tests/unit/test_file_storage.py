import tempfile

import pytest
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

    assert ref == {
        "tmp_name": "gandalf/run-1/ada.txt",
        "name": "ada.txt",
        "content_type": "text/plain",
        "size": 5,
        "charset": None,
    }


def test_wizard_file_storage_open_returns_uploaded_file_with_content(file_storage):
    uploaded = SimpleUploadedFile("ada.txt", b"hello", content_type="text/plain")
    ref = file_storage.save("run-1", uploaded)

    reopened = file_storage.open(ref)

    assert reopened.name == "ada.txt"
    assert reopened.content_type == "text/plain"
    assert reopened.size == 5
    assert reopened.read() == b"hello"


def test_wizard_file_storage_save_renames_on_collision(file_storage):
    file_storage.save("run-1", SimpleUploadedFile("dup.txt", b"first"))

    second_ref = file_storage.save("run-1", SimpleUploadedFile("dup.txt", b"second"))

    assert second_ref["tmp_name"] != "gandalf/run-1/dup.txt"
    assert file_storage.open(second_ref).read() == b"second"


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
