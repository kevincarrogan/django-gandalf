import pytest
from pytest_django.asserts import assertContains, assertTemplateUsed

from tests.testapp.forms import FirstStepForm


def test_wizard_viewset_renders_form(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


@pytest.mark.xfail(
    reason="Generated step views do not inherit viewset get_context_data yet.",
)
def test_generated_step_view_uses_viewset_context_data(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assert response.context["step_title"] == "First step"


def test_wizard_viewset_delegates_post_to_first_step_form(client):
    response = client.post("/wizard/", data={"name": ""})

    assert response.status_code == 200
    assert isinstance(response.context["form"], FirstStepForm)
    assert response.context["form"].errors == {
        "name": ["This field is required."],
    }


@pytest.mark.xfail(
    reason="Wizard.step() overwrites the current form view instead of preserving an ordered journey.",
)
def test_linear_wizard_starts_with_first_declared_form(client):
    response = client.get("/linear-wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')
