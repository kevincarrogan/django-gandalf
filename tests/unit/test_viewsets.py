from http import HTTPStatus

import pytest

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import ConfiguredWizard, Wizard
from tests.testapp.forms import FirstStepForm


class _Session(dict):
    modified = False


def test_wizard_viewset_configures_plain_wizard(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

    request = rf.get("/wizard/")
    request.session = _Session()

    response = PlainWizardViewSet.as_view()(request)

    assert response.status_code == HTTPStatus.FOUND
    viewset = PlainWizardViewSet()
    configured = viewset.configure_wizard(viewset.get_wizard(bound_wizard=None))
    assert isinstance(configured, ConfiguredWizard)


def test_wizard_viewset_get_replays_existing_run(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"

    request = rf.get("/wizard/existing-run/")
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {},
            },
        }
    )

    response = PlainWizardViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.OK
    assert response.context_data["form"].__class__ is FirstStepForm


def test_wizard_viewset_post_replays_invalid_step_submission(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"

    request = rf.post("/wizard/existing-run/", data={"name": ""})
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {},
            },
        }
    )

    response = PlainWizardViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.OK
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }


def test_wizard_viewset_post_returns_done_response(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"

        def done(self, bound_wizard):
            from django.http import HttpResponse

            return HttpResponse(f"completed {bound_wizard.run_id}")

    request = rf.post("/wizard/existing-run/", data={"name": "Ada"})
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {},
            },
        }
    )

    response = PlainWizardViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed existing-run"


def test_wizard_viewset_get_returns_done_response_after_complete_path(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"

        def done(self, bound_wizard):
            from django.http import HttpResponse

            return HttpResponse(f"completed {bound_wizard.run_id}")

    request = rf.get("/wizard/existing-run/")
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        }
    )

    response = PlainWizardViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed existing-run"


def test_wizard_viewset_without_done_raises_not_implemented_on_final_step(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"

    request = rf.post("/wizard/existing-run/", data={"name": "Ada"})
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {},
            },
        }
    )

    with pytest.raises(
        NotImplementedError,
        match="WizardViewSet subclasses must define done().",
    ):
        PlainWizardViewSet.as_view()(request, run_id="existing-run")


def test_wizard_viewset_uses_configured_wizard():
    configured_wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(template_name="testapp/single_step_wizard.html")
    )

    class ConfiguredWizardViewSet(WizardViewSet):
        wizard = configured_wizard
        template_name = "testapp/single_step_wizard.html"

    wizard = ConfiguredWizardViewSet().get_wizard(bound_wizard=None)

    assert wizard is configured_wizard


def test_wizard_viewset_does_not_reconfigure_configured_wizard():
    configured_wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(template_name="testapp/single_step_wizard.html")
    )

    class ConfiguredWizardViewSet(WizardViewSet):
        wizard = configured_wizard
        template_name = "testapp/other_wizard.html"

    viewset = ConfiguredWizardViewSet()
    wizard = viewset.configure_wizard(viewset.get_wizard(bound_wizard=None))

    assert wizard is configured_wizard
    assert wizard.tree.form_view.template_name == "testapp/single_step_wizard.html"


def test_wizard_viewset_rejects_invalid_wizard_type():
    class InvalidWizardViewSet(WizardViewSet):
        wizard = object()

    viewset = InvalidWizardViewSet()

    with pytest.raises(
        TypeError,
        match="WizardViewSet.wizard must be a Wizard or ConfiguredWizard",
    ):
        viewset.configure_wizard(viewset.get_wizard(bound_wizard=None))


def test_wizard_viewset_configures_plain_wizard_from_get_wizard(rf):
    class PlainWizardFromGetterViewSet(WizardViewSet):
        template_name = "testapp/single_step_wizard.html"

        def get_wizard(self, bound_wizard):
            return Wizard().step(FirstStepForm)

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

    request = rf.get("/wizard/")
    request.session = _Session()

    response = PlainWizardFromGetterViewSet.as_view()(request)

    assert response.status_code == HTTPStatus.FOUND


def test_wizard_viewset_get_wizard_can_build_tree_from_run_state(rf):
    from tests.testapp.forms import ItemCountForm, ItemForm

    class DynamicViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"

        def get_wizard(self, bound_wizard):
            state = bound_wizard.get_state()
            wizard = Wizard().step(ItemCountForm, context={"step_name": "count"})
            if state:
                count = int(state[0]["step"]["count"])
                for index in range(count):
                    wizard = wizard.step(ItemForm, context={"index": index})
            return wizard

    request = rf.get("/dynamic/existing-run/")
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"count": "3"}}],
                },
            },
        }
    )

    response = DynamicViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.OK
    assert response.context_data["form"].__class__ is ItemForm
