from django.test import Client
import pytest
from pytest_django.asserts import assertContains, assertTemplateUsed

from tests.testapp.forms import FirstStepForm, SecondStepForm


def run_id_from_response(response):
    return response.wsgi_request.wizard.run_id


def test_wizard_viewset_renders_form(client):
    response = client.get("/wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_wizard_viewset_renders_management_form_with_run_id(client):
    response = client.get("/linear-wizard/")
    run_id = run_id_from_response(response)

    assert response.status_code == 200
    assertContains(response, 'name="run_id"')
    assertContains(response, f'value="{run_id}"')


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


def test_linear_wizard_starts_with_first_declared_form(client):
    response = client.get("/linear-wizard/")

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_linear_wizard_valid_first_step_renders_next_declared_form(client, db):
    response = client.post("/linear-wizard/", data={"name": "Ada"})

    assert response.status_code == 200
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assertContains(response, '<input type="email" name="email"')


def test_linear_wizard_progress_does_not_leak_to_new_client(db):
    first_client = Client()
    second_client = Client()
    response = first_client.get("/linear-wizard/")
    run_id = run_id_from_response(response)

    first_client.post(
        "/linear-wizard/",
        data={"name": "Ada", "run_id": run_id},
    )
    response = second_client.get("/linear-wizard/")

    assert response.status_code == 200
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_progress_persists_for_same_client(client, db):
    response = client.get("/linear-wizard/")
    run_id = run_id_from_response(response)

    client.post(
        "/linear-wizard/",
        data={"name": "Ada", "run_id": run_id},
    )
    response = client.get("/linear-wizard/", data={"run_id": run_id})

    assert response.status_code == 200
    assert isinstance(response.context["form"], SecondStepForm)


def test_linear_wizard_progress_does_not_leak_to_different_wizard(client, db):
    response = client.get("/linear-wizard/")
    run_id = run_id_from_response(response)

    client.post(
        "/linear-wizard/",
        data={"name": "Ada", "run_id": run_id},
    )

    response = client.get("/other-linear-wizard/")

    assert response.status_code == 200
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_progress_survives_recreated_declaration(client, db):
    response = client.get("/linear-wizard/")
    run_id = run_id_from_response(response)

    client.post(
        "/linear-wizard/",
        data={"name": "Ada", "run_id": run_id},
    )

    response = client.get(
        "/recreated-linear-wizard/",
        data={"run_id": run_id},
    )

    assert response.status_code == 200
    assert isinstance(response.context["form"], SecondStepForm)
