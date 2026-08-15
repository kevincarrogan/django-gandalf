from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ImproperlyConfigured

from gandalf import tree
from gandalf.file_storage import WizardFileStorage
from gandalf.form_views import StepFormView, form_view_factory
from gandalf.observers import WizardObserver
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
    "WizardObserver",
    "branch",
    "condition",
    "form_view_factory",
    "on_field",
    "step",
    "switch",
]


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


def step(form_class_or_form_view_class: StepDeclaration, /, **context: Any) -> Wizard:
    """Module-level entry point: returns a Wizard starting with one step."""
    return Wizard().step(form_class_or_form_view_class, **context)


def branch(
    *conditions: tuple[tree.Predicate, Wizard], default: Wizard | None = None
) -> Wizard:
    """Module-level entry point: returns a Wizard starting with one branch."""
    return Wizard().branch(*conditions, default=default)


def switch(
    selector: tree.Selector,
    cases: dict[str, Wizard],
    default: Wizard | None = None,
) -> Wizard:
    """Module-level entry point: returns a Wizard starting with one switch."""
    return Wizard().switch(selector, cases, default=default)


@dataclass(frozen=True)
class on_field:
    """A selector that reads a value straight out of an earlier answer.

    The common case, said declaratively: `on_field("account", "kind")`
    routes on the `kind` field of the step named `account`. Because it
    *is* the answer rather than a computation over it, the dependency is
    data — an outline reports which step and field decide the route, so a
    caller planning ahead can work out where an answer leads instead of
    inferring it. Reach for a plain function whenever the
    decision is anything more than "what did they say".

    Scalar answers only: a multi-valued field has no single value to
    switch on, so route those with a selector of your own.
    """

    step: str
    field: str

    @property
    def __name__(self) -> str:
        return f"{self.step}.{self.field}"

    def __call__(self, request: Any) -> str:
        found = request.wizard.path.find_step(name=self.step)
        if found is None:
            raise ImproperlyConfigured(
                f"on_field({self.step!r}, {self.field!r}) found no answered "
                f"step named {self.step!r} before this switch."
            )
        return str(found.form.cleaned_data.get(self.field, ""))


def _outline(node: tree.Node | None) -> list[dict[str, Any]]:
    """Walk a declared tree into the description `ConfiguredWizard.outline()`
    returns. A sibling of `tree.Formatter`, which walks the same shape into
    indented text."""
    entries: list[dict[str, Any]] = []
    while node is not None:
        if isinstance(node, tree.Step):
            context = node.context or {}
            entries.append(
                {
                    "kind": "step",
                    "name": context.get("name"),
                    "context": dict(context),
                    "declaration": node,
                }
            )
        elif isinstance(node, tree.Switch):
            entries.append(_outline_switch(node))
        elif isinstance(node, tree.Branch):
            entries.append(
                {
                    "kind": "branch",
                    "arms": [
                        {
                            "when": _callable_name(predicate),
                            "description": inspect.getdoc(predicate),
                            "steps": _outline(arm),
                        }
                        for predicate, arm in node.arms
                    ],
                    "default": _outline(node.default),
                }
            )
        else:
            entries.append({"kind": "expand"})
        node = node.next
    return entries


def _outline_switch(node: tree.Switch) -> dict[str, Any]:
    """A switch, with its outcomes named.

    More use to a caller planning ahead than a branch is: the set of
    possible results is declared, so even a selector whose workings are
    opaque says what the answers could be. When the selector is an
    `on_field` the dependency itself is data — which step, which field —
    and the route stops being a guess.
    """
    selector = node.selector
    entry: dict[str, Any] = {
        "kind": "switch",
        "decided_by": _callable_name(selector),
        "description": inspect.getdoc(selector),
        "cases": [
            {"case": case, "steps": _outline(arm)}
            for case, (_, arm) in zip(node.cases, node.arms)
        ],
        "default": _outline(node.default),
    }
    if isinstance(selector, on_field):
        entry["source"] = {"step": selector.step, "field": selector.field}
        # A dataclass carries its class docstring, which describes
        # `on_field` rather than this particular route.
        entry["description"] = None
    return entry


def _callable_name(target: Any) -> str | None:
    return cast("str | None", getattr(target, "__name__", None))


class Wizard:
    def __init__(self, *, tree: tree.Node | None = None) -> None:
        self.tree = tree

    def step(
        self, form_class_or_form_view_class: StepDeclaration, /, **context: Any
    ) -> Wizard:
        """Declare a step. Keyword arguments become the step's context, so
        `name=` is an ordinary context key — the one the default
        `StepNameRouter` reads — and any other key is matched the same way by
        `find_step()` / `filter_steps()`.
        """
        declarations = list(self.tree) if self.tree is not None else []
        declarations.append(
            tree.Step(
                declaration=form_class_or_form_view_class,
                context=context or None,
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

    def switch(
        self,
        selector: tree.Selector,
        cases: dict[str, Wizard],
        default: Wizard | None = None,
    ) -> Wizard:
        """Route on what `selector(request)` returns, one case per outcome.

        The same arbitrary code a predicate may run, asked a different
        question: *which* rather than *whether*. The selector is called
        once per walk however many cases there are, exactly one case can
        apply, and each case's answers are stored under its own name — so
        reordering the cases cannot strand them. A value no case names
        falls to `default`, or past the switch entirely when there is
        none.
        """
        if "default" in cases:
            raise ImproperlyConfigured(
                'A switch case cannot be called "default" — that name is '
                "where the fallback arm's answers are stored. Pass it as "
                "default=... instead."
            )
        declarations = list(self.tree) if self.tree is not None else []
        arms = tuple(
            (tree.CaseGuard(selector=selector, case=case), sub_wizard.tree)
            for case, sub_wizard in cases.items()
        )
        declarations.append(
            tree.Switch(
                arms=arms,
                default=default.tree if default is not None else None,
                selector=selector,
                cases=tuple(cases),
            )
        )
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
    observer_class = WizardObserver
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
        self.observer_class = configuration.get("observer_class", self.observer_class)
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

    def outline(self) -> list[dict[str, Any]]:
        """This wizard's declared shape, as data.

        What `tree.Formatter` prints for a human, in a form something else
        can read: every step in order, every fork with *all* of its
        possible routes, and a marker wherever the tree grows from an
        answer. A description of the declaration, so it needs no run, no
        request and no storage — the same answer before anybody starts and
        after they finish.

        Entries are dicts with a `kind`:

        * `step` — its `name`, its `context`, and the `declaration` itself
          (the one entry that is not JSON; everything else is, and callers
          that want plain data drop it, or replace it with something
          derived from it — a JSON Schema of the step's form, say).
        * `branch` — `arms`, each carrying the `when` and `description` its
          predicate names itself with, and the `steps` it selects; plus the
          `default`. Which arm runs depends on answers, so all are shown.
        * `switch` — `decided_by` and `description` from the selector,
          `cases` named by the value that selects them, `default`, and a
          `source` naming the step and field when the selector is an
          `on_field` and the dependency is therefore knowable.
        * `expand` — a marker and nothing more: an expansion's steps do not
          exist until the answer that shapes them does.

        A dynamic `get_wizard()` is described as it currently resolves,
        which is the honest answer — its shape is a function of the run.
        """
        return _outline(self.tree)

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
