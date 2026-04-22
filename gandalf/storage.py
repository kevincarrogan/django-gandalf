from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


class SessionStorage:
    def __init__(self, request, prefix):
        self.request = request
        self.prefix = prefix

class CookieStorage:
    def __init__(self, request, prefix):
        self.request = request
        self.prefix = prefix


def resolve_storage_class(storage_class=None):
    from django.conf import settings

    configured_storage = storage_class or getattr(
        settings,
        "GANDALF_WIZARD_STORAGE_CLASS",
        SessionStorage,
    )

    if isinstance(configured_storage, str):
        configured_storage = import_string(configured_storage)

    if not isinstance(configured_storage, type):
        raise ImproperlyConfigured(
            "Wizard storage must be a class or dotted path to one."
        )

    return configured_storage
