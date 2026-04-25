from django.views import View


class WizardViewSet(View):
    def dispatch(self, request, *args, **kwargs):
        step_view = self.wizard.start.as_view(
            template_name=self.template_name,
        )
        return step_view(request, *args, **kwargs)
