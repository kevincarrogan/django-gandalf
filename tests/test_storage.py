import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

from gandalf import CookieStorage, SessionStorage, Wizard


def test_default_storage_is_session_storage():
    wizard = Wizard()

    assert wizard.storage_class is SessionStorage


def test_wizard_uses_session_storage_instance():
    wizard = Wizard()
    request = RequestFactory().get("/wizard/")
    storage = wizard.get_storage(request, prefix="test-wizard")

    assert isinstance(storage, SessionStorage)
    assert storage.request is request
    assert storage.prefix == "test-wizard"


def test_cookie_storage_can_be_passed_to_wizard():
    wizard = Wizard(storage_class=CookieStorage)
    request = RequestFactory().get("/wizard/")
    storage = wizard.get_storage(request, prefix="cookie-wizard")

    assert isinstance(storage, CookieStorage)
    assert storage.request is request
    assert storage.prefix == "cookie-wizard"


@override_settings(GANDALF_WIZARD_STORAGE_CLASS=CookieStorage)
def test_global_storage_setting_can_override_default():
    wizard = Wizard()
    request = RequestFactory().get("/wizard/")
    storage = wizard.get_storage(request)

    assert isinstance(storage, CookieStorage)


@override_settings(GANDALF_WIZARD_STORAGE_CLASS="gandalf.storage.CookieStorage")
def test_global_storage_setting_accepts_dotted_path():
    wizard = Wizard()

    assert wizard.storage_class is CookieStorage


@override_settings(GANDALF_WIZARD_STORAGE_CLASS=object())
def test_invalid_storage_class_raises():
    with pytest.raises(ImproperlyConfigured):
        Wizard()


class InMemoryStorage:
    def __init__(self, request, prefix):
        self.request = request
        self.prefix = prefix


@override_settings(GANDALF_WIZARD_STORAGE_CLASS=CookieStorage)
def test_wizard_parameter_takes_precedence_over_global_setting():
    wizard = Wizard(storage_class=InMemoryStorage)

    assert wizard.storage_class is InMemoryStorage
