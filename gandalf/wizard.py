from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import Storage

from gandalf import tree
from gandalf.file_storage import WizardFileStorage
from gandalf.form_views import StepFormView, form_view_factory
from gandalf.runtime import (
    BoundWizard,
    CursorWalker,
    InvalidStash,
    MergeCleanedData,
    StateSerializer,
    StepDispatcher,
)
from gandalf.types import Context


if TYPE_CHECKING:
    from gandalf.form_views import StepDeclaration


__all__ = [
    "BoundWizard",
    "ConfiguredWizard",
    "InvalidStash",
    "MergeCleanedData",
    "StepFormView",
    "StepNameRouter",
    "Wizard",
    "WizardFileStorage",
    "branch",
    "condition",
    "form_view_factory",
    "named",
    "step",
]


def named(
    name: str, form_class_or_form_view_class: StepDeclaration
) -> tuple[StepDeclaration, Context]:
    """Shorthand for declaring a step with `context={"name": name}`.
    Pass the result to `Wizard().step(...)`. Equivalent to the `name=`
    keyword on `.step()`, which is the preferred spelling.
    """
    return form_class_or_form_view_class, {"name": name}


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
    context_key = "name"

    def resolve(self, url_kwargs: dict[str, Any]) -> Context | None:
        value = url_kwargs.get(self.url_kwarg)
        if not value:
            return None
        return {self.context_key: value}

    def reverse(self, step: tree.Step) -> str | None:
        """Return the URL segment for a step declaration, or None when the
        step carries no routable context (an unroutable step renders at the
        bare run URL instead)."""
        context = step.context or {}
        segment: str | None = context.get(self.context_key)
        return segment

    def clean_url_kwargs(self, url_kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in url_kwargs.items() if key != self.url_kwarg
        }


def condition(
    predicate: tree.Predicate, target: Wizard
) -> tuple[tree.Predicate, Wizard]:
    return predicate, target


def step(
    form_class_or_form_view_class: StepDeclaration | tuple[StepDeclaration, Context],
    context: Context | None = None,
    name: str | None = None,
) -> Wizard:
    """Module-level entry point: returns a Wizard starting with one step."""
    return Wizard().step(form_class_or_form_view_class, context=context, name=name)


def branch(
    *conditions: tuple[tree.Predicate, Wizard], default: Wizard | None = None
) -> Wizard:
    """Module-level entry point: returns a Wizard starting with one branch."""
    return Wizard().branch(*conditions, default=default)


class Wizard:
    def __init__(self, *, tree: tree.Node | None = None) -> None:
        self.tree = tree

    def step(
        self,
        form_class_or_form_view_class: StepDeclaration
        | tuple[StepDeclaration, Context],
        context: Context | None = None,
        name: str | None = None,
    ) -> Wizard:
        if isinstance(form_class_or_form_view_class, tuple):
            form_class_or_form_view_class, base_context = form_class_or_form_view_class
            context = {**base_context, **(context or {})}
        if name is not None:
            context = {**(context or {}), "name": name}
        declarations = list(self.tree) if self.tree is not None else []
        declarations.append(
            tree.Step(
                declaration=form_class_or_form_view_class,
                context=context,
            )
        )
        return self.__class__(tree=tree.build(declarations))

    def branch(
        self, *conditions: tuple[tree.Predicate, Wizard], default: Wizard | None = None
    ) -> Wizard:
        declarations = list(self.tree) if self.tree is not None else []
        arms = tuple(
            (predicate, sub_wizard.tree) for predicate, sub_wizard in conditions
        )
        default_tree = default.tree if default is not None else None
        declarations.append(tree.Branch(arms=arms, default=default_tree))
        return self.__class__(tree=tree.build(declarations))

    def expand(self, builder: tree.Builder) -> Wizard:
        """Grow the tree here from `builder(request)`, called mid-walk.

        `builder` returns a `Wizard` whose steps are spliced in at this point.
        It runs behind a fully-validated prefix, so it can read prior answers
        to decide how many steps to produce. See `tree.Expand`.
        """
        declarations = list(self.tree) if self.tree is not None else []
        declarations.append(tree.Expand(builder=builder))
        return self.__class__(tree=tree.build(declarations))

    def configure(self, **configuration: Any) -> ConfiguredWizard:
        return ConfiguredWizard(
            tree=self.tree,
            configuration=configuration,
        )


class ConfiguredWizard:
    file_storage_class = WizardFileStorage
    # None means "let `file_storage_class` pick its own backend", which is
    # what keeps a zero-argument custom storage class working. Configuring
    # one opts into passing it as `backend=`.
    file_storage_backend: Storage | None = None
    cursor_walker_class = CursorWalker
    step_dispatcher_class = StepDispatcher
    state_serializer_class = StateSerializer
    form_view_factory = staticmethod(form_view_factory)
    step_router_class = StepNameRouter

    def __init__(self, *, tree: Any, configuration: dict[str, Any]) -> None:
        if "storage_class" in configuration:
            raise ImproperlyConfigured(
                "storage_class belongs on the WizardViewSet, not the wizard. "
                "Storage has to exist before the wizard does — get_wizard() "
                "is handed a BoundWizard that can already read stored state — "
                "so the wizard cannot supply it. Set "
                "WizardViewSet.storage_class instead."
            )
        self.configuration = configuration
        self.form_view_factory = configuration.get(
            "form_view_factory", self.form_view_factory
        )
        self.tree = self._configure_tree(tree)
        self.file_storage_class = configuration.get(
            "file_storage_class", self.file_storage_class
        )
        self.file_storage_backend = configuration.get(
            "file_storage_backend", self.file_storage_backend
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

    def configure(self, **configuration: Any) -> ConfiguredWizard:
        raise ImproperlyConfigured("ConfiguredWizard instances cannot be configured.")

    def _configure_tree(self, root: tree.Node | None) -> tree.Node | None:
        template_name = self.configuration.get("template_name")
        # `Transformer.transform` is deliberately open about what it returns;
        # a `Configurer` returns a tree of the same shape it was given.
        return cast(
            "tree.Node | None",
            tree.Configurer(
                template_name=template_name,
                form_view_factory=self.form_view_factory,
            ).transform(root),
        )

    def configure_expansion(self, built: Wizard) -> tree.Node | None:
        """Configure and vet a subtree an `Expand` builder returned.

        The builder hands back a bare `Wizard`; it gets the same `Configurer`
        pass a declared tree does, then two checks the declared tree already
        has run for it but this subtree has not: every step must be routable,
        and an expansion may not itself contain an expansion. Both are raised
        here — at the moment of building — because the subtree does not exist
        until then.
        """
        subtree = self._configure_tree(built.tree)
        router = self.step_router_class()
        finder = tree.ContextFinder({})
        finder.visit(subtree)
        steps = finder.all()
        unroutable = [step for step in steps if router.reverse(step) is None]
        if unroutable:
            names = ", ".join(step.declaration.__name__ for step in unroutable)
            raise ImproperlyConfigured(
                "Every expanded step needs a routable name; build steps with "
                f".step(..., name=...). Unroutable steps: {names}."
            )
        if any(isinstance(node, tree.Expand) for node in tree.iter_nodes(subtree)):
            raise ImproperlyConfigured(
                "An expansion cannot contain another expansion. A branch "
                "inside an expansion, and an expansion inside a branch arm, "
                "are both fine — only expand-within-expand is rejected."
            )
        return subtree
