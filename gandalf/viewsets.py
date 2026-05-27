from django.shortcuts import redirect
from django.views import View

from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.wizard import ConfiguredWizard, Wizard


class WizardViewSet(View):
    storage_class = SessionStorage

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
        bound_wizard.bind(wizard)
        return bound_wizard

    def get(self, request, *args, run_id=None, **kwargs):
        bound_wizard = self._make_bound_wizard(request)
        if run_id is None:
            bound_wizard.initialise()
            self._resolve_wizard(bound_wizard)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        bound_wizard.retrieve(run_id)
        self._resolve_wizard(bound_wizard)

        edit_context = bound_wizard.wizard.edit_resolver_class().resolve(request)
        if edit_context is not None:
            return bound_wizard.render_edit(**edit_context)

        response = bound_wizard.replay(*args, **kwargs)
        if response is None:
            return self._finish(bound_wizard)

        return response

    def post(self, request, *args, run_id, **kwargs):
        bound_wizard = self._make_bound_wizard(request)
        bound_wizard.retrieve(run_id)
        self._resolve_wizard(bound_wizard)
        resolver = bound_wizard.wizard.edit_resolver_class()
        edit_context = resolver.resolve(request)
        submission = request.POST.dict()
        files = self._store_uploads(bound_wizard, request.FILES)
        if edit_context is not None:
            resolver.clean_submission(submission)
            bound_wizard.edit(submission, files=files, **edit_context)
        else:
            bound_wizard.submit(submission, *args, files=files, **kwargs)
        response = bound_wizard.replay(*args, **kwargs)

        if response is None:
            return self._finish(bound_wizard)

        return response

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
