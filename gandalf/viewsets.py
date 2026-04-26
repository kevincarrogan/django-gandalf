from django.views import View


class WizardViewSet(View):
    def dispatch(self, request, *args, **kwargs):
        current_form_view = self.wizard.get_current_form_view()
        step_view = current_form_view.as_view(
            template_name=self.template_name,
        )
        return step_view(request, *args, **kwargs)
