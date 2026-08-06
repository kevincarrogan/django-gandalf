from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias

from django import forms
from django.views.generic.edit import FormView

from gandalf.types import WizardRequest


if TYPE_CHECKING:
    # `FormView` is generic to type checkers but not at runtime — it carries
    # no `__class_getitem__` in any supported Django — so the parameter is
    # supplied only where it is read. `BaseForm` rather than `Form` so that
    # `ModelForm` steps type-check too.
    _StepFormViewBase = FormView[forms.BaseForm]

    #: The view class behind a step: `StepFormView`, a plain Django
    #: `FormView` subclass a step declared for itself, or one this module
    #: generated for a bare `Form`.
    StepViewClass: TypeAlias = type[FormView[Any]]

    #: What `.step()` accepts: a form to generate a view for, or a view
    #: that brings its own.
    StepDeclaration: TypeAlias = "type[forms.Form] | StepViewClass"
else:
    _StepFormViewBase = FormView


class StepFormView(_StepFormViewBase):
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

    #: Narrowed from `View.request`: a step view is dispatched inside a
    #: wizard, which is what puts `request.wizard` there. A `StepFormView`
    #: mounted standalone (see below) is handed a plain request and simply
    #: has no run to read.
    request: WizardRequest

    # Restated from `FormMixin` so the class is concrete about what a step's
    # form may be. Inherited, it is a variable of the generic parameter, and
    # assigning it through the class — as `form_view_factory` does — is
    # ambiguous to a type checker.
    form_class: type[forms.BaseForm] | None = None

    def get_success_url(self) -> str:
        return self.request.path


def form_view_factory(
    form_class: type[forms.Form], *, template_name: str
) -> type[StepFormView]:
    form_name = form_class.__name__

    class GeneratedFormView(StepFormView):
        pass

    GeneratedFormView.form_class = form_class
    GeneratedFormView.template_name = template_name
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView
