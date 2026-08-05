from django.views.generic.edit import FormView


class StepFormView(FormView):
    """Base class for a step that brings its own view.

    A step view is dispatched as an ordinary Django view, but the wizard
    reads only the *status code* of its response — a 3xx means "this answer
    stands, carry on" — and then discards the response. The success URL is
    therefore never followed, and every step view ends up writing the same
    no-op redirect back onto itself. This class writes it once.

    Subclass it in place of Django's `FormView` when a step needs view-level
    behaviour, and give it a `template_name` (the viewset's default only
    reaches the views Gandalf generates):

        from gandalf.form_views import StepFormView


        class BillingStepView(StepFormView):
            form_class = BillingForm
            template_name = "billing/step.html"

            def get_initial(self):
                ...

    Nothing else changes: it is a plain `FormView`, so it keeps its own
    configuration and can be mounted as a standalone view outside the
    wizard — override `get_success_url()` there to go somewhere real.
    """

    def get_success_url(self):
        return self.request.path


def form_view_factory(form_class, *, template_name):
    form_name = form_class.__name__

    class GeneratedFormView(StepFormView):
        pass

    GeneratedFormView.form_class = form_class
    GeneratedFormView.template_name = template_name
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView
