from http import HTTPStatus

from django.test import Client
from django.urls import reverse
import pytest
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from gandalf.viewsets import WizardViewSet
from gandalf.wizards import ConfiguredWizard, Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


class _Session(dict):
    modified = False


@pytest.fixture
def single_step_wizard_url():
    return reverse("single-step-wizard")


@pytest.fixture
def single_step_wizard_run_url():
    def build_url(run_id):
        return reverse("single-step-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def single_step_wizard_without_done_url():
    return reverse("single-step-wizard-without-done")


@pytest.fixture
def single_step_wizard_without_done_run_url():
    def build_url(run_id):
        return reverse("single-step-wizard-without-done-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def single_step_wizard_done_data_url():
    return reverse("single-step-wizard-done-data")


@pytest.fixture
def single_step_wizard_done_data_run_url():
    def build_url(run_id):
        return reverse("single-step-wizard-done-data-run", kwargs={"run_id": run_id})

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


def get_new_run_id_from_session(session, existing_run_ids):
    gandalf_runs = session["gandalf_runs"]
    new_run_ids = set(gandalf_runs) - existing_run_ids
    assert len(new_run_ids) == 1
    return new_run_ids.pop()


def test_wizard_viewset_redirects_to_run_url_on_initialise(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    response = client.get(single_step_wizard_url)
    run_id, run_data = get_only_run_info_from_session(client.session)

    assertRedirects(
        response,
        single_step_wizard_run_url(run_id),
        fetch_redirect_response=False,
    )
    assert run_data == {}


def test_wizard_viewset_delegates_run_get_to_first_step_form(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    client.get(single_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

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
    client.get(single_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(single_step_wizard_run_url(run_id), data={"name": ""})

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)
    assert response.context["form"].errors == {
        "name": ["This field is required."],
    }


def test_single_step_wizard_valid_post_returns_done_response(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    client.get(single_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(single_step_wizard_run_url(run_id), data={"name": "Ada"})

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


def test_single_step_wizard_get_after_valid_post_returns_done_response(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    client.get(single_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(single_step_wizard_run_url(run_id), data={"name": "Ada"})

    response = client.get(single_step_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


def test_single_step_wizard_done_can_read_submitted_form_data(
    client,
    single_step_wizard_done_data_url,
    single_step_wizard_done_data_run_url,
):
    client.get(single_step_wizard_done_data_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        single_step_wizard_done_data_run_url(run_id),
        data={"name": "Ada"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada"


def test_linear_wizard_run_starts_with_first_declared_form(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.get(linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_linear_wizard_valid_first_step_renders_next_declared_form(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="email" name="email"')
    assert client.session["gandalf_runs"][run_id]["submissions"] == [{"name": "Ada"}]


def test_linear_wizard_replaces_invalid_submission_on_next_post(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(linear_wizard_run_url(run_id), data={"name": ""})
    response = client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)
    assert client.session["gandalf_runs"][run_id]["submissions"] == [{"name": "Ada"}]


def test_linear_wizard_get_after_valid_first_step_renders_next_declared_form(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.get(linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="email" name="email"')


def test_wizard_viewset_without_done_raises_not_implemented_on_final_step(
    client,
    single_step_wizard_without_done_url,
    single_step_wizard_without_done_run_url,
):
    client.get(single_step_wizard_without_done_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    with pytest.raises(
        NotImplementedError,
        match="WizardViewSet subclasses must define done().",
    ):
        client.post(
            single_step_wizard_without_done_run_url(run_id), data={"name": "Ada"}
        )


def test_linear_wizard_submissions_do_not_leak_to_new_client(
    linear_wizard_url,
    linear_wizard_run_url,
):
    first_client = Client()
    second_client = Client()
    first_client.get(linear_wizard_url)
    first_run_id, _ = get_only_run_info_from_session(first_client.session)
    second_client.get(linear_wizard_url)
    second_run_id, _ = get_only_run_info_from_session(second_client.session)

    first_client.post(linear_wizard_run_url(first_run_id), data={"name": "Ada"})
    response = second_client.get(linear_wizard_run_url(second_run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_submissions_persist_for_same_client(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.get(linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_linear_wizard_submissions_do_not_leak_to_different_wizard(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
    other_linear_wizard_url,
    other_linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    linear_run_id, _ = get_only_run_info_from_session(client.session)
    client.post(linear_wizard_run_url(linear_run_id), data={"name": "Ada"})

    existing_run_ids = set(client.session["gandalf_runs"])
    client.get(other_linear_wizard_url)
    other_run_id = get_new_run_id_from_session(client.session, existing_run_ids)
    response = client.get(other_linear_wizard_run_url(other_run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_submissions_survive_recreated_declaration(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
    recreated_linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.get(recreated_linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


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
    assert isinstance(PlainWizardViewSet().get_configured_wizard(), ConfiguredWizard)


def test_wizard_viewset_uses_configured_wizard():
    configured_wizard = Wizard().step(FirstStepForm).configure()

    class ConfiguredWizardViewSet(WizardViewSet):
        wizard = configured_wizard

    wizard = ConfiguredWizardViewSet().get_wizard()

    assert wizard is configured_wizard


def test_wizard_viewset_rejects_invalid_wizard_type():
    class InvalidWizardViewSet(WizardViewSet):
        wizard = object()

    with pytest.raises(
        TypeError,
        match="WizardViewSet.wizard must be a Wizard or ConfiguredWizard",
    ):
        InvalidWizardViewSet().get_configured_wizard()


def test_wizard_viewset_configures_plain_wizard_from_get_wizard(rf):
    class PlainWizardFromGetterViewSet(WizardViewSet):
        template_name = "testapp/single_step_wizard.html"

        def get_wizard(self):
            return Wizard().step(FirstStepForm)

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

    request = rf.get("/wizard/")
    request.session = _Session()

    response = PlainWizardFromGetterViewSet.as_view()(request)

    assert response.status_code == HTTPStatus.FOUND


def test_wizard_viewset_allows_get_configured_wizard_override():
    class ConfiguringWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        configured_wizard = None

        def get_configured_wizard(self):
            self.__class__.configured_wizard = super().get_configured_wizard()
            return self.__class__.configured_wizard

    configured_wizard = ConfiguringWizardViewSet().get_configured_wizard()

    assert configured_wizard is ConfiguringWizardViewSet.configured_wizard
    assert isinstance(ConfiguringWizardViewSet.configured_wizard, ConfiguredWizard)
