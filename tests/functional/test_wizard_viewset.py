import tempfile
from http import HTTPStatus

from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
import pytest
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from tests.testapp.forms import (
    BusinessDetailsForm,
    FirstStepForm,
    PersonalDetailsForm,
    ReviewForm,
    SecondStepForm,
)


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
def single_step_wizard_done_run_data_url():
    return reverse("single-step-wizard-done-run-data")


@pytest.fixture
def single_step_wizard_done_run_data_run_url():
    def build_url(run_id):
        return reverse(
            "single-step-wizard-done-run-data-run", kwargs={"run_id": run_id}
        )

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
def done_linear_wizard_url():
    return reverse("done-linear-wizard")


@pytest.fixture
def done_linear_wizard_run_url():
    def build_url(run_id):
        return reverse("done-linear-wizard-run", kwargs={"run_id": run_id})

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


@pytest.fixture
def done_branching_wizard_url():
    return reverse("done-branching-wizard")


@pytest.fixture
def done_branching_wizard_run_url():
    def build_url(run_id):
        return reverse("done-branching-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def branching_wizard_url():
    return reverse("branching-wizard")


@pytest.fixture
def branching_wizard_run_url():
    def build_url(run_id):
        return reverse("branching-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def empty_wizard_url():
    return reverse("empty-wizard")


@pytest.fixture
def empty_wizard_run_url():
    def build_url(run_id):
        return reverse("empty-wizard-run", kwargs={"run_id": run_id})

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


def test_single_step_wizard_done_can_read_run_data(
    client,
    single_step_wizard_done_run_data_url,
    single_step_wizard_done_run_data_run_url,
):
    client.get(single_step_wizard_done_run_data_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        single_step_wizard_done_run_data_run_url(run_id),
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
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
    ]


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
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
    ]


def test_linear_wizard_preserves_valid_previous_submission_when_posting_next_step(
    client,
    done_linear_wizard_url,
    done_linear_wizard_run_url,
):
    client.get(done_linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(done_linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.post(
        done_linear_wizard_run_url(run_id),
        data={"email": "ada@example.com"},
    )

    assert response.status_code == HTTPStatus.OK
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_linear_wizard_done_can_read_submitted_form_data_from_each_step(
    client,
    done_linear_wizard_url,
    done_linear_wizard_run_url,
):
    client.get(done_linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(done_linear_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.post(
        done_linear_wizard_run_url(run_id),
        data={"email": "ada@example.com"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"


def test_linear_wizard_does_not_append_submission_after_done(
    client,
    done_linear_wizard_url,
    done_linear_wizard_run_url,
):
    client.get(done_linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(done_linear_wizard_run_url(run_id), data={"name": "Ada"})
    client.post(done_linear_wizard_run_url(run_id), data={"email": "ada@example.com"})
    response = client.post(
        done_linear_wizard_run_url(run_id),
        data={"email": "grace@example.com"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]


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


def test_branching_wizard_valid_step_renders_first_step_in_matching_branch(
    client,
    branching_wizard_url,
    branching_wizard_run_url,
):
    client.get(branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        branching_wizard_run_url(run_id),
        data={"account_type": "business"},
    )

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], BusinessDetailsForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="text" name="business_name"')
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "business"}},
    ]


def test_branching_wizard_valid_step_renders_first_step_in_default_branch(
    client,
    branching_wizard_url,
    branching_wizard_run_url,
):
    client.get(branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        branching_wizard_run_url(run_id),
        data={"account_type": "personal"},
    )

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], PersonalDetailsForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="text" name="preferred_name"')
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "personal"}},
    ]


def test_branching_wizard_post_inside_arm_records_nested_state(
    client,
    branching_wizard_url,
    branching_wizard_run_url,
):
    client.get(branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        branching_wizard_run_url(run_id),
        data={"account_type": "business"},
    )

    response = client.post(
        branching_wizard_run_url(run_id),
        data={"business_name": "Acme"},
    )

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], ReviewForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]


def test_done_branching_wizard_complete_flow_uses_runtime_tree(
    client,
    done_branching_wizard_url,
    done_branching_wizard_run_url,
):
    client.get(done_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        done_branching_wizard_run_url(run_id), data={"account_type": "business"}
    )
    client.post(done_branching_wizard_run_url(run_id), data={"business_name": "Acme"})
    client.post(done_branching_wizard_run_url(run_id), data={"confirmed": "on"})
    response = client.post(
        done_branching_wizard_run_url(run_id),
        data={"email": "ada@example.com"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"completed 4 via ReviewForm missing=None account_count=1 declared_count=5"
    )


@pytest.fixture
def editing_branching_wizard_url():
    return reverse("editing-branching-wizard")


@pytest.fixture
def editing_branching_wizard_run_url():
    def build_url(run_id):
        return reverse("editing-branching-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_editing_branching_wizard_get_with_edit_param_renders_form_with_initial(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    from tests.testapp.forms import AccountTypeForm

    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"account_type": "business"},
    )
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"business_name": "Acme"},
    )

    response = client.get(
        editing_branching_wizard_run_url(run_id) + "?gandalf_edit_step=account_type",
    )

    assert response.status_code == HTTPStatus.OK
    form = response.context["form"]
    assert isinstance(form, AccountTypeForm)
    assert form.is_bound is False
    assert form.initial == {"account_type": "business"}


def test_editing_branching_wizard_post_edit_keeping_arm_preserves_downstream(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"account_type": "business"},
    )
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"business_name": "Acme"},
    )

    response = client.post(
        editing_branching_wizard_run_url(run_id),
        data={"gandalf_edit_step": "account_type", "account_type": "business"},
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]


def test_editing_branching_wizard_post_edit_changing_arm_truncates_downstream(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"account_type": "business"},
    )
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"business_name": "Acme"},
    )

    response = client.post(
        editing_branching_wizard_run_url(run_id),
        data={"gandalf_edit_step": "account_type", "account_type": "personal"},
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], PersonalDetailsForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "personal"}},
        {"branch": []},
    ]


def test_editing_branching_wizard_post_edit_strips_marker_from_submission(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"account_type": "business"},
    )

    client.post(
        editing_branching_wizard_run_url(run_id),
        data={"gandalf_edit_step": "account_type", "account_type": "business"},
    )

    stored = client.session["gandalf_runs"][run_id]["state"][0]["step"]
    assert "gandalf_edit_step" not in stored


def test_branch_entry_wizard_renders_default_arm_first_step(client):
    start_url = reverse("branch-entry-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("branch-entry-wizard-run", kwargs={"run_id": run_id})

    response = client.get(run_url)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_find_step_raises_when_multiple_steps_share_context(client):
    start_url = reverse("duplicate-context-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("duplicate-context-wizard-run", kwargs={"run_id": run_id})

    client.post(run_url, data={"name": "Ada"})
    response = client.post(run_url, data={"email": "ada@example.com"})

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"raised MultipleStepsReturned"


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
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    first_client = client
    second_client = client.__class__()
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


def test_wizard_viewset_rejects_invalid_wizard_type(client):
    with pytest.raises(
        TypeError,
        match="WizardViewSet.wizard must be a Wizard or ConfiguredWizard",
    ):
        client.get(reverse("invalid-wizard"))


def test_wizard_viewset_accepts_form_view_step(client):
    start_url = reverse("form-view-step-wizard")
    response = client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("form-view-step-wizard-run", kwargs={"run_id": run_id})

    assertRedirects(response, run_url, fetch_redirect_response=False)

    response = client.get(run_url)
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)

    response = client.post(run_url, data={"name": "Ada"})
    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


def test_wizard_viewset_raises_when_form_step_has_no_template_name(client):
    with pytest.raises(
        ImproperlyConfigured,
        match="template_name",
    ):
        client.get(reverse("missing-template-wizard"))


def test_wizard_viewset_accepts_pre_configured_wizard(client):
    start_url = reverse("pre-configured-wizard")
    response = client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("pre-configured-wizard-run", kwargs={"run_id": run_id})

    assertRedirects(response, run_url, fetch_redirect_response=False)

    response = client.get(run_url)
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)

    response = client.post(run_url, data={"name": "Ada"})
    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


def test_wizard_viewset_rejects_reconfiguring_configured_wizard(client):
    with pytest.raises(
        ImproperlyConfigured,
        match="ConfiguredWizard instances cannot be configured.",
    ):
        client.get(reverse("double-configured-wizard"))


def test_dynamic_wizard_generates_step_per_chosen_count(client):
    start_url = reverse("dynamic-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("dynamic-wizard-run", kwargs={"run_id": run_id})

    first_response = client.get(run_url)
    assert first_response.status_code == HTTPStatus.OK
    assert "count" in first_response.context["form"].fields

    client.post(run_url, data={"count": "3"})

    for name in ("Ada", "Grace", "Mary"):
        response = client.get(run_url)
        assert response.status_code == HTTPStatus.OK
        assert "name" in response.context["form"].fields
        client.post(run_url, data={"name": name})

    done_response = client.get(run_url)
    assert done_response.status_code == HTTPStatus.OK
    assert done_response.content == b"completed Ada, Grace, Mary"


def test_dynamic_list_payload_wizard_condenses_items_into_list(client):
    import json

    start_url = reverse("dynamic-list-payload-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("dynamic-list-payload-wizard-run", kwargs={"run_id": run_id})

    client.post(run_url, data={"count": "3"})
    client.post(run_url, data={"name": "Ada"})
    client.post(run_url, data={"name": "Grace"})
    client.post(run_url, data={"name": "Mary"})

    response = client.get(run_url)

    assert response.status_code == HTTPStatus.OK
    assert json.loads(response.content) == {
        "count": 3,
        "items": [
            {"name": "Ada"},
            {"name": "Grace"},
            {"name": "Mary"},
        ],
    }


def test_dynamic_wizard_regenerates_tree_from_current_stored_state(client):
    start_url = reverse("dynamic-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("dynamic-wizard-run", kwargs={"run_id": run_id})

    session = client.session
    session["gandalf_runs"][run_id] = {
        "state": [
            {"step": {"count": "2"}},
            {"step": {"name": "Ada"}},
            {"step": {"name": "Grace"}},
        ],
    }
    session.save()

    done_response = client.get(run_url)
    assert done_response.status_code == HTTPStatus.OK
    assert done_response.content == b"completed Ada, Grace"


def test_empty_wizard_run_returns_done_response_immediately(
    client,
    empty_wizard_url,
    empty_wizard_run_url,
):
    response = client.get(empty_wizard_url)

    run_id, _ = get_only_run_info_from_session(client.session)
    assertRedirects(
        response, empty_wizard_run_url(run_id), fetch_redirect_response=False
    )

    response = client.get(empty_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


@pytest.fixture
def merged_payload_wizard_url():
    return reverse("merged-payload-wizard")


@pytest.fixture
def merged_payload_wizard_run_url():
    def build_url(run_id):
        return reverse("merged-payload-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_linear_wizard_done_can_merge_cleaned_data_across_path(
    client,
    merged_payload_wizard_url,
    merged_payload_wizard_run_url,
):
    client.get(merged_payload_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(merged_payload_wizard_run_url(run_id), data={"name": "Ada"})
    response = client.post(
        merged_payload_wizard_run_url(run_id),
        data={"email": "ada@example.com"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed name=Ada email=ada@example.com"


@pytest.fixture
def path_aware_linear_wizard_url():
    return reverse("path-aware-linear-wizard")


@pytest.fixture
def path_aware_linear_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "path-aware-linear-wizard-run",
            kwargs={"run_id": run_id},
        )

    return build_url


def test_step_view_can_pre_fill_initial_from_request_wizard_path(
    client,
    path_aware_linear_wizard_url,
    path_aware_linear_wizard_run_url,
):
    client.get(path_aware_linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        path_aware_linear_wizard_run_url(run_id),
        data={"name": "Ada"},
    )
    response = client.get(path_aware_linear_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="ada@example.com"')


@pytest.fixture
def path_aware_form_view_first_step_wizard_url():
    return reverse("path-aware-form-view-first-step-wizard")


@pytest.fixture
def path_aware_form_view_first_step_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "path-aware-form-view-first-step-wizard-run",
            kwargs={"run_id": run_id},
        )

    return build_url


def test_step_view_can_pre_fill_initial_from_path_with_form_view_upstream(
    client,
    path_aware_form_view_first_step_wizard_url,
    path_aware_form_view_first_step_wizard_run_url,
):
    client.get(path_aware_form_view_first_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        path_aware_form_view_first_step_wizard_run_url(run_id),
        data={"name": "Ada"},
    )
    response = client.get(path_aware_form_view_first_step_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="ada@example.com"')


@pytest.fixture
def branching_merged_payload_wizard_url():
    return reverse("branching-merged-payload-wizard")


@pytest.fixture
def branching_merged_payload_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "branching-merged-payload-wizard-run",
            kwargs={"run_id": run_id},
        )

    return build_url


def test_branching_wizard_done_merges_cleaned_data_across_multi_step_arm_path(
    client,
    branching_merged_payload_wizard_url,
    branching_merged_payload_wizard_run_url,
):
    client.get(branching_merged_payload_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        branching_merged_payload_wizard_run_url(run_id),
        data={"account_type": "business"},
    )
    client.post(
        branching_merged_payload_wizard_run_url(run_id),
        data={"business_name": "Acme"},
    )
    client.post(
        branching_merged_payload_wizard_run_url(run_id),
        data={"email": "acme@example.com"},
    )
    response = client.post(
        branching_merged_payload_wizard_run_url(run_id),
        data={"confirmed": "on"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"account_type=business "
        b"business_name=Acme "
        b"email=acme@example.com "
        b"confirmed=True"
    )


@pytest.fixture
def empty_branch_arm_merged_payload_wizard_url():
    return reverse("empty-branch-arm-merged-payload-wizard")


@pytest.fixture
def empty_branch_arm_merged_payload_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "empty-branch-arm-merged-payload-wizard-run",
            kwargs={"run_id": run_id},
        )

    return build_url


def test_branching_wizard_with_unmatched_no_default_arm_drops_branch_from_path(
    client,
    empty_branch_arm_merged_payload_wizard_url,
    empty_branch_arm_merged_payload_wizard_run_url,
):
    client.get(empty_branch_arm_merged_payload_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        empty_branch_arm_merged_payload_wizard_run_url(run_id),
        data={"name": "Ada"},
    )
    response = client.post(
        empty_branch_arm_merged_payload_wizard_run_url(run_id),
        data={"account_type": "personal"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"name=Ada account_type=personal"


@pytest.fixture
def runtime_tree_branching_merge_wizard_url():
    return reverse("runtime-tree-branching-merge-wizard")


@pytest.fixture
def runtime_tree_branching_merge_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "runtime-tree-branching-merge-wizard-run",
            kwargs={"run_id": run_id},
        )

    return build_url


def test_branching_wizard_done_can_merge_cleaned_data_across_runtime_tree(
    client,
    runtime_tree_branching_merge_wizard_url,
    runtime_tree_branching_merge_wizard_run_url,
):
    client.get(runtime_tree_branching_merge_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        runtime_tree_branching_merge_wizard_run_url(run_id),
        data={"account_type": "business"},
    )
    client.post(
        runtime_tree_branching_merge_wizard_run_url(run_id),
        data={"business_name": "Acme"},
    )
    response = client.post(
        runtime_tree_branching_merge_wizard_run_url(run_id),
        data={"confirmed": "on"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"account_type=business business_name=Acme confirmed=True"
    )


@pytest.fixture
def section_editing_wizard_url():
    return reverse("section-editing-wizard")


@pytest.fixture
def section_editing_wizard_run_url():
    def build_url(run_id):
        return reverse("section-editing-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_section_editing_wizard_uses_custom_edit_resolver_for_get(
    client,
    section_editing_wizard_url,
    section_editing_wizard_run_url,
):
    from tests.testapp.forms import AccountTypeForm

    client.get(section_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        section_editing_wizard_run_url(run_id),
        data={"account_type": "personal"},
    )
    client.post(
        section_editing_wizard_run_url(run_id),
        data={"preferred_name": "Ada"},
    )

    response = client.get(
        section_editing_wizard_run_url(run_id) + "?section=account",
    )

    assert response.status_code == HTTPStatus.OK
    form = response.context["form"]
    assert isinstance(form, AccountTypeForm)
    assert form.initial == {"account_type": "personal"}


def test_section_editing_wizard_uses_custom_edit_resolver_for_post(
    client,
    section_editing_wizard_url,
    section_editing_wizard_run_url,
):
    client.get(section_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        section_editing_wizard_run_url(run_id),
        data={"account_type": "personal"},
    )
    client.post(
        section_editing_wizard_run_url(run_id),
        data={"preferred_name": "Ada"},
    )

    client.post(
        section_editing_wizard_run_url(run_id),
        data={"section": "account", "account_type": "business"},
    )

    _, run_data = get_only_run_info_from_session(client.session)
    assert run_data["state"][0]["step"] == {"account_type": "business"}
    assert "section" not in run_data["state"][0]["step"]


@pytest.fixture
def file_uploading_wizard_url():
    return reverse("file-uploading-wizard")


@pytest.fixture
def file_uploading_wizard_run_url():
    def build_url(run_id):
        return reverse("file-uploading-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def isolated_media_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            yield tmpdir


def test_file_uploading_wizard_persists_upload_and_advances(
    client,
    file_uploading_wizard_url,
    file_uploading_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_uploading_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        file_uploading_wizard_run_url(run_id),
        data={"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
    )

    assert response.status_code == HTTPStatus.OK
    assertContains(response, '<input type="text" name="name"')
    _, run_data = get_only_run_info_from_session(client.session)
    [photo_entry] = run_data["state"]
    assert photo_entry["files"]["photo"]["tmp_name"] == (f"gandalf/{run_id}/avatar.jpg")
    assert photo_entry["files"]["photo"]["name"] == "avatar.jpg"
    assert os.path.exists(
        os.path.join(isolated_media_root, "gandalf", run_id, "avatar.jpg")
    )


def test_file_uploading_wizard_done_cleans_up_files(
    client,
    file_uploading_wizard_url,
    file_uploading_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_uploading_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        file_uploading_wizard_run_url(run_id),
        data={"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
    )

    response = client.post(
        file_uploading_wizard_run_url(run_id),
        data={"name": "Ada"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed avatar.jpg"
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    assert not os.path.exists(run_dir) or os.listdir(run_dir) == []


def test_file_uploading_wizard_replay_after_upload_re_renders_next_step(
    client,
    file_uploading_wizard_url,
    file_uploading_wizard_run_url,
    isolated_media_root,
):
    client.get(file_uploading_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        file_uploading_wizard_run_url(run_id),
        data={"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
    )

    response = client.get(file_uploading_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assertContains(response, '<input type="text" name="name"')
