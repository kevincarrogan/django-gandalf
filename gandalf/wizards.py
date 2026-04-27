from django.core.exceptions import ImproperlyConfigured

from gandalf.form_views import form_view_factory
from gandalf.runtime import BoundWizard
from gandalf.steps import Step
from gandalf.storage import SessionStorage


__all__ = [
    "BoundWizard",
    "ConfiguredWizard",
    "Step",
    "Wizard",
    "condition",
    "form_view_factory",
]


def condition(predicate, target):
    return predicate, target


class Wizard:
    def __init__(self, *, steps=None):
        if steps is None:
            steps = []

        self.steps = list(steps)

    def step(self, form_class_or_form_view_class, context=None):
        return self.__class__(
            steps=[
                *self.steps,
                Step(declaration=form_class_or_form_view_class),
            ],
        )

    def branch(self, *conditions, default=None):
        return self.__class__(steps=self.steps)

    def configure(self, **configuration):
        return ConfiguredWizard(
            steps=self.steps,
            configuration=configuration,
        )


class ConfiguredWizard:
    storage_class = SessionStorage

    def __init__(self, *, steps, configuration):
        self.configuration = configuration
        self.steps = self._configure_steps(steps)
        self.storage_class = configuration.get("storage_class", self.storage_class)

    def configure(self, **configuration):
        raise ImproperlyConfigured("ConfiguredWizard instances cannot be configured.")

    def _configure_steps(self, steps):
        template_name = self.configuration.get("template_name")

        configured_steps = []

        for step in steps:
            configured_steps.append(step.configure(template_name=template_name))

        return configured_steps

    def get_bound_wizard(self, request):
        return BoundWizard(self, request, self.storage_class(request))
