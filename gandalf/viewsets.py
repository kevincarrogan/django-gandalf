from django.shortcuts import redirect
from django.views import View


class WizardViewSet(View):
    def get(self, request, *args, run_id=None, **kwargs):
        if run_id is None:
            bound_wizard = self.wizard.initialise(request)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        bound_wizard = self.wizard.bind(request, run_id)
        response = bound_wizard.replay(self.template_name, *args, **kwargs)
        if response is None:
            return self.done(bound_wizard)

        return response

    def post(self, request, *args, run_id, **kwargs):
        bound_wizard = self.wizard.bind(request, run_id)
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
