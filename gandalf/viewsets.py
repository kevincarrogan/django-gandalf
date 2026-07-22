from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect
from django.urls import path, reverse
from django.views import View

from gandalf import tree
from gandalf.escapes import Advance, Obliterate, Park
from gandalf.runtime import BoundWizard
from gandalf.storage import RunNotFound, SessionStorage
from gandalf.wizard import ConfiguredWizard, Wizard


class WizardViewSet(View):
    storage_class = SessionStorage
    url_name = None
    # URL kwargs owned by the patterns `urls()` publishes; anything else the
    # request captures is mount-prefix context (e.g. a tenant slug).
    reserved_url_kwargs = frozenset({"run_id", "gandalf_step"})

    @classmethod
    def urls(cls):
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

    def get_wizard(self, bound_wizard):
        """Per-request hook returning the Wizard to use for this dispatch.

        Default implementation returns the class-attribute `wizard` — the
        declarative shortcut. Override to build the tree dynamically; the
        passed `bound_wizard` exposes the current request and (after
        `retrieve()`) the run's stored state via `get_run_data()` /
        `get_state()`.
        """
        wizard = getattr(self, "wizard", None)
        if wizard is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no wizard to run. Define {name}.wizard as a "
                f"Wizard declaration, or override {name}.get_wizard() to "
                "build one per request."
            )
        return wizard

    def configure_wizard(self, wizard):
        configuration = {}
        if hasattr(self, "template_name"):
            configuration["template_name"] = self.template_name

        if isinstance(wizard, ConfiguredWizard):
            return wizard

        if isinstance(wizard, Wizard):
            return wizard.configure(**configuration)

        raise TypeError("WizardViewSet.wizard must be a Wizard or ConfiguredWizard")

    def _make_bound_wizard(self, request):
        storage = self.storage_class(request)
        return BoundWizard(request, storage)

    def _resolve_wizard(self, bound_wizard):
        wizard = self._configured_wizard(self.get_wizard(bound_wizard))
        # Re-resolving a static wizard hands back the same object, so the
        # routability walk is skipped rather than repeated.
        if wizard is not bound_wizard.wizard:
            self._validate_routable(wizard)
            bound_wizard.bind(wizard)
        bound_wizard.urls = self
        return bound_wizard

    def _configured_wizard(self, declared):
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
        cached = getattr(self, "_configured", None)
        if cached is not None and cached[0] is declared:
            return cached[1]
        configured = self.configure_wizard(declared)
        self._configured = (declared, configured)
        return configured

    def _refreshed_cursor(self, bound_wizard, walk, *args, **kwargs):
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

    def _validate_routable(self, wizard):
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
        segments = [router.reverse(step) for step in steps]
        duplicates = sorted({name for name in segments if segments.count(name) > 1})
        if duplicates:
            raise ImproperlyConfigured(
                "Wizard step names must be unique; a URL segment has to name "
                f"exactly one step. Duplicated: {', '.join(duplicates)}."
            )

    def get(self, request, *args, run_id=None, **kwargs):
        bound_wizard = self._make_bound_wizard(request)
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
            return self._finish(bound_wizard)
        return self._redirect_to_cursor(bound_wizard, cursor)

    def post(self, request, *args, run_id, **kwargs):
        bound_wizard = self._make_bound_wizard(request)
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
        submission = request.POST.dict()
        return self._routed_post(
            bound_wizard, route_context, submission, *args, **kwargs
        )

    def _retrieve_run(self, bound_wizard, run_id):
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

    def run_unavailable(self, bound_wizard, reason):
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

    def _routed_get(self, bound_wizard, route_context, *args, **kwargs):
        """Render the step a routed URL addresses.

        The URL is a claim, never an instruction: the cursor's step and
        completed steps render, anything else — unknown, not yet reached,
        or parked in a dormant arm — redirects to where the wizard
        actually is.
        """
        walk = bound_wizard.walk(*args, claim=route_context, **kwargs)
        if not walk.reached:
            return self._redirect_to_cursor(bound_wizard, walk.cursor)
        bound_wizard.mark_rendering(walk.cursor, walk.target.declaration)
        if walk.target.declaration is walk.cursor.node:
            return bound_wizard.dispatcher.render_cursor(walk.cursor, *args, **kwargs)
        return bound_wizard.render_step(
            *args, target=walk.target, url_kwargs=kwargs or None
        )

    def _routed_post(self, bound_wizard, route_context, submission, *args, **kwargs):
        """Put the submission at the step the URL claims.

        One walk decides everything: it replays the stored answers, puts the
        submission at the claimed step, and carries on. Reaching that step is
        the authorisation — a run that cannot get there stores nothing. A
        submission that fails validation is kept so the redirect can render
        it with its errors, and a step that escapes returns the escape's
        redirect.
        """
        files = self._store_uploads(bound_wizard, self.request.FILES)
        walk = bound_wizard.walk(
            *args, claim=route_context, submission=submission, files=files, **kwargs
        )
        if not walk.reached:
            bound_wizard.delete_file_refs(files)
            return self._redirect_to_cursor(bound_wizard, walk.cursor)
        escape = walk.cursor.escape_for(walk.target.declaration)
        if escape is not None:
            return self._escaped(bound_wizard, escape, walk, files)
        bound_wizard.persist(walk)
        return self._continue(
            bound_wizard, self._refreshed_cursor(bound_wizard, walk, *args, **kwargs)
        )

    def _continue(self, bound_wizard, next_cursor):
        if next_cursor.node is None:
            return self._finish(bound_wizard)
        return self._redirect_to_cursor(bound_wizard, next_cursor)

    def _escaped(self, bound_wizard, escape, walk, files):
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

    def _redirect_to_cursor(self, bound_wizard, cursor):
        if cursor.node is not None:
            return redirect(self._step_url_for(bound_wizard, cursor.node))
        return redirect(self.get_wizard_url(bound_wizard.run_id))

    def _step_url_for(self, bound_wizard, step_declaration):
        segment = bound_wizard.wizard.step_router_class().reverse(step_declaration)
        return self.get_step_url(bound_wizard.run_id, segment)

    def get_url_kwargs(self):
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

    def get_start_url(self):
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

    def get_wizard_url(self, run_id):
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

    def get_step_url(self, run_id, step_segment):
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

    def _finish(self, bound_wizard):
        """Complete the run: `done()` fires once, then the run is tombstoned
        so nothing can fire it again.

        The mark is written after `done()` returns, so a `done()` that raises
        leaves the run resumable rather than stranded half-finished.
        """
        response = self.done(bound_wizard)
        bound_wizard.cleanup_files()
        bound_wizard.complete()
        return response

    def _store_uploads(self, bound_wizard, uploaded_files):
        if not uploaded_files:
            return None
        return {
            field: bound_wizard.file_storage.save(bound_wizard.run_id, uploaded_file)
            for field, uploaded_file in uploaded_files.items()
        }

    def done(self, bound_wizard):
        raise NotImplementedError("WizardViewSet subclasses must define done().")
