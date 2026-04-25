from pytest_django.asserts import assertTemplateUsed


def test_wizard_viewset_renders(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
