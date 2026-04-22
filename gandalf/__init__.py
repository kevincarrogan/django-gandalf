from gandalf.storage import CookieStorage, SessionStorage, resolve_storage_class


class Wizard:
    def __init__(self, storage_class=None, **configuration):
        self.tree = []
        self.configuration = configuration
        self.storage_class = resolve_storage_class(storage_class)

    def step(self, form):
        self.tree.append(form)
        return self

    def branch(self, *forms, default=None):
        return self

    def get_storage(self, request, prefix="wizard"):
        return self.storage_class(request=request, prefix=prefix)


__all__ = [
    "CookieStorage",
    "SessionStorage",
    "Wizard",
]
