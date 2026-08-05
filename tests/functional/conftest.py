import tempfile

from django.test import override_settings
import pytest


@pytest.fixture
def isolated_media_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            yield tmpdir
