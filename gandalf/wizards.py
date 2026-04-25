from django.views.generic.edit import FormView


def form_view_factory(form_class):
    form_name = form_class.__name__

    class GeneratedFormView(FormView):
        pass

    GeneratedFormView.form_class = form_class
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView


class Wizard:
    def __init__(self, **configuration):
        self.configuration = configuration
        self.tree = []

    def step(self, form_class_or_form_view_class, context=None):
        return self
