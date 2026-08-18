from __future__ import annotations

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
from gandalf.runtime import BoundWizard, Cursor, RuntimeStep, Walk, submission_from_post
from gandalf.storage import RunNotFound, SessionStorage
from gandalf.types import Context, FileRefs, Stash, StorageClass, Submission
from gandalf.wizard import ConfiguredWizard, Wizard


class WizardViewSet(View):
    storage_class: StorageClass = SessionStorage
    url_name: str | None = None
    # URL kwargs owned by the patterns `urls()` publishes; anything else the
    # request captures is mount-prefix context (e.g. a tenant slug).
    reserved_url_kwargs = frozenset({"run_id", "gandalf_step"})

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
    def for_context(cls, context: WizardContext) -> tuple[WizardViewSet, BoundWizard]:
        """This viewset and a `BoundWizard` on it, for an environment.

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
        return view, view._make_bound_wizard(context)

    @classmethod
    def begin_for(cls, context: WizardContext) -> tuple[WizardViewSet, BoundWizard]:
        """`begin()` for a caller that also needs the view — mint the run,
        then resolve. The order is the point, which is why this exists
        rather than being spelled out again by everyone who needs it."""
        view, bound_wizard = cls.for_context(context)
        bound_wizard.initialise()
        view._resolve_wizard(bound_wizard)
        return view, bound_wizard

    @classmethod
    def inspect_for(
        cls, context: WizardContext, run_id: str
    ) -> tuple[WizardViewSet, BoundWizard]:
        """`inspect()` for a caller that also needs the view — retrieve the
        run, then resolve, because a dynamic `get_wizard()` is entitled to
        read the run's state to decide its shape."""
        view, bound_wizard = cls.for_context(context)
        bound_wizard.retrieve(run_id)
        view._resolve_wizard(bound_wizard)
        return view, bound_wizard

    @classmethod
    def resolve_for(cls, context: WizardContext) -> tuple[WizardViewSet, BoundWizard]:
        """`resolve()` for a caller that also needs the view — no run is
        created, so there is nothing to retrieve before resolving."""
        view, bound_wizard = cls.for_context(context)
        view._resolve_wizard(bound_wizard)
        return view, bound_wizard

    @classmethod
    def begin(cls, request: HttpRequest, **url_kwargs: Any) -> BoundWizard:
        """A fresh run of this wizard, returned rather than redirected to.

        What the start URL does, minus the redirect. The start URL mints a
        run id and hands it straight to a `Location` header; a caller that
        has to *remember* which run a thing is being answered in — a hub
        page tracking one run per section — learns the id at the moment it
        is created instead of having to discover it afterwards.
        `url_kwargs` are mount-prefix context (e.g. a tenant slug),
        forwarded into URL reversing via `get_url_kwargs()`.
        """
        return cls.begin_for(WizardContext.from_request(request, **url_kwargs))[1]

    @classmethod
    def inspect(
        cls, request: HttpRequest, run_id: str, **url_kwargs: Any
    ) -> BoundWizard:
        """This wizard bound to `run_id`, outside its own request cycle.

        The dance every cross-wizard reader needs and no caller should have
        to spell: build the view, hand it the request and any mount-prefix
        kwargs, make a `BoundWizard` on this viewset's `storage_class`,
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
    ) -> BoundWizard:
        """A fresh run seeded from a stash payload, returned rather than
        redirected to — the run behind `resurrect()`.

        Resolution happens *after* seeding, unlike `inspect()`: the state a
        dynamic `get_wizard()` would read is the state the payload just
        supplied. Raises `InvalidStash` — before any run is created — when
        the payload is malformed or its label does not match.
        """
        view, bound_wizard = cls.for_context(
            WizardContext.from_request(request, **url_kwargs)
        )
        bound_wizard.resurrect(payload, expected_label=expected_label)
        view._resolve_wizard(bound_wizard)
        return bound_wizard

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
        bound_wizard = cls.reopen(
            request, payload, expected_label=expected_label, **url_kwargs
        )
        return bound_wizard.entry_url(step)

    @classmethod
    def resolve(cls, request: HttpRequest, **url_kwargs: Any) -> BoundWizard:
        """This wizard, bound but not started — no run is created.

        The third thing a caller can want, alongside `begin()` and
        `inspect()`: not to run a wizard, nor to reach a run that exists,
        but to ask what the wizard *is*. `bound_wizard.wizard.outline()`
        reads its declared shape from here, and asking leaves nothing
        behind.

        A dynamic `get_wizard()` resolves with no stored state to read,
        because there is no run — so it describes itself as it would
        begin, the only honest answer before one exists. `run_id` is
        unset: this is for describing a wizard, not running one.
        """
        return cls.resolve_for(WizardContext.from_request(request, **url_kwargs))[1]

    def get_wizard(self, bound_wizard: BoundWizard) -> Wizard | ConfiguredWizard:
        """Per-request hook returning the Wizard to use for this dispatch.

        Default implementation returns the class-attribute `wizard` — the
        declarative shortcut. Override to build the tree dynamically; the
        passed `bound_wizard` exposes the current request and (after
        `retrieve()`) the run's stored state via `get_run_data()` /
        `get_state()`.
        """
        wizard: Wizard | ConfiguredWizard | None = getattr(self, "wizard", None)
        if wizard is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no wizard to run. Define {name}.wizard as a "
                f"Wizard declaration, or override {name}.get_wizard() to "
                "build one per request."
            )
        return wizard

    def configure_wizard(self, wizard: Wizard | ConfiguredWizard) -> ConfiguredWizard:
        configuration: dict[str, Any] = {}
        if hasattr(self, "template_name"):
            configuration["template_name"] = self.template_name

        if isinstance(wizard, ConfiguredWizard):
            return wizard

        if isinstance(wizard, Wizard):
            return wizard.configure(**configuration)

        raise TypeError("WizardViewSet.wizard must be a Wizard or ConfiguredWizard")

    def context_for(self, request: HttpRequest) -> WizardContext:
        """The environment this request implies, carrying the mount kwargs
        every reverse of this wizard's URLs needs."""
        return WizardContext.from_request(request, **self.get_url_kwargs())

    def _make_bound_wizard(self, context: WizardContext) -> BoundWizard:
        return BoundWizard(context, self.storage_class(context))

    def _resolve_wizard(self, bound_wizard: BoundWizard) -> BoundWizard:
        wizard = self._configured_wizard(self.get_wizard(bound_wizard))
        # Re-resolving a static wizard hands back the same object, so the
        # routability walk is skipped rather than repeated.
        if wizard is not bound_wizard.wizard:
            self._validate_routable(wizard)
            bound_wizard.bind(wizard)
        bound_wizard.urls = self
        return bound_wizard

    def _configured_wizard(
        self, declared: Wizard | ConfiguredWizard
    ) -> ConfiguredWizard:
        """Configure `declared` at most once per request.

        `configure_wizard()` builds a new `ConfiguredWizard` every time it is
        called, which re-runs the tree `Configurer` and regenerates a
        `FormView` class per step. A POST resolves the wizard twice, and for a
        wizard declared the usual way — a plain `Wizard` class attribute —
        both resolutions are handed the very same declaration, so the second
        rebuild produces an object identical to the first and differs only in
        identity. Caching on the view instance, which Django builds per
        request, spares that rebuild and lets the identity check above hold,
        so the refresh walk is skipped too.

        A dynamic `get_wizard()` returns a new declaration each call and
        correctly gets no reuse — its tree really can have changed.
        """
        cached: tuple[Wizard | ConfiguredWizard, ConfiguredWizard] | None = getattr(
            self, "_configured", None
        )
        if cached is not None and cached[0] is declared:
            return cached[1]
        configured = self.configure_wizard(declared)
        self._configured = (declared, configured)
        return configured

    def _refreshed_cursor(
        self, bound_wizard: BoundWizard, walk: Walk, *args: Any, **kwargs: Any
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
        bound_wizard.clear_rendering()
        previous = bound_wizard.wizard
        self._resolve_wizard(bound_wizard)
        if bound_wizard.wizard is previous:
            return walk.cursor
        return bound_wizard.cursor(*args, **kwargs)

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
        bound_wizard = self._make_bound_wizard(self.context_for(request))
        if run_id is None:
            bound_wizard.initialise()
            self._resolve_wizard(bound_wizard)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        unavailable = self._retrieve_run(bound_wizard, run_id)
        if unavailable is not None:
            return unavailable
        self._resolve_wizard(bound_wizard)

        router = bound_wizard.wizard.step_router_class()
        route_context = router.resolve(kwargs)
        kwargs = router.clean_url_kwargs(kwargs)
        if route_context is not None:
            return self._routed_get(bound_wizard, route_context, *args, **kwargs)

        cursor = bound_wizard.cursor(*args, **kwargs)
        if cursor.node is None:
            return self.finish(bound_wizard)
        return self._redirect_to_cursor(bound_wizard, cursor)

    def post(
        self, request: HttpRequest, *args: Any, run_id: str, **kwargs: Any
    ) -> HttpResponseBase:
        bound_wizard = self._make_bound_wizard(self.context_for(request))
        unavailable = self._retrieve_run(bound_wizard, run_id)
        if unavailable is not None:
            return unavailable
        self._resolve_wizard(bound_wizard)

        router = bound_wizard.wizard.step_router_class()
        route_context = router.resolve(kwargs)
        kwargs = router.clean_url_kwargs(kwargs)
        if route_context is None:
            return self._redirect_to_cursor(
                bound_wizard, bound_wizard.cursor(*args, **kwargs)
            )
        submission = submission_from_post(request.POST)
        return self._routed_post(
            bound_wizard, route_context, submission, *args, **kwargs
        )

    def _retrieve_run(
        self, bound_wizard: BoundWizard, run_id: str
    ) -> HttpResponseBase | None:
        """Load the run, or return the response for one that cannot be run.

        The availability guard runs before the wizard is resolved: a
        completed run has no state left, and a dynamic `get_wizard()` is
        entitled to read state. Returns None when the run is live and the
        request should carry on.
        """
        try:
            bound_wizard.retrieve(run_id)
        except RunNotFound:
            return self.run_unavailable(bound_wizard, reason="unknown")
        if bound_wizard.is_complete:
            return self.run_unavailable(bound_wizard, reason="completed")
        return None

    def run_unavailable(
        self, bound_wizard: BoundWizard, reason: str
    ) -> HttpResponseBase:
        """Response for a run this request cannot continue.

        `reason` is `"completed"` — the run finished and `done()` has already
        fired for it — or `"unknown"`: no such run, whether never started,
        obliterated, or lost with an expired session. The default sends the
        user to the wizard's start URL, so refreshing a completion page
        quietly begins a fresh run rather than re-firing `done()`'s side
        effects. Override to render a completion page, raise `Http404`, or
        treat the two reasons differently.
        """
        return redirect(self.get_start_url())

    def _routed_get(
        self,
        bound_wizard: BoundWizard,
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
        walk = bound_wizard.walk(*args, claim=route_context, **kwargs)
        if not walk.reached:
            return self._redirect_to_cursor(bound_wizard, walk.cursor)
        # A reached walk always carries the step it arrived at.
        target = cast(RuntimeStep, walk.target)
        bound_wizard.mark_rendering(walk.cursor, target.declaration)
        if target.declaration is walk.cursor.node:
            return bound_wizard.dispatcher.render_cursor(walk.cursor, *args, **kwargs)
        return bound_wizard.render_step(*args, target=target, url_kwargs=kwargs or None)

    def _routed_post(
        self,
        bound_wizard: BoundWizard,
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
        files = bound_wizard.store_uploads(self.request.FILES)
        walk = bound_wizard.walk(
            *args, claim=route_context, submission=submission, files=files, **kwargs
        )
        if not walk.reached:
            bound_wizard.delete_file_refs(files)
            return self._redirect_to_cursor(bound_wizard, walk.cursor)
        escape = walk.cursor.escape_for(cast(RuntimeStep, walk.target).declaration)
        if escape is not None:
            return self._escaped(bound_wizard, escape, walk, files)
        bound_wizard.persist(walk)
        return self._continue(
            bound_wizard, self._refreshed_cursor(bound_wizard, walk, *args, **kwargs)
        )

    def _continue(
        self, bound_wizard: BoundWizard, next_cursor: Cursor
    ) -> HttpResponseBase:
        if next_cursor.node is None:
            return self.finish(bound_wizard)
        return self._redirect_to_cursor(bound_wizard, next_cursor)

    def _escaped(
        self,
        bound_wizard: BoundWizard,
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
            bound_wizard.obliterate()
        elif isinstance(escape, Park):
            bound_wizard.delete_file_refs(files)
        elif isinstance(escape, Advance):
            bound_wizard.persist(walk)
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

    def _redirect_to_cursor(
        self, bound_wizard: BoundWizard, cursor: Cursor
    ) -> HttpResponseBase:
        if cursor.node is not None:
            # The viewset is the reverser, so a step always has a URL here.
            return redirect(cast(str, bound_wizard.step_url(cursor.node)))
        return redirect(self.get_wizard_url(bound_wizard.run_id))

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

    def finish(self, bound_wizard: BoundWizard) -> HttpResponseBase:
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
        discarded, and the files are swept once the response has rendered
        rather than the moment `done()` returns.

        The tombstone is not deferred with them. A completion template that
        raises would otherwise leave a run whose `done()` has committed its
        side effects and which a refresh can fire again.

        The sweep is the render's to trigger, so a programmatic caller that
        drops an unrendered `TemplateResponse` leaves the run's uploads
        behind. That response is unusable in that state — reading its
        `.content` raises — so a caller doing it has already discarded what
        it asked for; anything driving a run headlessly wants a rendered or
        plain response from `done()` regardless.
        """
        response = self.done(bound_wizard)
        bound_wizard.keep_readable()
        if isinstance(response, SimpleTemplateResponse):
            # Fires immediately if the response is already rendered.
            response.add_post_render_callback(
                lambda _rendered: bound_wizard.cleanup_files()
            )
        else:
            bound_wizard.cleanup_files()
        bound_wizard.complete()
        return response

    def done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        raise NotImplementedError("WizardViewSet subclasses must define done().")
