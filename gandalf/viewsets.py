from django.shortcuts import redirect
from django.views import View

from gandalf.wizards import ConfiguredWizard


class WizardViewSet(View):
    def _require_configured_wizard(self, wizard):
        if not isinstance(wizard, ConfiguredWizard):
            raise TypeError("WizardViewSet.wizard must be a ConfiguredWizard")

        return wizard

    def get_wizard(self):
        wizard = self.wizard
        return self._require_configured_wizard(wizard)

    def get(self, request, *args, run_id=None, **kwargs):
        wizard = self._require_configured_wizard(self.get_wizard())
        if run_id is None:
            bound_wizard = wizard.initialise(request)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        bound_wizard = wizard.bind(request, run_id)
        response = bound_wizard.replay(self.template_name, *args, **kwargs)
        if response is None:
            return self.done(bound_wizard)

        return response

    def post(self, request, *args, run_id, **kwargs):
        wizard = self._require_configured_wizard(self.get_wizard())
        bound_wizard = wizard.bind(request, run_id)
        bound_wizard.submit(
            request.POST.dict(),
            self.template_name,
            *args,
            **kwargs,
        )
        response = bound_wizard.replay(self.template_name, *args, **kwargs)

        if response is None:
            return self.done(bound_wizard)

        return response

    def done(self, bound_wizard):
        raise NotImplementedError("WizardViewSet subclasses must define done().")
