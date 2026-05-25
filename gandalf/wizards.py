from django.core.exceptions import ImproperlyConfigured

from gandalf import tree
from gandalf.form_views import form_view_factory
from gandalf.runtime import (
    BoundWizard,
    CursorWalker,
    RuntimeTreeBuilder,
    StateSerializer,
)
from gandalf.storage import SessionStorage


__all__ = [
    "BoundWizard",
    "ConfiguredWizard",
    "Wizard",
    "condition",
    "form_view_factory",
]


def condition(predicate, target):
    return predicate, target


class Wizard:
    def __init__(self, *, tree=None):
        self.tree = tree

    def step(self, form_class_or_form_view_class, context=None):
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


class ConfiguredWizard:
    storage_class = SessionStorage
    runtime_tree_builder_class = RuntimeTreeBuilder
    cursor_walker_class = CursorWalker
    state_serializer_class = StateSerializer

    def __init__(self, *, tree, configuration):
        self.configuration = configuration
        self.tree = self._configure_tree(tree)
        self.storage_class = configuration.get(
            "storage_class", self.storage_class
        )
        self.runtime_tree_builder_class = configuration.get(
            "runtime_tree_builder_class", self.runtime_tree_builder_class
        )
        self.cursor_walker_class = configuration.get(
            "cursor_walker_class", self.cursor_walker_class
        )
        self.state_serializer_class = configuration.get(
            "state_serializer_class", self.state_serializer_class
        )

    def configure(self, **configuration):
        raise ImproperlyConfigured("ConfiguredWizard instances cannot be configured.")

    def _configure_tree(self, root):
        template_name = self.configuration.get("template_name")
        return tree.Configurer(template_name=template_name).transform(root)

    def get_bound_wizard(self, request):
        return BoundWizard(self, request, self.storage_class(request))
