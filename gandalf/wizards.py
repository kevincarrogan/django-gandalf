from django import forms
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
    tree = None

    def __init__(self, **configuration):
        self.configuration = configuration
        self.steps = []
        self.start = None

    def get_current_form_view(self):
        return self.steps[0]

    def step(self, form_class_or_form_view_class, context=None):
        if issubclass(form_class_or_form_view_class, forms.Form):
            form_class = form_class_or_form_view_class
            form_view = form_view_factory(form_class)
            self.steps.append(form_view)
            self.start = self.steps[0]

        return self
