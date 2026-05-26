from django.shortcuts import redirect
from django.views import View

from gandalf.runtime import BoundWizard
from gandalf.storage import SessionStorage
from gandalf.wizard import ConfiguredWizard, Wizard


EDIT_STEP_FIELD = "gandalf_edit_step"


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

        edit_step = request.GET.get(EDIT_STEP_FIELD)
        if edit_step:
            return bound_wizard.render_edit(step_name=edit_step)

        response = bound_wizard.replay(*args, **kwargs)
        if response is None:
            return self.done(bound_wizard)

        return response

    def post(self, request, *args, run_id, **kwargs):
        bound_wizard = self._make_bound_wizard(request)
        bound_wizard.retrieve(run_id)
        self._resolve_wizard(bound_wizard)
        submission = request.POST.dict()
        edit_step = submission.pop(EDIT_STEP_FIELD, None)
        if edit_step:
            bound_wizard.edit(submission, step_name=edit_step)
        else:
            bound_wizard.submit(submission, *args, **kwargs)
        response = bound_wizard.replay(*args, **kwargs)

        if response is None:
            return self.done(bound_wizard)

        return response

    def done(self, bound_wizard):
        raise NotImplementedError("WizardViewSet subclasses must define done().")
