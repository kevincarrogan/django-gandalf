class Wizard:
    def __init__(self, **configuration):
        pass

    def step(self, form):
        return self

    def branch(self, *forms, default=None):
        return self


class WizardViewSet:
    # This handles the outside world of the request/response and then splits
    # this out to route to the correct step (which should just be a FormView).
    #
    # This will handle routing to the right view, handle the urls.
    #
    # This is ideally how we would handle the ManagementForm.
    #
    # __Although how do we inject the ManagentForm in whilst making the child
    # FormViews not care that they're part of this - maybe the view needs to
    # know more context__.
    #
    wizard = None

    def get_wizard(self):
        """
        Return the wizard used for this request.

        Subclasses can override this to build the flow dynamically from the
        current request (for example user role, feature flags, or tenant).
        """
        return self.wizard


class NamedURLRouter:
    def __init__(self, *args, **kwargs):
        pass

    @property
    def urls(self):
        return []


def is_this(request):
    pass


def is_that(request):
    pass


def condition(cond, flow):
    pass
