from django.template import Context, Template

from gandalf.wizards import Wizard
from tests.testapp.forms import FirstStepForm


def render_management_form(context):
    template = Template("{% load gandalf %}{% gandalf_management_form %}")
    return template.render(Context(context))


def test_gandalf_management_form_renders_bound_wizard_run_id(rf):
    request = rf.get("/wizard/")
    request.session = {}
    wizard = Wizard().step(FirstStepForm)
    request.wizard = wizard.bind(request)

    rendered = render_management_form({"request": request})

    assert 'type="hidden"' in rendered
    assert 'name="run_id"' in rendered
    assert f'value="{request.wizard.run_id}"' in rendered
