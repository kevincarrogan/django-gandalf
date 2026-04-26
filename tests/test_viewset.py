from http import HTTPStatus

from django.test import Client
from django.urls import reverse
import pytest
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from tests.testapp.forms import FirstStepForm, SecondStepForm


@pytest.fixture
def single_step_wizard_url():
    return reverse("single-step-wizard")


@pytest.fixture
def single_step_wizard_run_url():
    def build_url(run_id):
        return reverse("single-step-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def linear_wizard_url():
    return reverse("linear-wizard")


@pytest.fixture
def linear_wizard_run_url():
    def build_url(run_id):
        return reverse("linear-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def other_linear_wizard_url():
    return reverse("other-linear-wizard")


@pytest.fixture
def other_linear_wizard_run_url():
    def build_url(run_id):
        return reverse("other-linear-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def recreated_linear_wizard_url():
    return reverse("recreated-linear-wizard")


@pytest.fixture
def recreated_linear_wizard_run_url():
    def build_url(run_id):
        return reverse("recreated-linear-wizard-run", kwargs={"run_id": run_id})

    return build_url


def get_only_run_info_from_session(session):
    gandalf_runs = session["gandalf_runs"]
    assert len(gandalf_runs) == 1
    return list(gandalf_runs.items())[0]


def initialise_wizard_run(client, wizard_url):
    existing_run_ids = set(client.session.get("gandalf_runs", {}))
    response = client.get(wizard_url)
    gandalf_runs = client.session["gandalf_runs"]
    new_run_ids = set(gandalf_runs) - existing_run_ids
    assert len(new_run_ids) == 1
    run_id = new_run_ids.pop()
    assert response.status_code == HTTPStatus.FOUND
    return run_id, gandalf_runs[run_id], response


def test_wizard_viewset_redirects_to_run_url_on_initialise(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    run_id, run_data, response = initialise_wizard_run(client, single_step_wizard_url)

    assertRedirects(
        response,
        single_step_wizard_run_url(run_id),
        fetch_redirect_response=False,
    )
    assert run_data == {"current_step_index": 0}


def test_wizard_viewset_delegates_run_get_to_first_step_form(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, single_step_wizard_url)

    response = client.get(single_step_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_wizard_viewset_delegates_run_post_to_first_step_form(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, single_step_wizard_url)

    response = client.post(single_step_wizard_run_url(run_id), data={"name": ""})

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)
    assert response.context["form"].errors == {
        "name": ["This field is required."],
    }


def test_linear_wizard_run_starts_with_first_declared_form(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, linear_wizard_url)

    response = client.get(linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_linear_wizard_valid_first_step_redirects_to_run_url(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, linear_wizard_url)

    response = client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})

    assertRedirects(
        response,
        linear_wizard_run_url(run_id),
        fetch_redirect_response=False,
    )


def test_linear_wizard_get_after_valid_first_step_renders_next_declared_form(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, linear_wizard_url)

    client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.get(linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="email" name="email"')


def test_linear_wizard_progress_does_not_leak_to_new_client(
    linear_wizard_url,
    linear_wizard_run_url,
):
    first_client = Client()
    second_client = Client()
    first_run_id, _, _ = initialise_wizard_run(first_client, linear_wizard_url)
    second_run_id, _, _ = initialise_wizard_run(second_client, linear_wizard_url)

    first_client.post(linear_wizard_run_url(first_run_id), data={"name": "Ada"})
    response = second_client.get(linear_wizard_run_url(second_run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_progress_persists_for_same_client(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, linear_wizard_url)

    client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.get(linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_linear_wizard_progress_does_not_leak_to_different_wizard(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
    other_linear_wizard_url,
    other_linear_wizard_run_url,
):
    linear_run_id, _, _ = initialise_wizard_run(client, linear_wizard_url)
    client.post(linear_wizard_run_url(linear_run_id), data={"name": "Ada"})

    other_run_id, _, _ = initialise_wizard_run(client, other_linear_wizard_url)
    response = client.get(other_linear_wizard_run_url(other_run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_progress_survives_recreated_declaration(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
    recreated_linear_wizard_run_url,
):
    run_id, _, _ = initialise_wizard_run(client, linear_wizard_url)

    client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.get(recreated_linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)
