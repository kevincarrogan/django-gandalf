from django.views import View


class WizardViewSet(View):
    def dispatch(self, request, *args, **kwargs):
        wizard = self.wizard.bind(request)
        request.wizard = wizard
        current_form_view = wizard.get_current_form_view()

        if request.method == "POST":
            form = current_form_view.form_class(request.POST)

            if form.is_valid():
                wizard.complete_current_step()
                current_form_view = wizard.get_current_form_view()
                step_view = current_form_view.as_view(
                    template_name=self.template_name,
                )
                return step_view(request, *args, **kwargs)

        step_view = current_form_view.as_view(
            template_name=self.template_name,
        )
        return step_view(request, *args, **kwargs)
