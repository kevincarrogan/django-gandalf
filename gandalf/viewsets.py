from django.shortcuts import redirect
from django.views import View


class WizardViewSet(View):
    def get(self, request, *args, run_id=None, **kwargs):
        if run_id is None:
            bound_wizard = self.wizard.initialise(request)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        bound_wizard = self.wizard.bind(request, run_id)
        response = self.dispatch_current_step(request, bound_wizard, *args, **kwargs)
        if response is None:
            return self.done(bound_wizard)

        return response

    def post(self, request, *args, run_id, **kwargs):
        bound_wizard = self.wizard.bind(request, run_id)
        bound_wizard.save_current_step_data(
            request.POST.dict(),
            self.template_name,
            *args,
            **kwargs,
        )
        response = self.dispatch_current_step(request, bound_wizard, *args, **kwargs)

        if response is None:
            return self.done(bound_wizard)

        return response

    def done(self, bound_wizard):
        raise NotImplementedError("WizardViewSet subclasses must define done().")

    def dispatch_current_step(self, request, bound_wizard, *args, **kwargs):
        return bound_wizard.dispatch_next_incomplete_step(
            self.template_name,
            *args,
            **kwargs,
        )
