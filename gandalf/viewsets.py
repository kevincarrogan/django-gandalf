from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect
from django.urls import path, reverse
from django.views import View

from gandalf import tree
from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.wizard import ConfiguredWizard, Wizard


class WizardViewSet(View):
    storage_class = SessionStorage
    url_name = None

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
        return self.wizard

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
        wizard = self.configure_wizard(self.get_wizard(bound_wizard))
        self._validate_routable(wizard)
        bound_wizard.bind(wizard)
        bound_wizard.urls = self
        return bound_wizard

    def _validate_routable(self, wizard):
        """Every step must be routable: steps are addressed by URL, so each
        one needs a segment the configured router can derive. Raises for
        any step the router cannot reverse."""
        router = wizard.step_router_class()
        finder = tree.ContextFinder({})
        finder.visit(wizard.tree)
        unroutable = [
            step for step in finder.all() if router.reverse(step) is None
        ]
        if unroutable:
            names = ", ".join(
                step.declaration.__name__ for step in unroutable
            )
            raise ImproperlyConfigured(
                "Every wizard step needs a routable name; declare steps "
                f"with .step(..., name=...). Unroutable steps: {names}."
            )

    def get(self, request, *args, run_id=None, **kwargs):
        bound_wizard = self._make_bound_wizard(request)
        if run_id is None:
            bound_wizard.initialise()
            self._resolve_wizard(bound_wizard)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        bound_wizard.retrieve(run_id)
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
        bound_wizard.retrieve(run_id)
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

    def _routed_get(self, bound_wizard, route_context, *args, **kwargs):
        """Render the step a routed URL addresses.

        The URL is a claim, never an instruction: the cursor's step and
        completed steps render, anything else — unknown, not yet reached,
        or parked in a dormant arm — redirects to where the wizard
        actually is.
        """
        cursor = bound_wizard.cursor(*args, **kwargs)
        target = bound_wizard.find_step_at(cursor, **route_context)
        if target is not None and target.declaration is cursor.node:
            bound_wizard.mark_rendering(cursor, cursor.node)
            return bound_wizard.dispatcher.render_cursor(cursor, *args, **kwargs)
        if target is not None and target.data is not None:
            bound_wizard.mark_rendering(cursor, target.declaration)
            return bound_wizard.render_edit(
                *args, target=target, url_kwargs=kwargs or None
            )
        return self._redirect_to_cursor(bound_wizard, cursor)

    def _routed_post(self, bound_wizard, route_context, submission, *args, **kwargs):
        """Apply a routed submission: the cursor's step submits, a completed
        step edits, anything else redirects to the cursor without storing
        the payload or its uploads. Successful writes redirect (PRG); a
        rejected edit returns its error render directly."""
        cursor = bound_wizard.cursor(*args, **kwargs)
        target = bound_wizard.find_step_at(cursor, **route_context)
        if target is not None and target.declaration is cursor.node:
            files = self._store_uploads(bound_wizard, self.request.FILES)
            bound_wizard.submit(submission, *args, files=files, **kwargs)
        elif target is not None and target.data is not None:
            files = self._store_uploads(bound_wizard, self.request.FILES)
            bound_wizard.mark_rendering(cursor, target.declaration)
            edit_response = bound_wizard.edit(
                submission,
                *args,
                cursor=cursor,
                target=target,
                files=files,
                url_kwargs=kwargs or None,
            )
            if edit_response is not None:
                return edit_response
        else:
            return self._redirect_to_cursor(bound_wizard, cursor)

        next_cursor = bound_wizard.cursor(*args, **kwargs)
        if next_cursor.node is None:
            return self._finish(bound_wizard)
        return self._redirect_to_cursor(bound_wizard, next_cursor)

    def _redirect_to_cursor(self, bound_wizard, cursor):
        if cursor.node is not None:
            return redirect(self._step_url_for(bound_wizard, cursor.node))
        return redirect(self.get_wizard_url(bound_wizard.run_id))

    def _step_url_for(self, bound_wizard, step_declaration):
        segment = bound_wizard.wizard.step_router_class().reverse(step_declaration)
        return self.get_step_url(bound_wizard.run_id, segment)

    def get_wizard_url(self, run_id):
        """Reverse the bare run URL. The default uses the `<url_name>-run`
        pattern published by `urls()`; override for a custom URL scheme.
        """
        if self.url_name is None:
            raise ImproperlyConfigured(
                "Set url_name (or override get_wizard_url) on this "
                "WizardViewSet."
            )
        return reverse(f"{self.url_name}-run", kwargs={"run_id": run_id})

    def get_step_url(self, run_id, step_segment):
        """Reverse a routed step URL, mirroring `get_wizard_url`. The
        default uses the `<url_name>-step` pattern published by `urls()`;
        override for a custom URL scheme.
        """
        if self.url_name is None:
            raise ImproperlyConfigured(
                "Set url_name (or override get_step_url) on this "
                "WizardViewSet."
            )
        return reverse(
            f"{self.url_name}-step",
            kwargs={"run_id": run_id, "gandalf_step": step_segment},
        )

    def _finish(self, bound_wizard):
        response = self.done(bound_wizard)
        bound_wizard.cleanup_files()
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
