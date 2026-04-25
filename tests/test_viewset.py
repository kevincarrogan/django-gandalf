from pytest_django.asserts import assertTemplateUsed

from tests.testapp.forms import FirstStepForm


def test_wizard_viewset_renders(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/single_step_wizard.html")


def test_wizard_viewset_renders_first_step_form(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assert isinstance(response.context["form"], FirstStepForm)
