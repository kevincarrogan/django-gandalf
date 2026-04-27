from dataclasses import dataclass, replace

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.views.generic.edit import FormView

from gandalf.form_views import form_view_factory


@dataclass(frozen=True)
class Step:
    declaration: type
    form_view: type[FormView] | None = None

    def configure(self, *, template_name=None):
        if issubclass(self.declaration, forms.Form):
            if template_name is None:
                raise ImproperlyConfigured(
                    "Wizard.configure() must receive template_name when "
                    "generating FormView steps from Form classes."
                )

            return replace(
                self,
                form_view=form_view_factory(
                    self.declaration,
                    template_name=template_name,
                ),
            )

        return replace(self, form_view=self.declaration)
