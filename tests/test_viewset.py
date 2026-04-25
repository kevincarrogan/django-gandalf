import pytest
from django.test import SimpleTestCase


@pytest.mark.xfail(reason="WizardViewSet does not dispatch GET requests yet")
def test_wizard_viewset_delegates_get_request_to_first_step(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    SimpleTestCase().assertTemplateUsed(response, "testapp/single_step_wizard.html")
