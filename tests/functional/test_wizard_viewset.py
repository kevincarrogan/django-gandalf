import tempfile
from http import HTTPStatus

from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
import pytest
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertRedirects,
    assertTemplateUsed,
)


from tests.testapp.forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    EmailLookupForm,
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


def _step(run_url, step):
    return f"{run_url}{step}/"


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

    response = client.get(single_step_wizard_run_url(run_id), follow=True)

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

    response = client.post(
        _step(single_step_wizard_run_url(run_id), "first"),
        data={"name": ""},
        follow=True,
    )

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

    response = client.post(
        _step(single_step_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


def test_single_step_wizard_revisit_after_completion_does_not_rerun_done(
    client,
    single_step_wizard_url,
    single_step_wizard_run_url,
):
    client.get(single_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    completion = client.post(
        _step(single_step_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    assert completion.content == f"completed {run_id}".encode()

    response = client.get(single_step_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == single_step_wizard_url
    assert response.content != f"completed {run_id}".encode()


def test_single_step_wizard_done_can_read_submitted_form_data(
    client,
    single_step_wizard_done_data_url,
    single_step_wizard_done_data_run_url,
):
    client.get(single_step_wizard_done_data_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(single_step_wizard_done_data_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
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
        _step(single_step_wizard_done_run_data_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
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

    response = client.get(linear_wizard_run_url(run_id), follow=True)

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

    response = client.post(
        _step(linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )

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

    client.post(
        _step(linear_wizard_run_url(run_id), "first"),
        data={"name": ""},
        follow=True,
    )
    response = client.post(
        _step(linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
    ]


def test_wizard_preserves_valid_previous_submission_when_posting_next_step(
    client, routed_wizard_urls, routed_wizard_run
):
    # Uses a three-step wizard so the run is still live after the second
    # POST: a completed run is tombstoned, so its state is deliberately no
    # longer inspectable.
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    response = client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert client.session["gandalf_runs"][routed_wizard_run]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_linear_wizard_done_can_read_submitted_form_data_from_each_step(
    client,
    done_linear_wizard_url,
    done_linear_wizard_run_url,
):
    client.get(done_linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(done_linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.post(
        _step(done_linear_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"


def test_linear_wizard_bare_url_post_after_done_neither_stores_nor_reruns_done(
    client,
    done_linear_wizard_url,
    done_linear_wizard_run_url,
):
    client.get(done_linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(done_linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    completion = client.post(
        _step(done_linear_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
    )
    assert completion.content == b"completed Ada at ada@example.com"

    response = client.post(
        done_linear_wizard_run_url(run_id),
        data={"email": "grace@example.com"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == done_linear_wizard_url
    assert client.session["gandalf_runs"][run_id] == {"completed": True}


def test_linear_wizard_get_after_valid_first_step_renders_next_declared_form(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.get(linear_wizard_run_url(run_id), follow=True)

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
        _step(branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
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
        _step(branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "personal"},
        follow=True,
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
        _step(branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )

    response = client.post(
        _step(branching_wizard_run_url(run_id), "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], ReviewForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_done_branching_wizard_complete_flow_uses_runtime_tree(
    client,
    done_branching_wizard_url,
    done_branching_wizard_run_url,
):
    client.get(done_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(done_branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(done_branching_wizard_run_url(run_id), "business"),
        data={"business_name": "Acme"},
        follow=True,
    )
    client.post(
        _step(done_branching_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
        follow=True,
    )
    response = client.post(
        _step(done_branching_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
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


def test_editing_branching_wizard_get_completed_step_renders_form_with_initial(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(editing_branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(editing_branching_wizard_run_url(run_id), "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )

    response = client.get(
        _step(editing_branching_wizard_run_url(run_id), "account_type"),
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
        _step(editing_branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(editing_branching_wizard_run_url(run_id), "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )

    response = client.post(
        _step(editing_branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_editing_branching_wizard_post_edit_changing_arm_keeps_dormant_arm(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(editing_branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(editing_branching_wizard_run_url(run_id), "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )

    response = client.post(
        _step(editing_branching_wizard_run_url(run_id), "account_type"),
        data={"account_type": "personal"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], PersonalDetailsForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_editing_branching_wizard_full_reentrant_loop(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    """The re-entrant summary pattern end to end: trivial edits bounce
    straight back to the summary, a diverting edit asks only the new arm's
    steps, and flipping the branch answer back restores the dormant arm."""
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = editing_branching_wizard_run_url(run_id)
    client.post(
        _step(run_url, "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(run_url, "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )

    response = client.get(run_url, follow=True)
    assert isinstance(response.context["form"], ReviewForm)

    # Trivial edit from the summary: change lands, user is back on the
    # summary immediately.
    response = client.post(
        _step(run_url, "business_name"),
        data={"business_name": "Globex"},
        follow=True,
    )
    assert isinstance(response.context["form"], ReviewForm)

    # Diverting edit: the flow re-routes to the personal arm and asks only
    # its unanswered step.
    response = client.post(
        _step(run_url, "account_type"),
        data={"account_type": "personal"},
        follow=True,
    )
    assert isinstance(response.context["form"], PersonalDetailsForm)

    # Answering the diverted step (a plain submission, no edit marker)
    # returns straight to the summary.
    response = client.post(
        _step(run_url, "preferred_name"),
        data={"preferred_name": "Ada"},
        follow=True,
    )
    assert isinstance(response.context["form"], ReviewForm)

    # Flipping the branch answer back restores the dormant business arm
    # without re-asking it, landing on the summary again.
    response = client.post(
        _step(run_url, "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    assert isinstance(response.context["form"], ReviewForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"account_type": "business"}},
        {
            "branch": {
                "0": [{"step": {"business_name": "Globex"}}],
                "default": [{"step": {"preferred_name": "Ada"}}],
            }
        },
    ]


def test_editing_branching_wizard_resumes_legacy_bare_list_branch_state(
    client,
    editing_branching_wizard_url,
    editing_branching_wizard_run_url,
):
    client.get(editing_branching_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    session = client.session
    session["gandalf_runs"][run_id]["state"] = [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]
    session.save()

    response = client.get(editing_branching_wizard_run_url(run_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)


@pytest.fixture
def routed_wizard_urls():
    def build(run_id, step=None):
        if step is None:
            return reverse("routed-wizard-run", kwargs={"run_id": run_id})
        return reverse(
            "routed-wizard-step",
            kwargs={"run_id": run_id, "gandalf_step": step},
        )

    return build


@pytest.fixture
def routed_wizard_run(client, routed_wizard_urls):
    client.get(reverse("routed-wizard"))
    run_id, _ = get_only_run_info_from_session(client.session)
    return run_id


def test_routed_wizard_bare_run_url_redirects_to_cursor_step_url(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.get(routed_wizard_urls(routed_wizard_run))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(routed_wizard_run, "account_type")


def test_routed_wizard_get_cursor_step_url_renders_form(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.get(routed_wizard_urls(routed_wizard_run, "account_type"))

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], AccountTypeForm)


def test_routed_wizard_valid_submit_redirects_to_next_step_url(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(
        routed_wizard_run, "business_name"
    )


def test_routed_wizard_invalid_submit_redirects_and_rerenders_with_errors(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "not-a-choice"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(routed_wizard_run, "account_type")
    followed = client.get(response["Location"])
    assert followed.status_code == HTTPStatus.OK
    assert followed.context["form"].errors == {
        "account_type": [
            "Select a valid choice. not-a-choice is not one of the available choices."
        ],
    }


def test_routed_wizard_get_completed_step_url_renders_prefilled_form(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )

    response = client.get(routed_wizard_urls(routed_wizard_run, "account_type"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].initial == {"account_type": "business"}


def test_routed_wizard_get_unknown_step_url_redirects_to_cursor(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.get(routed_wizard_urls(routed_wizard_run, "missing"))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(routed_wizard_run, "account_type")


def test_routed_wizard_get_future_step_url_redirects_to_cursor(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.get(routed_wizard_urls(routed_wizard_run, "review"))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(routed_wizard_run, "account_type")


def test_routed_wizard_trivial_edit_redirects_back_to_summary(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )

    response = client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Globex"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(routed_wizard_run, "review")
    state = client.session["gandalf_runs"][routed_wizard_run]["state"]
    assert state[1] == {"branch": {"0": [{"step": {"business_name": "Globex"}}]}}


def test_routed_wizard_diverting_edit_redirects_to_new_arm_step(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )

    response = client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "personal"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(
        routed_wizard_run, "preferred_name"
    )


def test_routed_wizard_invalid_edit_renders_errors_without_redirect(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )
    response = client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": ""},
        follow=True,
    )

    # Placement is placement: a rejected submission is kept and parked on,
    # exactly as for a step being answered the first time. The errors below
    # come from a *fresh walk* after the redirect, which is only possible if
    # the rejected data was persisted and replayed.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {
        "business_name": ["This field is required."],
    }


def test_routed_wizard_dormant_step_url_redirects_instead_of_500(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "personal"},
    )

    response = client.get(routed_wizard_urls(routed_wizard_run, "business_name"))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(
        routed_wizard_run, "preferred_name"
    )


def test_routed_wizard_stale_tab_post_redirects_without_storing(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "personal"},
    )
    state_before = client.session["gandalf_runs"][routed_wizard_run]["state"]

    response = client.post(
        routed_wizard_urls(routed_wizard_run, "review"),
        data={"confirmed": "on"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(
        routed_wizard_run, "preferred_name"
    )
    assert client.session["gandalf_runs"][routed_wizard_run]["state"] == state_before


def test_routed_wizard_renders_back_link_to_previous_step(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )

    response = client.get(routed_wizard_urls(routed_wizard_run, "business_name"))

    assert response.status_code == HTTPStatus.OK
    back_url = routed_wizard_urls(routed_wizard_run, "account_type")
    assertContains(response, f'<a href="{back_url}">Back</a>', html=True)


def test_routed_wizard_first_step_renders_without_back_link(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.get(routed_wizard_urls(routed_wizard_run, "account_type"))

    assert response.status_code == HTTPStatus.OK
    assertNotContains(response, ">Back</a>", html=False)


def test_routed_wizard_step_behind_an_unanswered_step_is_unreachable(
    client, routed_wizard_urls, routed_wizard_run
):
    """A claim is only honoured by arriving at it, and the walk stops at the
    first unanswered step. So a later step that still holds an answer is not
    renderable while something before it is missing — its form would
    otherwise run against a prefix the walk has not proven."""
    session = client.session
    session["gandalf_runs"][routed_wizard_run]["state"] = [
        {"step": None},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        {"step": {"confirmed": "on"}},
    ]
    session.save()

    response = client.get(routed_wizard_urls(routed_wizard_run, "review"))

    assertRedirects(response, routed_wizard_urls(routed_wizard_run, "account_type"))


def test_routed_wizard_final_submit_completes_run(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )

    response = client.post(
        routed_wizard_urls(routed_wizard_run, "review"),
        data={"confirmed": "on"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {routed_wizard_run}".encode()


def test_routed_wizard_unknown_step_url_on_completed_run_redirects_to_start(
    client, routed_wizard_urls, routed_wizard_run
):
    client.post(
        routed_wizard_urls(routed_wizard_run, "account_type"),
        data={"account_type": "business"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "business_name"),
        data={"business_name": "Acme"},
    )
    client.post(
        routed_wizard_urls(routed_wizard_run, "review"),
        data={"confirmed": "on"},
    )

    response = client.get(routed_wizard_urls(routed_wizard_run, "missing"))

    # The run is finished, so there is no cursor to send the user back to —
    # every URL under a completed run resolves to `run_unavailable()`.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse("routed-wizard")


def test_unroutable_wizard_raises_improperly_configured(client):
    with pytest.raises(ImproperlyConfigured, match="FirstStepForm"):
        client.get(reverse("unroutable-wizard"))


def test_org_scoped_wizard_edit_render_receives_url_kwargs(
    client,
):
    start_url = reverse("org-scoped-wizard", kwargs={"org": "acme"})
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    step_url = reverse(
        "org-scoped-wizard-step",
        kwargs={"org": "acme", "run_id": run_id, "gandalf_step": "first"},
    )
    client.post(step_url, data={"name": "Ada"})

    response = client.get(step_url)

    assert response.status_code == HTTPStatus.OK
    assert response.context["org"] == "acme"
    assert response.context["form"].initial == {"name": "Ada"}


def test_org_scoped_wizard_invalid_edit_error_render_receives_url_kwargs(
    client,
):
    start_url = reverse("org-scoped-wizard", kwargs={"org": "acme"})
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    step_url = reverse(
        "org-scoped-wizard-step",
        kwargs={"org": "acme", "run_id": run_id, "gandalf_step": "first"},
    )
    client.post(step_url, data={"name": "Ada"})

    response = client.post(step_url, data={"name": ""}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.context["org"] == "acme"
    assert response.context["form"].errors == {"name": ["This field is required."]}


def test_org_scoped_wizard_start_redirects_within_same_mount(client):
    start_url = reverse("org-scoped-wizard", kwargs={"org": "acme"})

    response = client.get(start_url)

    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("org-scoped-wizard-run", kwargs={"org": "acme", "run_id": run_id})
    assertRedirects(response, run_url, target_status_code=HTTPStatus.FOUND)


def test_org_scoped_wizard_submission_redirects_within_same_mount(client):
    start_url = reverse("org-scoped-wizard", kwargs={"org": "acme"})
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    first_step_url = reverse(
        "org-scoped-wizard-step",
        kwargs={"org": "acme", "run_id": run_id, "gandalf_step": "first"},
    )

    response = client.post(first_step_url, data={"name": "Ada"})

    review_step_url = reverse(
        "org-scoped-wizard-step",
        kwargs={"org": "acme", "run_id": run_id, "gandalf_step": "review"},
    )
    assertRedirects(response, review_step_url)


def test_wizard_viewset_urls_requires_url_name():
    from django.core.exceptions import ImproperlyConfigured

    from gandalf.viewsets import WizardViewSet

    class NamelessViewSet(WizardViewSet):
        pass

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        NamelessViewSet.urls()


def test_misconfigured_wizard_start_raises_improperly_configured(client):
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match="get_wizard_url"):
        client.get(reverse("misconfigured-wizard"))


def test_wizardless_wizard_raises_improperly_configured(client):
    with pytest.raises(
        ImproperlyConfigured,
        match="WizardlessWizardViewSet has no wizard to run",
    ):
        client.get(reverse("wizardless-wizard"))


def test_misconfigured_wizard_run_url_raises_improperly_configured(client):
    from django.core.exceptions import ImproperlyConfigured

    session = client.session
    session["gandalf_runs"] = {"11111111-1111-1111-1111-111111111111": {}}
    session.save()

    with pytest.raises(ImproperlyConfigured, match="get_step_url"):
        client.get(
            reverse(
                "misconfigured-wizard-run",
                kwargs={"run_id": "11111111-1111-1111-1111-111111111111"},
            )
        )


def test_programmatic_lookup_wizard_probes_step_not_found_mid_run(client):
    client.get(reverse("programmatic-lookup-wizard"))
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("programmatic-lookup-wizard-run", kwargs={"run_id": run_id})
    client.post(_step(run_url, "first"), data={"name": "Ada"})

    response = client.get(_step(run_url, "second"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["lookup_probe"] == "step-not-found"
    assert response.context["name_lookup_probe"] == "first"
    assert response.context["ambiguous_lookup_probe"] == "type-error"


def test_programmatic_lookup_wizard_edit_of_missing_step_deletes_new_uploads(
    client, isolated_media_root
):
    client.get(reverse("programmatic-lookup-wizard"))
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("programmatic-lookup-wizard-run", kwargs={"run_id": run_id})
    client.post(_step(run_url, "first"), data={"name": "Ada"})

    response = client.post(
        _step(run_url, "second"),
        data={"email": "ada@example.com"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"completed edit-cleanup=True nav-probe=True resolve-status=200 "
        b"declaration-claim=True ambiguous=True"
    )


@pytest.fixture
def cross_branch_run(client):
    client.get(reverse("cross-branch-wizard"))
    run_id, _ = get_only_run_info_from_session(client.session)
    session = client.session
    session["gandalf_runs"][run_id]["state"] = [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        {"branch": {"0": [{"step": {"email": "ada@example.com"}}]}},
        {"step": {"confirmed": "on"}},
    ]
    session.save()
    run_url = reverse("cross-branch-wizard-run", kwargs={"run_id": run_id})
    return run_id, run_url


def test_cross_branch_wizard_path_read_is_safe_mid_divert(client, cross_branch_run):
    _, run_url = cross_branch_run

    response = client.get(_step(run_url, "preferred_name"))

    assert response.status_code == HTTPStatus.OK
    assert response.context["path_names"] == ["account_type", "review"]


def test_cross_branch_wizard_edit_is_safe_mid_divert(client, cross_branch_run):
    run_id, run_url = cross_branch_run

    response = client.post(
        _step(run_url, "account_type"),
        data={"account_type": "personal"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == _step(run_url, "preferred_name")
    state = client.session["gandalf_runs"][run_id]["state"]
    assert state[0] == {"step": {"account_type": "personal"}}
    assert state[1] == {"branch": {"0": [{"step": {"business_name": "Acme"}}]}}
    assert state[3] == {"step": {"confirmed": "on"}}


def test_branch_entry_wizard_renders_default_arm_first_step(client):
    start_url = reverse("branch-entry-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("branch-entry-wizard-run", kwargs={"run_id": run_id})

    response = client.get(run_url, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_duplicate_step_names_are_rejected_when_the_wizard_resolves(client):
    """Two steps sharing a name is a declaration error, so it is caught when
    the wizard resolves rather than per request — a walk stops at the cursor
    and so cannot see a duplicate lying beyond it."""
    with pytest.raises(ImproperlyConfigured, match="must be unique"):
        client.get(reverse("duplicate-context-wizard"))


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
            _step(single_step_wizard_without_done_run_url(run_id), "first"),
            data={"name": "Ada"},
            follow=True,
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

    first_client.post(
        _step(linear_wizard_run_url(first_run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = second_client.get(linear_wizard_run_url(second_run_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_submissions_persist_for_same_client(
    client,
    linear_wizard_url,
    linear_wizard_run_url,
):
    client.get(linear_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.get(linear_wizard_run_url(run_id), follow=True)

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
    client.post(
        _step(linear_wizard_run_url(linear_run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )

    existing_run_ids = set(client.session["gandalf_runs"])
    client.get(other_linear_wizard_url)
    other_run_id = get_new_run_id_from_session(client.session, existing_run_ids)
    response = client.get(other_linear_wizard_run_url(other_run_id), follow=True)

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

    client.post(
        _step(linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.get(recreated_linear_wizard_run_url(run_id), follow=True)

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

    response = client.get(run_url, follow=True)
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)

    response = client.post(
        _step(run_url, "first"),
        data={"name": "Ada"},
        follow=True,
    )
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

    response = client.get(run_url, follow=True)
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)

    response = client.post(
        _step(run_url, "first"),
        data={"name": "Ada"},
        follow=True,
    )
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

    first_response = client.get(run_url, follow=True)
    assert first_response.status_code == HTTPStatus.OK
    assert "count" in first_response.context["form"].fields

    client.post(
        _step(run_url, "count"),
        data={"count": "3"},
        follow=True,
    )

    for index, name in enumerate(("Ada", "Grace", "Mary")):
        response = client.get(run_url, follow=True)
        assert response.status_code == HTTPStatus.OK
        assert "name" in response.context["form"].fields
        done_response = client.post(
            _step(run_url, f"item-{index}"),
            data={"name": name},
            follow=True,
        )

    # The final item's POST completes the run and fires done() there; the
    # run is tombstoned afterwards, so nothing re-fires it.
    assert done_response.status_code == HTTPStatus.OK
    assert done_response.content == b"completed Ada, Grace, Mary"


def test_dynamic_list_payload_wizard_condenses_items_into_list(client):
    import json

    start_url = reverse("dynamic-list-payload-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("dynamic-list-payload-wizard-run", kwargs={"run_id": run_id})

    client.post(
        _step(run_url, "count"),
        data={"count": "3"},
        follow=True,
    )
    client.post(
        _step(run_url, "item-0"),
        data={"name": "Ada"},
        follow=True,
    )
    client.post(
        _step(run_url, "item-1"),
        data={"name": "Grace"},
        follow=True,
    )
    response = client.post(
        _step(run_url, "item-2"),
        data={"name": "Mary"},
        follow=True,
    )

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

    done_response = client.get(run_url, follow=True)
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

    response = client.get(empty_wizard_run_url(run_id), follow=True)

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

    client.post(
        _step(merged_payload_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.post(
        _step(merged_payload_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
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
        _step(path_aware_linear_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.get(path_aware_linear_wizard_run_url(run_id), follow=True)

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
        _step(path_aware_form_view_first_step_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.get(
        path_aware_form_view_first_step_wizard_run_url(run_id), follow=True
    )

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
        _step(branching_merged_payload_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(branching_merged_payload_wizard_run_url(run_id), "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )
    client.post(
        _step(branching_merged_payload_wizard_run_url(run_id), "second"),
        data={"email": "acme@example.com"},
        follow=True,
    )
    response = client.post(
        _step(branching_merged_payload_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
        follow=True,
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
        _step(empty_branch_arm_merged_payload_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.post(
        _step(
            empty_branch_arm_merged_payload_wizard_run_url(run_id),
            "skip_branch_account",
        ),
        data={"account_type": "personal"},
        follow=True,
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
        _step(runtime_tree_branching_merge_wizard_run_url(run_id), "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        _step(runtime_tree_branching_merge_wizard_run_url(run_id), "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )
    response = client.post(
        _step(runtime_tree_branching_merge_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
        follow=True,
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


def test_section_editing_wizard_uses_custom_step_router_for_get(
    client,
    section_editing_wizard_url,
    section_editing_wizard_run_url,
):
    client.get(section_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(section_editing_wizard_run_url(run_id), "account"),
        data={"account_type": "personal"},
        follow=True,
    )
    client.post(
        _step(section_editing_wizard_run_url(run_id), "details"),
        data={"preferred_name": "Ada"},
        follow=True,
    )

    response = client.get(
        _step(section_editing_wizard_run_url(run_id), "account"),
    )

    assert response.status_code == HTTPStatus.OK
    form = response.context["form"]
    assert isinstance(form, AccountTypeForm)
    assert form.initial == {"account_type": "personal"}


def test_section_editing_wizard_uses_custom_step_router_for_post(
    client,
    section_editing_wizard_url,
    section_editing_wizard_run_url,
):
    client.get(section_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(section_editing_wizard_run_url(run_id), "account"),
        data={"account_type": "personal"},
        follow=True,
    )
    client.post(
        _step(section_editing_wizard_run_url(run_id), "details"),
        data={"preferred_name": "Ada"},
        follow=True,
    )

    response = client.post(
        _step(section_editing_wizard_run_url(run_id), "account"),
        data={"account_type": "business"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)
    _, run_data = get_only_run_info_from_session(client.session)
    assert run_data["state"][0]["step"] == {"account_type": "business"}


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
        _step(file_uploading_wizard_run_url(run_id), "photo"),
        data={"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
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
        _step(file_uploading_wizard_run_url(run_id), "photo"),
        data={"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
    )

    response = client.post(
        _step(file_uploading_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
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
        _step(file_uploading_wizard_run_url(run_id), "photo"),
        data={"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
    )

    response = client.get(file_uploading_wizard_run_url(run_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, '<input type="text" name="name"')


@pytest.fixture
def named_helper_wizard_url():
    return reverse("named-helper-wizard")


@pytest.fixture
def named_helper_wizard_run_url():
    def build_url(run_id):
        return reverse("named-helper-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_named_helper_wizard_completes_with_context_lookups(
    client,
    named_helper_wizard_url,
    named_helper_wizard_run_url,
):
    client.get(named_helper_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(named_helper_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.post(
        _step(named_helper_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed first=Ada second=ada@example.com"


@pytest.fixture
def file_editing_wizard_url():
    return reverse("file-editing-wizard")


@pytest.fixture
def file_editing_wizard_run_url():
    def build_url(run_id):
        return reverse("file-editing-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_file_editing_wizard_edit_replaces_photo_and_deletes_old(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "First",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    response = client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "First",
            "photo": SimpleUploadedFile("second.jpg", b"second-bytes"),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    files = sorted(os.listdir(run_dir))
    assert files == ["second.jpg"]


def test_file_editing_wizard_edit_adds_photo_to_step_without_one(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={"label": "No photo yet"},
        follow=True,
    )

    response = client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "Now with photo",
            "photo": SimpleUploadedFile("later.jpg", b"later-bytes"),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    assert sorted(os.listdir(run_dir)) == ["later.jpg"]


def test_file_editing_wizard_edit_changing_label_keeps_photo(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    response = client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={"label": "Renamed"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    state = client.session["gandalf_runs"][run_id]["state"]
    assert state[0]["step"]["label"] == "Renamed"
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    assert sorted(os.listdir(run_dir)) == ["first.jpg"]


def test_file_editing_wizard_edit_get_renders_existing_photo(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    response = client.get(
        _step(file_editing_wizard_run_url(run_id), "photo"),
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"].initial.get("photo"), object)
    assert "first.jpg" in response.context["form"].initial["photo"].name


def test_file_editing_wizard_edit_with_invalid_submission_keeps_state_and_files(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )
    response = client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={
            "label": "",
            "photo": SimpleUploadedFile("rejected.jpg", b"rejected-bytes"),
        },
        follow=True,
    )

    # Placement is placement: a rejected submission is kept and parked on,
    # exactly as for a step being answered the first time. The errors below
    # come from a *fresh walk* after the redirect, which is only possible if
    # the rejected data was persisted and replayed.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {"label": ["This field is required."]}
    # The rejected submission is what is stored now, so its upload is the live
    # one and the superseded file is collected rather than left orphaned.
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    assert sorted(os.listdir(run_dir)) == ["rejected.jpg"]


def test_file_editing_wizard_rejected_upload_survives_the_correction(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    """Issue #44: a rejected edit used to delete the upload it arrived with,
    and browsers cannot repopulate a file input — so correcting the text field
    silently kept the *old* photo while the user believed the new one had been
    saved. A rejected submission is now kept whole, upload included, so the
    correction keeps the photo that came with it."""
    import os

    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    photo_url = _step(file_editing_wizard_run_url(run_id), "photo")
    client.post(
        photo_url,
        data={
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    # Pick a replacement photo, but leave a required field blank.
    client.post(
        photo_url,
        data={
            "label": "",
            "photo": SimpleUploadedFile("second.jpg", b"second-bytes"),
        },
        follow=True,
    )
    # Correct the field. No file is re-sent, exactly as a browser would behave.
    client.post(photo_url, data={"label": "Fixed"}, follow=True)

    state = client.session["gandalf_runs"][run_id]["state"]
    assert state[0]["step"]["label"] == "Fixed"
    assert state[0]["files"]["photo"]["name"] == "second.jpg"
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    assert sorted(os.listdir(run_dir)) == ["second.jpg"]


def test_file_editing_wizard_unknown_step_url_redirects(
    client,
    file_editing_wizard_url,
    file_editing_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(file_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(file_editing_wizard_run_url(run_id), "photo"),
        data={"label": "Only label"},
        follow=True,
    )
    state_before = client.session["gandalf_runs"][run_id]["state"]

    response = client.post(
        _step(file_editing_wizard_run_url(run_id), "nonexistent"),
        data={
            "label": "ignored",
            "photo": SimpleUploadedFile("orphan.jpg", b"orphan-bytes"),
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == _step(file_editing_wizard_run_url(run_id), "review")
    assert client.session["gandalf_runs"][run_id]["state"] == state_before
    run_dir = os.path.join(isolated_media_root, "gandalf", run_id)
    assert not os.path.exists(run_dir) or os.listdir(run_dir) == []


@pytest.fixture
def empty_branch_arm_context_finder_wizard_url():
    return reverse("empty-branch-arm-context-finder-wizard")


@pytest.fixture
def empty_branch_arm_context_finder_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "empty-branch-arm-context-finder-wizard-run",
            kwargs={"run_id": run_id},
        )

    return build_url


def test_empty_branch_arm_context_finder_walks_both_trees(
    client,
    empty_branch_arm_context_finder_wizard_url,
    empty_branch_arm_context_finder_wizard_run_url,
):
    client.get(empty_branch_arm_context_finder_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    client.post(
        _step(empty_branch_arm_context_finder_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    response = client.post(
        _step(empty_branch_arm_context_finder_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    # Declared tree finder visits the unmatched-arm step (2) plus the two outer
    # steps (first + review) = 3 matches. Runtime tree finder visits only the
    # outer steps along the active path = 2 matches.
    assert response.content == b"completed declared=3 runtime=2"


@pytest.fixture
def branch_edit_rejection_wizard_url():
    return reverse("branch-edit-rejection-wizard")


@pytest.fixture
def branch_edit_rejection_wizard_run_url():
    def build_url(run_id):
        return reverse("branch-edit-rejection-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_branch_edit_rejection_wizard_edit_post_branch_step_with_invalid_keeps_state(
    client,
    branch_edit_rejection_wizard_url,
    branch_edit_rejection_wizard_run_url,
):
    client.get(branch_edit_rejection_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
    )
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
        follow=True,
    )
    response = client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "review"),
        data={"confirmed": ""},
        follow=True,
    )

    # Placement is placement: a rejected submission is kept and parked on,
    # exactly as for a step being answered the first time. The errors below
    # come from a *fresh walk* after the redirect, which is only possible if
    # the rejected data was persisted and replayed.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {"confirmed": ["This field is required."]}


def test_branch_edit_rejection_wizard_unvisited_step_url_redirects_to_cursor(
    client,
    branch_edit_rejection_wizard_url,
    branch_edit_rejection_wizard_run_url,
):
    client.get(branch_edit_rejection_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    state_before = client.session["gandalf_runs"][run_id]["state"]

    response = client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == _step(
        branch_edit_rejection_wizard_run_url(run_id), "second"
    )
    assert client.session["gandalf_runs"][run_id]["state"] == state_before


def test_branch_edit_rejection_wizard_edit_in_branch_arm_with_invalid_keeps_state(
    client,
    branch_edit_rejection_wizard_url,
    branch_edit_rejection_wizard_run_url,
):
    client.get(branch_edit_rejection_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "second"),
        data={"email": "ada@example.com"},
        follow=True,
    )
    client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "review"),
        data={"confirmed": "on"},
        follow=True,
    )
    response = client.post(
        _step(branch_edit_rejection_wizard_run_url(run_id), "second"),
        data={"email": "not-an-email"},
        follow=True,
    )

    # Kept and parked on, like any other rejected submission. These errors
    # come from a fresh walk after the redirect, so they prove it was stored.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {
        "email": ["Enter a valid email address."]
    }


@pytest.fixture
def escape_park_wizard_url():
    return reverse("escape-park-wizard")


@pytest.fixture
def escape_park_wizard_run_url():
    def build_url(run_id):
        return reverse("escape-park-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def escape_advance_wizard_url():
    return reverse("escape-advance-wizard")


@pytest.fixture
def escape_advance_wizard_run_url():
    def build_url(run_id):
        return reverse("escape-advance-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def escape_advance_final_step_wizard_url():
    return reverse("escape-advance-final-step-wizard")


@pytest.fixture
def escape_advance_final_step_wizard_run_url():
    def build_url(run_id):
        return reverse(
            "escape-advance-final-step-wizard-run", kwargs={"run_id": run_id}
        )

    return build_url


@pytest.fixture
def escape_obliterate_wizard_url():
    return reverse("escape-obliterate-wizard")


@pytest.fixture
def escape_obliterate_wizard_run_url():
    def build_url(run_id):
        return reverse("escape-obliterate-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def bare_escape_wizard_url():
    return reverse("bare-escape-wizard")


@pytest.fixture
def bare_escape_wizard_run_url():
    def build_url(run_id):
        return reverse("bare-escape-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def escape_editing_wizard_url():
    return reverse("escape-editing-wizard")


@pytest.fixture
def escape_editing_wizard_run_url():
    def build_url(run_id):
        return reverse("escape-editing-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_parking_escape_redirects_away_without_storing_the_submission(
    client,
    escape_park_wizard_url,
    escape_park_wizard_run_url,
):
    client.get(escape_park_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_park_wizard_run_url(run_id), "email"),
        data={"email": "existing@example.com"},
    )

    assertRedirects(response, reverse("escape-landing"))
    # Nothing was ever written: the walk validates before it persists, so a
    # parking escape simply declines to store rather than storing and undoing.
    assert client.session["gandalf_runs"][run_id].get("state", []) == []


def test_parking_escape_leaves_the_run_on_the_escaping_step(
    client,
    escape_park_wizard_url,
    escape_park_wizard_run_url,
):
    client.get(escape_park_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_park_wizard_run_url(run_id), "email"),
        data={"email": "existing@example.com"},
    )

    response = client.get(escape_park_wizard_run_url(run_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], EmailLookupForm)
    assertContains(response, '<input type="email" name="email"')


def test_parked_run_still_accepts_a_non_escaping_submission(
    client,
    escape_park_wizard_url,
    escape_park_wizard_run_url,
):
    client.get(escape_park_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_park_wizard_run_url(run_id), "email"),
        data={"email": "existing@example.com"},
    )

    response = client.post(
        _step(escape_park_wizard_run_url(run_id), "email"),
        data={"email": "new@example.com"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"email": "new@example.com"}},
    ]


def test_non_escaping_submission_advances_normally(
    client,
    escape_park_wizard_url,
    escape_park_wizard_run_url,
):
    client.get(escape_park_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_park_wizard_run_url(run_id), "email"),
        data={"email": "new@example.com"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"email": "new@example.com"}},
    ]


def test_advancing_escape_redirects_away_and_stores_the_submission(
    client,
    escape_advance_wizard_url,
    escape_advance_wizard_run_url,
):
    client.get(escape_advance_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_advance_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    assertRedirects(response, reverse("escape-landing"))
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"email": "ada@example.com", "subscribe": "on"}},
    ]


def test_advancing_escape_resumes_the_run_at_the_next_step(
    client,
    escape_advance_wizard_url,
    escape_advance_wizard_run_url,
):
    client.get(escape_advance_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_advance_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    response = client.get(escape_advance_wizard_run_url(run_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_run_completes_after_an_advancing_escape(
    client,
    escape_advance_wizard_url,
    escape_advance_wizard_run_url,
):
    client.get(escape_advance_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_advance_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    response = client.post(
        _step(escape_advance_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed ada@example.com"


def test_advancing_escape_on_the_final_step_defers_the_done_response(
    client,
    escape_advance_final_step_wizard_url,
    escape_advance_final_step_wizard_run_url,
):
    client.get(escape_advance_final_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_advance_final_step_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    assertRedirects(response, reverse("escape-landing"))


def test_completed_run_returns_done_when_revisited_after_escaping(
    client,
    escape_advance_final_step_wizard_url,
    escape_advance_final_step_wizard_run_url,
):
    client.get(escape_advance_final_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_advance_final_step_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    response = client.get(escape_advance_final_step_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run_id}".encode()


def test_obliterating_escape_removes_the_run(
    client,
    escape_obliterate_wizard_url,
    escape_obliterate_wizard_run_url,
):
    client.get(escape_obliterate_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_obliterate_wizard_run_url(run_id), "cancel"),
        data={"reason": "changed my mind", "cancel": "on"},
    )

    assertRedirects(response, reverse("escape-landing"))
    assert run_id not in client.session["gandalf_runs"]


def test_form_view_step_without_an_escape_advances_normally(
    client,
    escape_obliterate_wizard_url,
    escape_obliterate_wizard_run_url,
):
    client.get(escape_obliterate_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_obliterate_wizard_run_url(run_id), "cancel"),
        data={"reason": "carrying on"},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_editing_a_completed_step_escapes_like_any_other_placement(
    client,
    escape_editing_wizard_url,
    escape_editing_wizard_run_url,
):
    client.get(escape_editing_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_editing_wizard_run_url(run_id), "email"),
        data={"email": "new@example.com"},
    )

    response = client.post(
        _step(escape_editing_wizard_run_url(run_id), "email"),
        data={"email": "existing@example.com"},
    )

    # A step that escapes escapes wherever it sits. Swallowing it behind the
    # cursor let an edit store an answer the form had explicitly rejected —
    # the opposite of what Park means — so the submit and edit paths now
    # honour it identically, and Park declines to store.
    assertRedirects(response, reverse("escape-landing"))
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"email": "new@example.com"}},
    ]


def test_bare_escape_is_rejected_as_misuse(
    client,
    bare_escape_wizard_url,
    bare_escape_wizard_run_url,
):
    client.get(bare_escape_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    with pytest.raises(ImproperlyConfigured):
        client.post(
            _step(bare_escape_wizard_run_url(run_id), "bare"),
            data={"name": "Ada"},
        )


@pytest.fixture
def mid_flow_escape_park_wizard_url():
    return reverse("mid-flow-escape-park-wizard")


@pytest.fixture
def mid_flow_escape_park_wizard_run_url():
    def build_url(run_id):
        return reverse("mid-flow-escape-park-wizard-run", kwargs={"run_id": run_id})

    return build_url


@pytest.fixture
def escape_park_file_wizard_url():
    return reverse("escape-park-file-wizard")


@pytest.fixture
def escape_park_file_wizard_run_url():
    def build_url(run_id):
        return reverse("escape-park-file-wizard-run", kwargs={"run_id": run_id})

    return build_url


def test_parking_escape_keeps_answers_from_earlier_steps(
    client,
    mid_flow_escape_park_wizard_url,
    mid_flow_escape_park_wizard_run_url,
):
    client.get(mid_flow_escape_park_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(mid_flow_escape_park_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
    )

    response = client.post(
        _step(mid_flow_escape_park_wizard_run_url(run_id), "email"),
        data={"email": "existing@example.com"},
    )

    assertRedirects(response, reverse("escape-landing"))
    assert client.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
    ]


def test_parked_run_returns_to_the_escaping_step_with_earlier_answers_intact(
    client,
    mid_flow_escape_park_wizard_url,
    mid_flow_escape_park_wizard_run_url,
):
    client.get(mid_flow_escape_park_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(mid_flow_escape_park_wizard_run_url(run_id), "first"),
        data={"name": "Ada"},
    )
    client.post(
        _step(mid_flow_escape_park_wizard_run_url(run_id), "email"),
        data={"email": "existing@example.com"},
    )

    response = client.get(mid_flow_escape_park_wizard_run_url(run_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], EmailLookupForm)


def test_parking_escape_discards_the_upload_it_escaped_with(
    client,
    escape_park_file_wizard_url,
    escape_park_file_wizard_run_url,
    isolated_media_root,
):
    import os

    client.get(escape_park_file_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)

    response = client.post(
        _step(escape_park_file_wizard_run_url(run_id), "photo"),
        data={
            "photo": SimpleUploadedFile("avatar.jpg", b"binary"),
            "abandon": "on",
        },
    )

    assertRedirects(response, reverse("escape-landing"))
    # Nothing was ever written: the walk validates before it persists, so a
    # parking escape simply declines to store rather than storing and undoing.
    assert client.session["gandalf_runs"][run_id].get("state", []) == []
    assert not os.path.exists(
        os.path.join(isolated_media_root, "gandalf", run_id, "avatar.jpg")
    )


# --- Completion lifecycle -------------------------------------------------
#
# `done()` fires exactly once per run. The run is tombstoned once it has,
# so every later request for it — and every request for a run that never
# existed — resolves to `run_unavailable()`.


@pytest.fixture
def run_unavailable_wizard_url():
    return reverse("run-unavailable-wizard")


@pytest.fixture
def run_unavailable_wizard_run_url():
    def build_url(run_id):
        return reverse("run-unavailable-wizard-run", kwargs={"run_id": run_id})

    return build_url


def _complete_single_step_run(client, start_url, run_url_for):
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    response = client.post(
        _step(run_url_for(run_id), "first"),
        data={"name": "Ada"},
    )
    return run_id, response


def test_completing_a_run_replaces_its_state_with_a_tombstone(
    client, single_step_wizard_url, single_step_wizard_run_url
):
    run_id, _ = _complete_single_step_run(
        client, single_step_wizard_url, single_step_wizard_run_url
    )

    assert client.session["gandalf_runs"][run_id] == {"completed": True}


def test_completed_run_step_url_no_longer_renders_an_edit_form(
    client, single_step_wizard_url, single_step_wizard_run_url
):
    run_id, _ = _complete_single_step_run(
        client, single_step_wizard_url, single_step_wizard_run_url
    )

    response = client.get(_step(single_step_wizard_run_url(run_id), "first"))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == single_step_wizard_url


def test_reposting_a_completed_runs_final_step_neither_edits_nor_reruns_done(
    client, single_step_wizard_url, single_step_wizard_run_url
):
    run_id, completion = _complete_single_step_run(
        client, single_step_wizard_url, single_step_wizard_run_url
    )
    assert completion.content == f"completed {run_id}".encode()

    response = client.post(
        _step(single_step_wizard_run_url(run_id), "first"),
        data={"name": "Grace"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == single_step_wizard_url
    assert response.content != f"completed {run_id}".encode()
    assert client.session["gandalf_runs"][run_id] == {"completed": True}


def test_unknown_run_redirects_to_the_start_url(
    client, single_step_wizard_url, single_step_wizard_run_url
):
    client.get(single_step_wizard_url)

    response = client.get(
        single_step_wizard_run_url("11111111-1111-1111-1111-111111111111")
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == single_step_wizard_url


def test_run_url_with_no_session_at_all_redirects_to_the_start_url(
    client, single_step_wizard_url, single_step_wizard_run_url
):
    response = client.get(
        single_step_wizard_run_url("11111111-1111-1111-1111-111111111111")
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == single_step_wizard_url


def test_post_to_an_unknown_run_redirects_without_starting_one(
    client, single_step_wizard_url, single_step_wizard_run_url
):
    run_url = single_step_wizard_run_url("11111111-1111-1111-1111-111111111111")

    response = client.post(_step(run_url, "first"), data={"name": "Ada"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == single_step_wizard_url
    assert client.session.get("gandalf_runs", {}) == {}


def test_obliterated_run_revisit_redirects_to_the_start_url(
    client,
    escape_obliterate_wizard_url,
    escape_obliterate_wizard_run_url,
):
    client.get(escape_obliterate_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_obliterate_wizard_run_url(run_id), "cancel"),
        data={"reason": "changed my mind", "cancel": "on"},
    )

    response = client.get(escape_obliterate_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == escape_obliterate_wizard_url


def test_advancing_escape_on_the_final_step_still_defers_done_to_the_revisit(
    client,
    escape_advance_final_step_wizard_url,
    escape_advance_final_step_wizard_run_url,
):
    client.get(escape_advance_final_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_advance_final_step_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    # The escape deferred done(), so the run is complete but unfinished: the
    # first revisit is what fires done(), and it tombstones the run.
    first = client.get(escape_advance_final_step_wizard_run_url(run_id))
    assert first.status_code == HTTPStatus.OK
    assert first.content == f"completed {run_id}".encode()

    second = client.get(escape_advance_final_step_wizard_run_url(run_id))

    assert second.status_code == HTTPStatus.FOUND
    assert second["Location"] == escape_advance_final_step_wizard_url
    assert client.session["gandalf_runs"][run_id] == {"completed": True}


def test_run_unavailable_override_is_told_the_run_completed(
    client, run_unavailable_wizard_url, run_unavailable_wizard_run_url
):
    run_id, _ = _complete_single_step_run(
        client, run_unavailable_wizard_url, run_unavailable_wizard_run_url
    )

    response = client.get(run_unavailable_wizard_run_url(run_id))

    assert response.status_code == HTTPStatus.GONE
    assert response.content == b"unavailable: completed"


def test_run_unavailable_override_is_told_the_run_is_unknown(
    client, run_unavailable_wizard_url, run_unavailable_wizard_run_url
):
    client.get(run_unavailable_wizard_url)

    response = client.get(
        run_unavailable_wizard_run_url("11111111-1111-1111-1111-111111111111")
    )

    assert response.status_code == HTTPStatus.GONE
    assert response.content == b"unavailable: unknown"


def test_completed_run_redirect_keeps_the_mount_prefix_kwargs(client):
    start_url = reverse("org-scoped-wizard", kwargs={"org": "acme"})
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("org-scoped-wizard-run", kwargs={"org": "acme", "run_id": run_id})
    client.post(_step(run_url, "first"), data={"name": "Ada"})
    client.post(_step(run_url, "review"), data={"confirmed": "on"})

    response = client.get(run_url)

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == start_url


def test_dynamic_wizard_does_not_complete_before_its_generated_steps(client):
    start_url = reverse("dynamic-wizard")
    client.get(start_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    run_url = reverse("dynamic-wizard-run", kwargs={"run_id": run_id})

    response = client.post(_step(run_url, "count"), data={"count": "3"})

    # The tree resolved at the start of this POST had no item steps yet, so
    # completion has to be judged against the tree the submission implies —
    # otherwise the run finishes here and done() fires three steps early.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == _step(run_url, "item-0")
    assert client.session["gandalf_runs"][run_id]["state"] == [{"step": {"count": "3"}}]


def test_bare_run_url_post_on_a_live_run_redirects_without_storing(
    client, routed_wizard_urls, routed_wizard_run
):
    response = client.post(
        routed_wizard_urls(routed_wizard_run),
        data={"account_type": "business"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_wizard_urls(routed_wizard_run, "account_type")
    assert client.session["gandalf_runs"][routed_wizard_run].get("state", []) == []


def test_bare_run_url_post_on_a_complete_but_unfinished_run_returns_to_the_run(
    client,
    escape_advance_final_step_wizard_url,
    escape_advance_final_step_wizard_run_url,
):
    client.get(escape_advance_final_step_wizard_url)
    run_id, _ = get_only_run_info_from_session(client.session)
    client.post(
        _step(escape_advance_final_step_wizard_run_url(run_id), "newsletter"),
        data={"email": "ada@example.com", "subscribe": "on"},
    )

    # Advance deferred done(), so the run is complete with no cursor to point
    # at — a bare-URL POST goes back to the run URL, which finishes it.
    response = client.post(
        escape_advance_final_step_wizard_run_url(run_id),
        data={"email": "grace@example.com"},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == escape_advance_final_step_wizard_run_url(run_id)


def test_misconfigured_wizard_unknown_run_raises_improperly_configured(client):
    from django.core.exceptions import ImproperlyConfigured

    session = client.session
    session["gandalf_runs"] = {}
    session.save()

    with pytest.raises(ImproperlyConfigured, match="get_start_url"):
        client.get(
            reverse(
                "misconfigured-wizard-run",
                kwargs={"run_id": "11111111-1111-1111-1111-111111111111"},
            )
        )


def test_completion_tombstones_are_pruned_to_the_storage_cap(client):
    start_url = reverse("pruned-completion-wizard")
    completed = []

    for name in ("Ada", "Grace", "Mary"):
        client.get(start_url)
        run_id = next(
            key
            for key, data in client.session["gandalf_runs"].items()
            if not data.get("completed")
        )
        client.post(
            reverse(
                "pruned-completion-wizard-step",
                kwargs={"run_id": run_id, "gandalf_step": "first"},
            ),
            data={"name": name},
        )
        completed.append(run_id)

    # Storage keeps two tombstones, so the oldest completed run is dropped.
    assert list(client.session["gandalf_runs"]) == completed[1:]


def test_wizard_configured_storage_class_raises_improperly_configured(client):
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match="WizardViewSet.storage_class"):
        client.get(reverse("wizard-configured-storage"))
