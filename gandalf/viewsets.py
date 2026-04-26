from http import HTTPStatus

from django.shortcuts import redirect
from django.views import View


class WizardViewSet(View):
    def get(self, request, *args, run_id=None, **kwargs):
        if run_id is None:
            bound_wizard = self.wizard.initialise(request)
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        bound_wizard = self.wizard.bind(request, run_id)
        current_form_view = bound_wizard.get_current_form_view()
        step_view = current_form_view.as_view(
            template_name=self.template_name,
        )
        return step_view(request, *args, **kwargs)

    def post(self, request, *args, run_id, **kwargs):
        bound_wizard = self.wizard.bind(request, run_id)
        current_form_view = bound_wizard.get_current_form_view()
        step_view = current_form_view.as_view(
            template_name=self.template_name,
        )
        response = step_view(request, *args, **kwargs)

        if HTTPStatus(response.status_code).is_redirection:
            bound_wizard.complete_current_step()
            return redirect(self.get_wizard_url(bound_wizard.run_id))

        return response
