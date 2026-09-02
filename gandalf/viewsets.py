from __future__ import annotations

import weakref
from collections.abc import Callable
from enum import Enum
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponseBase
from django.shortcuts import redirect
from django.template.response import SimpleTemplateResponse
from django.urls import URLPattern, path, reverse
from django.views import View

from gandalf import tree
from gandalf.context import WizardContext
from gandalf.escapes import Advance, Escape, Obliterate, Park
from gandalf.file_storage import WizardFileStorage
from gandalf.form_views import form_view_factory
from gandalf.observers import WizardObserver
from gandalf.runtime import (
    Run,
    Cursor,
    CursorWalker,
    RuntimeStep,
    StateSerializer,
    StepDispatcher,
    Walk,
    submission_from_post,
)
from gandalf.storage import RunNotFound, SessionStorage
from gandalf.types import Context, FileRefs, Stash, StorageClass, Submission
from gandalf.wizard import ConfiguredWizard, StepNameRouter, Wizard


class RunUnavailable(str, Enum):
    """Why a request cannot continue a run — the `reason` handed to
    `WizardViewSet.run_unavailable()`. A `str` too, so `"completed"` still
    compares equal."""

    #: The run finished; `done()` has already fired for it.
    COMPLETED = "completed"
    #: Storage raised `RunNotFound`: never started, obliterated, or lost
    #: with an expired session.
    UNKNOWN = "unknown"

    __str__ = str.__str__


def _retire(run: Run) -> None:
    """Everything that outlives `done()` but must not outlive the run.

    Both halves are claims on answers that completion has discarded: the
    uploaded bytes a step's answer names, and the facts a step proved about
    the answers before it. Swept together, after the response has rendered,
    because a completion page reading the run back still needs both —
    `RuntimeStep.form` rebuilds and validates every step.
    """
    run.cleanup_files()
    run.discard_proofs()


class DoorRefused(Exception):
    """Raised when a driven caller opens a run the page's door would refuse.

    A wizard reached over HTTP comes through a dispatch, and anything
    guarding it — a task list checking whether a section is open yet —
    guards it there. A driver comes through `for_context()` instead and
    dispatches nothing, so it is a second door onto the same run, and the
    rules have to be asked at both.

    `reason` says which rule; it is a plain `str` so this module needs to
    know none of them. `EntryUnavailable` in `gandalf.tasklists` holds the
    ones a task list raises.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class WizardViewSet(View):
    """The Django view that publishes a wizard's URLs, runs it one request
    at a time, and completes it once.

    Everything a wizard needs that is not its shape is declared here, as
    class attributes: the template its generated steps render with, where
    runs and uploads are kept, what watches a run, and the runtime classes
    the walk is built from. A `Wizard` is a value — the same rule a `Form`
    and a `FormView` follow — so a wizard declared once can be mounted by
    two viewsets with two templates, and a section of a task list gets its
    seams from the `SectionViewSet` in its slot.
    """

    #: The template every step generated from a bare `Form` renders with. A
    #: step that brings its own `FormView` keeps its own.
    template_name: str | None = None
    #: Where runs are kept. Instantiated once per request with the request's
    #: `WizardContext`, before the wizard is resolved — a dynamic
    #: `get_wizard()` reads the run's stored state to decide its shape.
    storage_class: StorageClass = SessionStorage
    #: Where uploads go, constructed once per run with no arguments.
    file_storage_class: type[Any] = WizardFileStorage
    #: Told what happened to a run, as it happens, without seeing the answers.
    observer_class: type[WizardObserver] = WizardObserver
    #: Turns a bare `Form` into the step view the walk dispatches.
    form_view_factory: Callable[..., Any] = staticmethod(form_view_factory)
    #: The interpreter that replays stored answers and finds the cursor.
    cursor_walker_class: type[CursorWalker] = CursorWalker
    #: Builds the request a step view is dispatched with, and reads its answer.
    step_dispatcher_class: type[StepDispatcher] = StepDispatcher
    #: Flattens a walked tree back into the state storage keeps.
    state_serializer_class: type[StateSerializer] = StateSerializer
    #: Maps a URL step segment to a step and back.
    step_router_class: type[Any] = StepNameRouter
    url_name: str | None = None
    # URL kwargs owned by the patterns `urls()` publishes; anything else the
    # request captures is mount-prefix context (e.g. a tenant slug).
    reserved_url_kwargs = frozenset({"run_id", "gandalf_step"})
    #: One configured wizard per declaration this class has been asked to
    #: run, keyed by the declaration object. See `_configured_wizard()`.
    _configured: weakref.WeakKeyDictionary[Wizard, ConfiguredWizard]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Each class configures with its own attributes, so each keeps its
        # own cache: one wizard mounted by two viewsets is two configured
        # wizards, each rendering with its viewset's template.
        cls._configured = weakref.WeakKeyDictionary()

    @classmethod
    def urls(cls) -> list[URLPattern]:
        """URL patterns for this wizard, derived from `url_name`:
        `<url_name>` (start), `<url_name>-run` (bare run URL), and
        `<url_name>-step` (routed step URL). Mount with
        `path("prefix/", include(MyWizardViewSet.urls()))`.
        """
        if cls.url_name is None:
            raise ImproperlyConfigured(
                "WizardViewSet.urls() requires url_name to be set."
            )
        view = cls.as_view()
        return [
            path("", view, name=cls.url_name),
            path("<uuid:run_id>/", view, name=f"{cls.url_name}-run"),
            path(
                "<uuid:run_id>/<slug:gandalf_step>/",
                view,
                name=f"{cls.url_name}-step",
            ),
        ]

    @classmethod
    def for_context(cls, context: WizardContext) -> tuple[WizardViewSet, Run]:
        """This viewset and a `Run` on it, for an environment.

        The four lines every entry point below starts with, and the door a
        caller with no request comes through: `gandalf.driver` builds a
        context and asks for the pair, rather than manufacturing a browser
        request so that the request-shaped door will open.

        The view is set up with the browser's own request where there is
        one — not a copy, because a view reading `FILES` or `POST` must see
        what was actually uploaded rather than a copy whose input stream
        has already been read to the end.
        """
        view = cls()
        view.setup(context.request or context.http_request(), **context.url_kwargs)
        return view, view._make_run(context)

    @classmethod
    def begin_for(cls, context: WizardContext) -> tuple[WizardViewSet, Run]:
        """`begin()` for a caller that also needs the view — mint the run,
        then resolve. The order is the point, which is why this exists
        rather than being spelled out again by everyone who needs it."""
        view, run = cls.for_context(context)
        view._begin(run)
        return view, run

    @classmethod
    def inspect_for(
        cls, context: WizardContext, run_id: str
    ) -> tuple[WizardViewSet, Run]:
        """`inspect()` for a caller that also needs the view — retrieve the
        run, then resolve, because a dynamic `get_wizard()` is entitled to
        read the run's state to decide its shape."""
        view, run = cls.for_context(context)
        run.retrieve(run_id)
        view._resolve_wizard(run)
        return view, run

    def check_door(self) -> None:
        """Refuse a run this caller may not open, by raising `DoorRefused`.

        Does nothing by default: a wizard mounted on its own is open to
        whoever can reach its URL, and that is the whole of its rule.

        The hook exists because a caller with no request does not go
        through a dispatch, so anything a dispatch would have checked has
        to be asked for here instead. `JourneyScoped` implements it over
        the journey's store, which is what makes a blocked section blocked
        for a driver as well as for a browser.
        """

    @classmethod
    def begin_driven_for(cls, context: WizardContext) -> tuple[WizardViewSet, Run]:
        """`begin_for()` for a caller with no request — the driven door.

        The check goes between resolving the view and minting the run, so a
        refusal leaves nothing behind: no run id, no state, nothing for the
        page above to find and count.
        """
        view, run = cls.for_context(context)
        view.check_door()
        view._begin(run)
        return view, run

    @classmethod
    def inspect_driven_for(
        cls, context: WizardContext, run_id: str
    ) -> tuple[WizardViewSet, Run]:
        """`inspect_for()` for a caller with no request. Refused before the
        run is retrieved: a door that has closed since the run was started
        closes on the run too, exactly as it does when a browser comes back
        to a section whose prerequisite was withdrawn."""
        view, run = cls.for_context(context)
        view.check_door()
        run.retrieve(run_id)
        view._resolve_wizard(run)
        return view, run

    @classmethod
    def resolve_for(cls, context: WizardContext) -> tuple[WizardViewSet, Run]:
        """`resolve()` for a caller that also needs the view — no run is
        created, so there is nothing to retrieve before resolving."""
        view, run = cls.for_context(context)
        view._resolve_wizard(run)
        return view, run

    @classmethod
    def begin(cls, request: HttpRequest, **url_kwargs: Any) -> Run:
        """A fresh run of this wizard, returned rather than redirected to.

        What the start URL does, minus the redirect. The start URL mints a
        run id and hands it straight to a `Location` header; a caller that
        has to *remember* which run a thing is being answered in — a task list
        page tracking one run per section — learns the id at the moment it
        is created instead of having to discover it afterwards.
        `url_kwargs` are mount-prefix context (e.g. a tenant slug),
        forwarded into URL reversing via `get_url_kwargs()`.
        """
        return cls.begin_for(WizardContext.from_request(request, **url_kwargs))[1]

    @classmethod
    def inspect(cls, request: HttpRequest, run_id: str, **url_kwargs: Any) -> Run:
        """This wizard bound to `run_id`, outside its own request cycle.

        The dance every cross-wizard reader needs and no caller should have
        to spell: build the view, hand it the request and any mount-prefix
        kwargs, make a `Run` on this viewset's `storage_class`,
        retrieve the run, then resolve the wizard against it — in that
        order, because a dynamic `get_wizard()` is entitled to read the
        run's state to decide its shape. Afterwards `cursor()`, `path`,
        `step_url()`, `entry_url()` and `run_url` all work exactly as they
        do inside a dispatch.

        Nothing is walked here, so a caller that only wants `get_state()` or
        `is_complete` pays a storage read and no form validation at all.
        Raises `RunNotFound` for a run this storage does not hold. A
        tombstoned run is *found* — it stays addressable so a revisit can be
        answered as finished — so check `is_complete` before running it,
        exactly as a dispatch does.
        """
        return cls.inspect_for(
            WizardContext.from_request(request, **url_kwargs), run_id
        )[1]

    @classmethod
    def reopen(
        cls,
        request: HttpRequest,
        payload: Stash,
        expected_label: str | None = None,
        **url_kwargs: Any,
    ) -> Run:
        """A fresh run seeded from a stash payload, returned rather than
        redirected to — the run behind `resurrect()`.

        Resolution happens *after* seeding, unlike `inspect()`: the state a
        dynamic `get_wizard()` would read is the state the payload just
        supplied. Raises `InvalidStash` — before any run is created — when
        the payload is malformed or its label does not match.
        """
        view, run = cls.for_context(WizardContext.from_request(request, **url_kwargs))
        run.resurrect(payload, expected_label=expected_label)
        view._resolve_wizard(run)
        return run

    @classmethod
    def resurrect(
        cls,
        request: HttpRequest,
        payload: Stash,
        step: str | None = None,
        expected_label: str | None = None,
        **url_kwargs: Any,
    ) -> str | None:
        """Seed a fresh run from a stash payload and return the URL to send
        the user to.

        `step` names the step (URL segment) to land on; without it, the
        run's cursor step — or, for a fully-valid stash, the first step on
        the active route. Never the bare run URL: a resurrected run's
        answers all validate, so a GET there would walk straight to
        completion and fire `done()` before the user edited anything.
        `url_kwargs` are mount-prefix context (e.g. a tenant slug),
        forwarded into URL reversing via `get_url_kwargs()`. Raises
        `InvalidStash` — before any run is created — when the payload is
        malformed or its label does not match `expected_label`.

        Shorthand for `reopen()` plus `entry_url()`; reach for those when
        the new run itself is wanted and not only the URL.
        """
        run = cls.reopen(request, payload, expected_label=expected_label, **url_kwargs)
        return run.entry_url(step)

    @classmethod
    def resolve(cls, request: HttpRequest, **url_kwargs: Any) -> Run:
        """This wizard, bound but not started — no run is created.

        The third thing a caller can want, alongside `begin()` and
        `inspect()`: not to run a wizard, nor to reach a run that exists,
        but to ask what the wizard *is*. `run.wizard.outline()`
        reads its declared shape from here, and asking leaves nothing
        behind.

        A dynamic `get_wizard()` resolves with no stored state to read,
        because there is no run — so it describes itself as it would
        begin, the only honest answer before one exists. `run_id` is
        unset: this is for describing a wizard, not running one.
        """
        return cls.resolve_for(WizardContext.from_request(request, **url_kwargs))[1]

    def _begin(self, run: Run) -> None:
        """Mint the run, resolve the wizard against it, then say it started.

        The single door a fresh run comes through — `begin_for()` and the
        bare start URL both call this, rather than spelling the order out
        twice and leaving one of them to drift. The order is the point:
        `run_started()` is handed a run that has an id and a resolved
        wizard, so it can read `run.wizard` and write
        `run.metadata`.
        """
        run.initialise()
        self._resolve_wizard(run)
        self.run_started(run)

    def run_started(self, run: Run) -> None:
        """A fresh run of this wizard was just created. Does nothing by
        default.

        The counterpart to `done()`, and the only hook that fires **exactly
        once per run** without you having to arrange it. A run is minted
        once, so this is called once — unlike a step view, which is
        re-dispatched on every later request as the walk re-proves stored
        answers, and unlike `done()`, which is the end rather than the
        start.

        That is what makes it the place to set something up outside the
        wizard and remember it in `run.metadata`::

            class ClaimWizardViewSet(WizardViewSet):
                def run_started(self, run):
                    claim = Claim.objects.create(customer=run.context.actor)
                    run.metadata["claim_id"] = claim.pk

                def done(self, run):
                    claim = Claim.objects.get(pk=run.metadata["claim_id"])
                    ...

        Every later request reads `run.metadata["claim_id"]` back —
        from a step view, a branch predicate, `done()`, or a driver — and
        the bag survives completion, so a completion page can still name
        what was created.

        **`reopen()` does not fire this**, and neither does `inspect()`. A
        run seeded from a stash is a continuation, not a start: its metadata
        comes back with its answers, so the claim it created is already
        there. Firing here would open a second one every time a task list section
        is re-entered.

        The cost worth knowing: the bare start URL mints a run and redirects,
        so this fires for a drive-by visit that answers nothing. If that is
        too expensive to do speculatively, do it on first answer instead —
        from the first step's `form_valid()`, guarded on the metadata bag.

        Unlike an observer, this may raise, and a raise propagates to
        whoever asked for the run: a `run_started()` that cannot set its
        record up refuses to start the run rather than starting one that
        lies about having done so.
        """

    def get_wizard(self, run: Run) -> Wizard:
        """Per-request hook returning the Wizard to use for this dispatch.

        Default implementation returns the class-attribute `wizard` — the
        declarative shortcut. Override to build the tree dynamically; the
        passed `run` exposes the current request and (after
        `retrieve()`) the run's stored state via `get_run_data()` /
        `get_state()`.
        """
        wizard: Wizard | None = getattr(self, "wizard", None)
        if wizard is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no wizard to run. Define {name}.wizard as a "
                f"Wizard declaration, or override {name}.get_wizard() to "
                "build one per request."
            )
        return wizard

    def configure_wizard(self, wizard: Wizard) -> ConfiguredWizard:
        """The declaration `get_wizard()` returned, made runnable with this
        viewset's seams: its template for the steps it generates, its
        observer, its walker and the rest. The one place a `ConfiguredWizard`
        is built."""
        if not isinstance(wizard, Wizard):
            raise TypeError("WizardViewSet.wizard must be a Wizard")
        return ConfiguredWizard(
            wizard.tree,
            template_name=self.template_name,
            form_view_factory=self.form_view_factory,
            file_storage_class=self.file_storage_class,
            observer_class=self.observer_class,
            cursor_walker_class=self.cursor_walker_class,
            step_dispatcher_class=self.step_dispatcher_class,
            state_serializer_class=self.state_serializer_class,
            step_router_class=self.step_router_class,
        )

    def context_for(self, request: HttpRequest) -> WizardContext:
        """The environment this request implies, carrying the mount kwargs
        every reverse of this wizard's URLs needs."""
        return WizardContext.from_request(request, **self.get_url_kwargs())

    def _make_run(self, context: WizardContext) -> Run:
        return Run(context, self.storage_class(context))

    def _resolve_wizard(self, run: Run) -> Run:
        wizard = self._configured_wizard(self.get_wizard(run))
        # Re-resolving a static wizard hands back the same object, so the
        # routability walk is skipped rather than repeated.
        if wizard is not run.wizard:
            self._validate_routable(wizard)
            run.bind(wizard)
        run.urls = self
        return run

    def _configured_wizard(self, declared: Wizard) -> ConfiguredWizard:
        """Configure `declared` at most once per class.

        `configure_wizard()` builds a new `ConfiguredWizard` every time it is
        called, which re-runs the tree `Configurer` and regenerates a
        `FormView` class per step. A wizard declared the usual way — a plain
        `Wizard` class attribute — is the very same object on every request,
        so every rebuild would produce an object identical to the first and
        differ only in identity. Keeping the first one, keyed by the
        declaration, spares the rebuild and lets the identity check above
        hold: a POST that re-resolves to the same object skips its refresh
        walk.

        Held weakly so a dynamic `get_wizard()`, which returns a new
        declaration each call, leaves nothing behind once the request has
        dropped it — and correctly gets no reuse, since its tree really can
        have changed.
        """
        try:
            configured = self._configured.get(declared)
        except TypeError:
            # Not a `Wizard`, so not weak-referenceable either. Let
            # `configure_wizard()` refuse it, in its own words.
            return self.configure_wizard(declared)
        if configured is None:
            configured = self.configure_wizard(declared)
            self._configured[declared] = configured
        return configured

    def _refreshed_cursor(
        self, run: Run, walk: Walk, *args: Any, **kwargs: Any
    ) -> Cursor:
        """Re-derive the wizard from the state this request just wrote, then
        walk it again if the tree it describes has changed.

        A dynamic `get_wizard()` reads stored state, so the tree resolved at
        the start of a POST predates that POST's own submission: answering
        the step that decides the shape — a count, a branch key — yields a
        tree that does not yet hold the steps it implies. Judging completion
        against that stale tree fires `done()` mid-run. The recorded render
        context is dropped with it, since the write invalidated that walk.

        Re-resolving to the very same wizard means the tree cannot have
        changed, and `walk` was made from the state that was just persisted,
        so a second walk could only reproduce it.
        """
        run.clear_rendering()
        previous = run.wizard
        self._resolve_wizard(run)
        if run.wizard is previous:
            return walk.cursor
        return run.cursor(*args, **kwargs)

    def _validate_routable(self, wizard: ConfiguredWizard) -> None:
        """Every step must be routable: steps are addressed by URL, so each
        one needs a segment the configured router can derive. Raises for
        any step the router cannot reverse."""
        router = wizard.step_router_class()
        finder = tree.ContextFinder({})
        finder.visit(wizard.tree)
        steps = finder.all()
        unroutable = [step for step in steps if router.reverse(step) is None]
        if unroutable:
            names = ", ".join(step.declaration.__name__ for step in unroutable)
            raise ImproperlyConfigured(
                "Every wizard step needs a routable name; declare steps "
                f"with .step(..., name=...). Unroutable steps: {names}."
            )
        # A segment has to name exactly one step. This is checked here rather
        # than per request because it is a property of the declaration, and
        # because a walk stops at the cursor and so cannot see a duplicate
        # that lies beyond it.
        # Every step reverses by now; the unroutable ones raised above.
        segments = [cast(str, router.reverse(step)) for step in steps]
        duplicates = sorted({name for name in segments if segments.count(name) > 1})
        if duplicates:
            raise ImproperlyConfigured(
                "Wizard step names must be unique; a URL segment has to name "
                f"exactly one step. Duplicated: {', '.join(duplicates)}."
            )

    def get(
        self,
        request: HttpRequest,
        *args: Any,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> HttpResponseBase:
        run = self._make_run(self.context_for(request))
        if run_id is None:
            self._begin(run)
            return redirect(self.get_wizard_url(run.run_id))

        unavailable = self._retrieve_run(run, run_id)
        if unavailable is not None:
            return unavailable
        self._resolve_wizard(run)

        router = run.wizard.step_router_class()
        route_context = router.resolve(kwargs)
        kwargs = router.clean_url_kwargs(kwargs)
        if route_context is not None:
            return self._routed_get(run, route_context, *args, **kwargs)

        cursor = run.cursor(*args, **kwargs)
        if cursor.node is None:
            return self.finish(run)
        return self._redirect_to_cursor(run, cursor)

    def post(
        self, request: HttpRequest, *args: Any, run_id: str, **kwargs: Any
    ) -> HttpResponseBase:
        run = self._make_run(self.context_for(request))
        unavailable = self._retrieve_run(run, run_id)
        if unavailable is not None:
            return unavailable
        self._resolve_wizard(run)

        router = run.wizard.step_router_class()
        route_context = router.resolve(kwargs)
        kwargs = router.clean_url_kwargs(kwargs)
        if route_context is None:
            return self._redirect_to_cursor(run, run.cursor(*args, **kwargs))
        submission = submission_from_post(request.POST)
        return self._routed_post(run, route_context, submission, *args, **kwargs)

    def _retrieve_run(self, run: Run, run_id: str) -> HttpResponseBase | None:
        """Load the run, or return the response for one that cannot be run.

        The availability guard runs before the wizard is resolved: a
        completed run has no state left, and a dynamic `get_wizard()` is
        entitled to read state. Returns None when the run is live and the
        request should carry on.
        """
        try:
            run.retrieve(run_id)
        except RunNotFound:
            return self.run_unavailable(run, reason=RunUnavailable.UNKNOWN)
        if run.is_complete:
            return self.run_unavailable(run, reason=RunUnavailable.COMPLETED)
        return None

    def run_unavailable(self, run: Run, reason: RunUnavailable) -> HttpResponseBase:
        """Response for a run this request cannot continue.

        `reason` is `RunUnavailable.COMPLETED` — the run finished and `done()`
        has already fired for it — or `RunUnavailable.UNKNOWN`: no such run,
        whether never started, obliterated, or lost with an expired session.
        Each compares equal to its string. The default sends the
        user to the wizard's start URL, so refreshing a completion page
        quietly begins a fresh run rather than re-firing `done()`'s side
        effects. Override to render a completion page, raise `Http404`, or
        treat the two reasons differently.
        """
        return redirect(self.get_start_url())

    def _routed_get(
        self,
        run: Run,
        route_context: Context,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        """Render the step a routed URL addresses.

        The URL is a claim, never an instruction: the cursor's step and
        completed steps render, anything else — unknown, not yet reached,
        or parked in a dormant arm — redirects to where the wizard
        actually is.
        """
        walk = run.walk(*args, claim=route_context, **kwargs)
        if not walk.reached:
            return self._redirect_to_cursor(run, walk.cursor)
        # A reached walk always carries the step it arrived at.
        target = cast(RuntimeStep, walk.target)
        run.mark_rendering(walk.cursor, target.declaration)
        if target.declaration is walk.cursor.node:
            return run.dispatcher.render_cursor(walk.cursor, *args, **kwargs)
        return run.render_step(*args, target=target, url_kwargs=kwargs or None)

    def _routed_post(
        self,
        run: Run,
        route_context: Context,
        submission: Submission,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        """Put the submission at the step the URL claims.

        One walk decides everything: it replays the stored answers, puts the
        submission at the claimed step, and carries on. Reaching that step is
        the authorisation — a run that cannot get there stores nothing. A
        submission that fails validation is kept so the redirect can render
        it with its errors, and a step that escapes returns the escape's
        redirect.
        """
        files = run.store_uploads(self.request.FILES)
        walk = run.walk(
            *args, claim=route_context, submission=submission, files=files, **kwargs
        )
        if not walk.reached:
            run.delete_file_refs(files)
            return self._redirect_to_cursor(run, walk.cursor)
        escape = walk.cursor.escape_for(cast(RuntimeStep, walk.target).declaration)
        if escape is not None:
            return self._escaped(run, escape, walk, files)
        run.persist(walk)
        return self._continue(run, self._refreshed_cursor(run, walk, *args, **kwargs))

    def _continue(self, run: Run, next_cursor: Cursor) -> HttpResponseBase:
        if next_cursor.node is None:
            return self.finish(run)
        return self._redirect_to_cursor(run, next_cursor)

    def _escaped(
        self,
        run: Run,
        escape: Escape,
        walk: Walk,
        files: FileRefs | None,
    ) -> HttpResponseBase:
        """Settle what the escape leaves behind, then send the user off.

        Nothing has been persisted yet, so `Park` simply declines to write
        rather than having to undo one. The escape is only ever acted on for
        the submission the user just made; replays of a stored escaping
        answer merely satisfy their step.
        """
        if isinstance(escape, Obliterate):
            run.obliterate()
        elif isinstance(escape, Park):
            run.delete_file_refs(files)
        elif isinstance(escape, Advance):
            run.persist(walk)
        else:
            raise ImproperlyConfigured(
                "Raise Park, Advance or Obliterate to escape a wizard; "
                f"{type(escape).__name__} names no disposition for the run."
            )
        return redirect(
            escape.to,
            *escape.redirect_args,
            permanent=escape.permanent,
            **escape.redirect_kwargs,
        )

    def _redirect_to_cursor(self, run: Run, cursor: Cursor) -> HttpResponseBase:
        if cursor.node is not None:
            # The viewset is the reverser, so a step always has a URL here.
            return redirect(cast(str, run.step_url(cursor.node)))
        return redirect(self.get_wizard_url(run.run_id))

    def get_url_kwargs(self) -> dict[str, Any]:
        """URL kwargs the mount prefix captured (e.g. a tenant slug),
        forwarded into every reverse of this wizard's own URLs.

        The wizard only ever links to itself under the mount the current
        request came in through, so the request's captured kwargs — minus
        the wizard-owned `run_id` / `gandalf_step` — are exactly the
        reverse context. Override when reversing needs context the URL
        does not capture. Reversing from outside a request (an email, a
        management command) is ordinary `reverse()` with explicit kwargs.
        """
        url_kwargs = getattr(self, "kwargs", None) or {}
        return {
            key: value
            for key, value in url_kwargs.items()
            if key not in self.reserved_url_kwargs
        }

    def get_start_url(self) -> str:
        """Reverse the start URL — the one that begins a fresh run. The
        default uses the `<url_name>` pattern published by `urls()`,
        forwarding any mount-prefix kwargs via `get_url_kwargs()`; override
        for a custom URL scheme.
        """
        if self.url_name is None:
            raise ImproperlyConfigured(
                "Set url_name (or override get_start_url) on this WizardViewSet."
            )
        return reverse(self.url_name, kwargs=self.get_url_kwargs())

    def get_wizard_url(self, run_id: str) -> str:
        """Reverse the bare run URL. The default uses the `<url_name>-run`
        pattern published by `urls()`, forwarding any mount-prefix kwargs
        via `get_url_kwargs()`; override for a custom URL scheme.
        """
        if self.url_name is None:
            raise ImproperlyConfigured(
                "Set url_name (or override get_wizard_url) on this WizardViewSet."
            )
        return reverse(
            f"{self.url_name}-run",
            kwargs={**self.get_url_kwargs(), "run_id": run_id},
        )

    def get_step_url(self, run_id: str, step_segment: str | None) -> str:
        """Reverse a routed step URL, mirroring `get_wizard_url`. The
        default uses the `<url_name>-step` pattern published by `urls()`,
        forwarding any mount-prefix kwargs via `get_url_kwargs()`;
        override for a custom URL scheme.
        """
        if self.url_name is None:
            raise ImproperlyConfigured(
                "Set url_name (or override get_step_url) on this WizardViewSet."
            )
        return reverse(
            f"{self.url_name}-step",
            kwargs={
                **self.get_url_kwargs(),
                "run_id": run_id,
                "gandalf_step": step_segment,
            },
        )

    def finish(self, run: Run) -> HttpResponseBase:
        """Complete the run: `done()` fires once, then the run is tombstoned
        so nothing can fire it again.

        The mark is written after `done()` returns, so a `done()` that raises
        leaves the run resumable rather than stranded half-finished.

        This is also the programmatic completion for a caller driving the
        run outside a dispatch — reach a cursor whose `node` is None, then
        call this rather than re-spelling the done/cleanup/complete order.

        A `TemplateResponse` from `done()` is still unrendered here: Django
        renders it later, in the response middleware. So a completion page
        that reads the run back — iterating `wizard.path`, touching a file
        step's `.form` — does its reading after this method has returned,
        and both halves of retiring the run have to allow for that. The
        tree is pinned (`keep_readable()`) before the answers are
        discarded, and the run is retired once the response has rendered
        rather than the moment `done()` returns.

        The tombstone is not deferred with them. A completion template that
        raises would otherwise leave a run whose `done()` has committed its
        side effects and which a refresh can fire again.

        The sweep is the render's to trigger, so a programmatic caller that
        drops an unrendered `TemplateResponse` leaves the run's uploads and
        proofs behind. That response is unusable in that state — reading its
        `.content` raises — so a caller doing it has already discarded what
        it asked for; anything driving a run headlessly wants a rendered or
        plain response from `done()` regardless.
        """
        response = self.done(run)
        run.keep_readable()
        if isinstance(response, SimpleTemplateResponse):
            # Fires immediately if the response is already rendered.
            response.add_post_render_callback(lambda _rendered: _retire(run))
        else:
            _retire(run)
        run.complete()
        return response

    def done(self, run: Run) -> HttpResponseBase:
        raise NotImplementedError("WizardViewSet subclasses must define done().")


# `__init_subclass__` runs for subclasses only; the base keeps a cache of
# its own so a bare `WizardViewSet` can be asked to run a wizard too.
WizardViewSet._configured = weakref.WeakKeyDictionary()
