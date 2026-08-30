"""Squest's "request a service" wizard.

Upstream: `HewlettPackard/squest`,
`service_catalog/views/catalog_views.py` (Apache-2.0) — two steps, where
the second form cannot be built until the first is answered.

**What upstream has to do by hand.** `get_form_kwargs()` runs before the
step it is building, so there is no validated answer to read and it goes
into the raw session instead:

    scope_id = self.storage.data['step_data']['0']['0-quota_scope'][0]
    instance_name = self.storage.data['step_data']['0']['0-name'][0]

Three separate pieces of formtools' storage layout are load-bearing in that
line: steps are keyed by position (`'0'`), fields carry the step prefix
(`'0-quota_scope'`), and every value is a list because it came from a
`QueryDict`. Insert a step at the front and it reads the wrong one, silently
— the key still exists. Rename the field and it raises `KeyError` at
runtime, on the second page.

A Gandalf step view is dispatched behind a validated prefix, so it reads
`cleaned_data` off a step it names. Positions do not appear, prefixes do not
appear, and values are the types the field cleaned them to. Insert a step in
front of it and nothing here changes.
"""

from django import forms
from django.core.validators import MaxValueValidator
from django.http import HttpResponse

from gandalf.form_views import StepFormView
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


#: Stands in for the `Scope` rows upstream looks up: what a team is allowed
#: to spend, which the survey needs so it can cap what it offers.
QUOTA_SCOPES = {
    "platform": {"label": "Platform team", "cpu_limit": 16},
    "research": {"label": "Research team", "cpu_limit": 4},
}


class InstanceForm(forms.Form):
    name = forms.CharField(label="Name this instance")
    quota_scope = forms.ChoiceField(
        label="Which team is this for?",
        choices=[(key, scope["label"]) for key, scope in QUOTA_SCOPES.items()],
    )


class SurveyForm(forms.Form):
    """The operation's survey — upstream builds its fields from the service
    definition, and needs the scope and the instance name to do it."""

    cpus = forms.IntegerField(label="CPUs", min_value=1)

    def __init__(self, quota_scope, instance_name, **kwargs):
        super().__init__(**kwargs)
        self.instance_name = instance_name
        cpu_limit = QUOTA_SCOPES[quota_scope]["cpu_limit"]
        self.fields["cpus"].validators.append(MaxValueValidator(cpu_limit))
        self.fields["cpus"].help_text = (
            f"{QUOTA_SCOPES[quota_scope]['label']} may request up to {cpu_limit} "
            f"for {instance_name}."
        )


class SurveyStepView(StepFormView):
    form_class = SurveyForm
    template_name = "testapp/linear_wizard.html"

    def get_form_kwargs(self):
        # The whole translation, in three lines. Named step, cleaned data,
        # no positions and no prefixes.
        instance = self.request.run.path.find_step(name="instance")
        answers = instance.form.cleaned_data
        return {
            **super().get_form_kwargs(),
            "quota_scope": answers["quota_scope"],
            "instance_name": answers["name"],
        }


request_a_service = (
    Wizard().step(InstanceForm, name="instance").step(SurveyStepView, name="survey")
)


class RequestAServiceViewSet(WizardViewSet):
    description = (
        "Squest's request-a-service wizard, translated: the second form is "
        "built from the first step's answer, read by name rather than out of "
        "raw session storage."
    )
    url_name = "formtools-squest"
    template_name = "testapp/linear_wizard.html"
    wizard = request_a_service

    def done(self, run):
        instance = run.path.find_step(name="instance").form.cleaned_data
        survey = run.path.find_step(name="survey").form.cleaned_data
        return HttpResponse(
            f"Requested {instance['name']} for {instance['quota_scope']} "
            f"with {survey['cpus']} CPUs"
        )
