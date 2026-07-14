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
    "StepNameRouter",
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
    Pass the result to `Wizard().step(...)`. Equivalent to the `name=`
    keyword on `.step()`, which is the preferred spelling.
    """
    return form_class_or_form_view_class, {"step_name": name}


class StepNameRouter:
    """Routes an optional URL step segment to a step-context lookup and
    reverses a step declaration back into a segment. The default
    `step_router_class` on `ConfiguredWizard`.

    Routing is an add-on: it activates only when the URL pattern captures
    `url_kwarg` (e.g. `<slug:gandalf_step>`). Without that kwarg,
    `resolve()` always returns None and the wizard behaves exactly as if
    routing did not exist. Subclass to route on a different context key or
    a composite lookup — the returned dict is matched against step context
    the same way edit resolution is.
    """

    url_kwarg = "gandalf_step"
    context_key = "step_name"

    def resolve(self, url_kwargs):
        value = url_kwargs.get(self.url_kwarg)
        if not value:
            return None
        return {self.context_key: value}

    def reverse(self, step):
        """Return the URL segment for a step declaration, or None when the
        step carries no routable context (an unroutable step renders at the
        bare run URL instead)."""
        context = step.context or {}
        return context.get(self.context_key)

    def clean_url_kwargs(self, url_kwargs):
        return {
            key: value
            for key, value in url_kwargs.items()
            if key != self.url_kwarg
        }


def condition(predicate, target):
    return predicate, target


def step(form_class_or_form_view_class, context=None, name=None):
    """Module-level entry point: returns a Wizard starting with one step."""
    return Wizard().step(form_class_or_form_view_class, context=context, name=name)


def branch(*conditions, default=None):
    """Module-level entry point: returns a Wizard starting with one branch."""
    return Wizard().branch(*conditions, default=default)


class Wizard:
    def __init__(self, *, tree=None):
        self.tree = tree

    def step(self, form_class_or_form_view_class, context=None, name=None):
        if isinstance(form_class_or_form_view_class, tuple):
            form_class_or_form_view_class, base_context = form_class_or_form_view_class
            context = {**base_context, **(context or {})}
        if name is not None:
            context = {**(context or {}), "step_name": name}
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
    file_storage_class = WizardFileStorage
    runtime_tree_builder_class = RuntimeTreeBuilder
    cursor_walker_class = CursorWalker
    step_dispatcher_class = StepDispatcher
    state_serializer_class = StateSerializer
    form_view_factory = staticmethod(form_view_factory)
    step_router_class = StepNameRouter

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
        self.step_router_class = configuration.get(
            "step_router_class", self.step_router_class
        )

    def configure(self, **configuration):
        raise ImproperlyConfigured("ConfiguredWizard instances cannot be configured.")

    def _configure_tree(self, root):
        template_name = self.configuration.get("template_name")
        return tree.Configurer(
            template_name=template_name,
            form_view_factory=self.form_view_factory,
        ).transform(root)
