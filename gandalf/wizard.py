from django.core.exceptions import ImproperlyConfigured

from gandalf import tree
from gandalf.file_storage import WizardFileStorage
from gandalf.form_views import form_view_factory
from gandalf.runtime import (
    BoundWizard,
    CursorWalker,
    MergeCleanedData,
    RuntimeTreeBuilder,
    StateSerializer,
    StepDispatcher,
)
from gandalf.storage import SessionStorage


__all__ = [
    "BoundWizard",
    "ConfiguredWizard",
    "MergeCleanedData",
    "StepNameEditResolver",
    "Wizard",
    "WizardFileStorage",
    "branch",
    "condition",
    "form_view_factory",
    "named",
    "step",
]


def named(name, form_class_or_form_view_class):
    """Shorthand for declaring a step with `context={"step_name": name}`.
    Pass the result to `Wizard().step(...)`.
    """
    return form_class_or_form_view_class, {"step_name": name}


class StepNameEditResolver:
    """Resolves an edit cycle from a single `gandalf_edit_step` field whose
    value is looked up against the wizard's runtime tree via `step_name=`
    context matching. The default `edit_resolver_class` on `ConfiguredWizard`.
    """

    field_name = "gandalf_edit_step"
    context_key = "step_name"

    def resolve(self, request):
        value = request.GET.get(self.field_name) or request.POST.get(self.field_name)
        if not value:
            return None
        return {self.context_key: value}

    def clean_submission(self, submission):
        submission.pop(self.field_name, None)
        return submission


def condition(predicate, target):
    return predicate, target


def step(form_class_or_form_view_class, context=None):
    """Module-level entry point: returns a Wizard starting with one step."""
    return Wizard().step(form_class_or_form_view_class, context=context)


def branch(*conditions, default=None):
    """Module-level entry point: returns a Wizard starting with one branch."""
    return Wizard().branch(*conditions, default=default)


class Wizard:
    def __init__(self, *, tree=None):
        self.tree = tree

    def step(self, form_class_or_form_view_class, context=None):
        if isinstance(form_class_or_form_view_class, tuple):
            form_class_or_form_view_class, base_context = form_class_or_form_view_class
            context = {**base_context, **(context or {})}
        declarations = list(self.tree) if self.tree is not None else []
        declarations.append(
            tree.Step(
                declaration=form_class_or_form_view_class,
                context=context,
            )
        )
        return self.__class__(tree=tree.build(declarations))

    def branch(self, *conditions, default=None):
        declarations = list(self.tree) if self.tree is not None else []
        arms = tuple(
            (predicate, sub_wizard.tree) for predicate, sub_wizard in conditions
        )
        default_tree = default.tree if default is not None else None
        declarations.append(tree.Branch(arms=arms, default=default_tree))
        return self.__class__(tree=tree.build(declarations))

    def configure(self, **configuration):
        return ConfiguredWizard(
            tree=self.tree,
            configuration=configuration,
        )

    def mermaid(self):
        """Render the declared flow as a Mermaid ``flowchart TD`` source string."""
        return tree.mermaid(self.tree)


class ConfiguredWizard:
    storage_class = SessionStorage
    file_storage_class = WizardFileStorage
    runtime_tree_builder_class = RuntimeTreeBuilder
    cursor_walker_class = CursorWalker
    step_dispatcher_class = StepDispatcher
    state_serializer_class = StateSerializer
    form_view_factory = staticmethod(form_view_factory)
    edit_resolver_class = StepNameEditResolver

    def __init__(self, *, tree, configuration):
        self.configuration = configuration
        self.form_view_factory = configuration.get(
            "form_view_factory", self.form_view_factory
        )
        self.tree = self._configure_tree(tree)
        self.storage_class = configuration.get("storage_class", self.storage_class)
        self.file_storage_class = configuration.get(
            "file_storage_class", self.file_storage_class
        )
        self.runtime_tree_builder_class = configuration.get(
            "runtime_tree_builder_class", self.runtime_tree_builder_class
        )
        self.cursor_walker_class = configuration.get(
            "cursor_walker_class", self.cursor_walker_class
        )
        self.step_dispatcher_class = configuration.get(
            "step_dispatcher_class", self.step_dispatcher_class
        )
        self.state_serializer_class = configuration.get(
            "state_serializer_class", self.state_serializer_class
        )
        self.edit_resolver_class = configuration.get(
            "edit_resolver_class", self.edit_resolver_class
        )

    def configure(self, **configuration):
        raise ImproperlyConfigured("ConfiguredWizard instances cannot be configured.")

    def mermaid(self):
        """Render the configured flow as a Mermaid ``flowchart TD`` source string."""
        return tree.mermaid(self.tree)

    def _configure_tree(self, root):
        template_name = self.configuration.get("template_name")
        return tree.Configurer(
            template_name=template_name,
            form_view_factory=self.form_view_factory,
        ).transform(root)
