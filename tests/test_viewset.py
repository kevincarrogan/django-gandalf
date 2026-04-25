from pytest_django.asserts import assertContains, assertTemplateUsed

from tests.testapp.forms import FirstStepForm


def test_wizard_viewset_renders_form(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_wizard_viewset_delegates_post_to_first_step_form(client):
    response = client.post("/wizard/", data={"name": ""})

    assert response.status_code == 200
    assert isinstance(response.context["form"], FirstStepForm)
    assert response.context["form"].errors == {
        "name": ["This field is required."],
    }
