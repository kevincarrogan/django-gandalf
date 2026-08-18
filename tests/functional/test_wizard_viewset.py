from http import HTTPStatus
import os
import re

from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
import pytest
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertRedirects,
    assertTemplateUsed,
)

from gandalf.driver import RunDriver
from gandalf.testing import (
    WizardTestDriver,
    seed_run,
    seed_stash,
    stored_runs,
    stored_stash,
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
from tests.testapp.views import CrossBranchWizardViewSet, DynamicWizardViewSet


def test_wizard_viewset_redirects_to_run_url_on_initialise(client, wizard_driver):
    driver = wizard_driver("single-step-wizard")

    response = client.get(driver.start_url)

    run = driver.only_run()
    assertRedirects(response, run.url, fetch_redirect_response=False)
    assert run.data == {}


def test_wizard_viewset_delegates_run_get_to_first_step_form(wizard_driver):
    run = wizard_driver("single-step-wizard").start()

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_wizard_viewset_delegates_run_post_to_first_step_form(wizard_driver):
    run = wizard_driver("single-step-wizard").start()

    response = run.post_step("first", {"name": ""}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)
    assert response.context["form"].errors == {
        "name": ["This field is required."],
    }


def test_single_step_wizard_valid_post_returns_done_response(wizard_driver):
    run = wizard_driver("single-step-wizard").start()

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run.run_id}".encode()


def test_single_step_wizard_revisit_after_completion_does_not_rerun_done(
    wizard_driver,
):
    driver = wizard_driver("single-step-wizard")
    run = driver.start()
    completion = run.post_step("first", {"name": "Ada"}, follow=True)
    assert completion.content == f"completed {run.run_id}".encode()

    response = run.get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url
    assert response.content != f"completed {run.run_id}".encode()


def test_single_step_wizard_done_can_read_submitted_form_data(wizard_driver):
    run = wizard_driver("single-step-wizard-done-data").start()

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada"


def test_single_step_wizard_done_can_read_run_data(wizard_driver):
    run = wizard_driver("single-step-wizard-done-run-data").start()

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada"


def test_linear_wizard_run_starts_with_first_declared_form(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assertContains(response, '<input type="text" name="name"')


def test_linear_wizard_valid_first_step_renders_next_declared_form(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="email" name="email"')
    assert run.state == [
        {"step": {"name": "Ada"}},
    ]


def test_linear_wizard_replaces_invalid_submission_on_next_post(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    run.post_step("first", {"name": ""}, follow=True)
    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)
    assert run.state == [
        {"step": {"name": "Ada"}},
    ]


def test_the_csrf_token_a_browser_posts_is_not_stored_as_an_answer(wizard_driver):
    """Every form a browser submits carries `csrfmiddlewaretoken`, and it
    answers nothing. Stored, it rides into `stash()` and out to wherever the
    application keeps one — so a session's CSRF secret, which is what the
    token unmasks to, ends up in a durable store nobody meant to put it in.
    The middleware has already checked it long before the viewset reads the
    POST, so dropping it here costs the protection nothing.
    """
    run = wizard_driver("linear-wizard").start()

    run.post_step(
        "first", {"name": "Ada", "csrfmiddlewaretoken": "sekrit"}, follow=True
    )

    assert run.state == [
        {"step": {"name": "Ada"}},
    ]


def test_wizard_preserves_valid_previous_submission_when_posting_next_step(
    routed_run,
):
    # Uses a three-step wizard so the run is still live after the second
    # POST: a completed run is tombstoned, so its state is deliberately no
    # longer inspectable.
    routed_run.post_step("account_type", {"account_type": "business"})
    response = routed_run.post_step("business_name", {"business_name": "Acme"})

    assert response.status_code == HTTPStatus.FOUND
    assert routed_run.state == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_multi_value_wizard_valid_multi_select_renders_next_declared_form(
    wizard_driver,
):
    run = wizard_driver("multi-value-wizard").start()

    response = run.post_step("toppings", {"toppings": ["cheese", "basil"]}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}
    assert run.state == [
        {"step": {"toppings": ["cheese", "basil"]}},
    ]


def test_multi_value_wizard_single_selection_cleans_back_to_a_list(wizard_driver):
    run = wizard_driver("multi-value-wizard").start()

    response = run.post_steps(
        [
            ("toppings", {"toppings": ["cheese"]}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed cheese for ada@example.com"


def test_multi_value_wizard_done_reads_every_selected_value(wizard_driver):
    run = wizard_driver("multi-value-wizard").start()

    response = run.post_steps(
        [
            ("toppings", {"toppings": ["cheese", "basil"]}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed cheese,basil for ada@example.com"


def test_multi_value_wizard_stored_multi_select_replays_without_errors(
    wizard_driver,
):
    run = wizard_driver("multi-value-wizard").start()
    run.post_step("toppings", {"toppings": ["cheese", "basil"]}, follow=True)

    response = run.get_step("second", follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_linear_wizard_done_can_read_submitted_form_data_from_each_step(
    wizard_driver,
):
    run = wizard_driver("done-linear-wizard").start()

    response = run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"


def test_linear_wizard_bare_url_post_after_done_neither_stores_nor_reruns_done(
    wizard_driver,
):
    driver = wizard_driver("done-linear-wizard")
    run = driver.start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    completion = run.post_step("second", {"email": "ada@example.com"}, follow=True)
    assert completion.content == b"completed Ada at ada@example.com"

    response = run.post({"email": "grace@example.com"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url
    assert run.data == {"completed": True}


def test_linear_wizard_get_after_valid_first_step_renders_next_declared_form(
    wizard_driver,
):
    run = wizard_driver("linear-wizard").start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], SecondStepForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="email" name="email"')


def test_branching_wizard_valid_step_renders_first_step_in_matching_branch(
    wizard_driver,
):
    run = wizard_driver("branching-wizard").start()

    response = run.post_step("account_type", {"account_type": "business"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], BusinessDetailsForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="text" name="business_name"')
    assert run.state == [
        {"step": {"account_type": "business"}},
    ]


def test_branching_wizard_valid_step_renders_first_step_in_default_branch(
    wizard_driver,
):
    run = wizard_driver("branching-wizard").start()

    response = run.post_step("account_type", {"account_type": "personal"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], PersonalDetailsForm)
    assert response.context["form"].errors == {}
    assertContains(response, '<input type="text" name="preferred_name"')
    assert run.state == [
        {"step": {"account_type": "personal"}},
    ]


def test_branching_wizard_post_inside_arm_records_nested_state(wizard_driver):
    run = wizard_driver("branching-wizard").start()
    run.post_step("account_type", {"account_type": "business"}, follow=True)

    response = run.post_step("business_name", {"business_name": "Acme"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], ReviewForm)
    assert run.state == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_done_branching_wizard_complete_flow_uses_runtime_tree(wizard_driver):
    run = wizard_driver("done-branching-wizard").start()

    response = run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business", {"business_name": "Acme"}),
            ("review", {"confirmed": "on"}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"completed 4 via ReviewForm missing=None account_count=1 declared_count=5"
    )


@pytest.fixture
def editing_branching_run(wizard_driver):
    """A run of the editing branching wizard with the business arm answered,
    parked on the review summary."""
    run = wizard_driver("editing-branching-wizard").start()
    run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme"}),
        ]
    )
    return run


def test_editing_branching_wizard_get_completed_step_renders_form_with_initial(
    editing_branching_run,
):
    response = editing_branching_run.get_step("account_type")

    assert response.status_code == HTTPStatus.OK
    form = response.context["form"]
    assert isinstance(form, AccountTypeForm)
    assert form.is_bound is False
    assert form.initial == {"account_type": "business"}


def test_editing_branching_wizard_post_edit_keeping_arm_preserves_downstream(
    editing_branching_run,
):
    response = editing_branching_run.post_step(
        "account_type", {"account_type": "business"}, follow=True
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)
    assert editing_branching_run.state == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_editing_branching_wizard_post_edit_changing_arm_keeps_dormant_arm(
    editing_branching_run,
):
    response = editing_branching_run.post_step(
        "account_type", {"account_type": "personal"}, follow=True
    )

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], PersonalDetailsForm)
    assert editing_branching_run.state == [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_editing_branching_wizard_full_reentrant_loop(editing_branching_run):
    """The re-entrant summary pattern end to end: trivial edits bounce
    straight back to the summary, a diverting edit asks only the new arm's
    steps, and flipping the branch answer back restores the dormant arm."""
    run = editing_branching_run

    response = run.get(follow=True)
    assert isinstance(response.context["form"], ReviewForm)

    # Trivial edit from the summary: change lands, user is back on the
    # summary immediately.
    response = run.post_step("business_name", {"business_name": "Globex"}, follow=True)
    assert isinstance(response.context["form"], ReviewForm)

    # Diverting edit: the flow re-routes to the personal arm and asks only
    # its unanswered step.
    response = run.post_step("account_type", {"account_type": "personal"}, follow=True)
    assert isinstance(response.context["form"], PersonalDetailsForm)

    # Answering the diverted step (a plain submission, no edit marker)
    # returns straight to the summary.
    response = run.post_step("preferred_name", {"preferred_name": "Ada"}, follow=True)
    assert isinstance(response.context["form"], ReviewForm)

    # Flipping the branch answer back restores the dormant business arm
    # without re-asking it, landing on the summary again.
    response = run.post_step("account_type", {"account_type": "business"}, follow=True)
    assert isinstance(response.context["form"], ReviewForm)
    assert run.state == [
        {"step": {"account_type": "business"}},
        {
            "branch": {
                "0": [{"step": {"business_name": "Globex"}}],
                "default": [{"step": {"preferred_name": "Ada"}}],
            }
        },
    ]


def test_editing_branching_wizard_resumes_legacy_bare_list_branch_state(
    wizard_driver,
):
    run = wizard_driver("editing-branching-wizard").start()
    run.seed_state(
        [
            {"step": {"account_type": "business"}},
            {"branch": [{"step": {"business_name": "Acme"}}]},
        ]
    )

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)


@pytest.fixture
def routed_run(wizard_driver):
    return wizard_driver("routed-wizard").start()


def test_routed_wizard_bare_run_url_redirects_to_cursor_step_url(routed_run):
    response = routed_run.get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("account_type")


def test_routed_wizard_get_cursor_step_url_renders_form(routed_run):
    response = routed_run.get_step("account_type")

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], AccountTypeForm)


def test_routed_wizard_valid_submit_redirects_to_next_step_url(routed_run):
    response = routed_run.post_step("account_type", {"account_type": "business"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("business_name")


def test_routed_wizard_invalid_submit_redirects_and_rerenders_with_errors(
    client, routed_run
):
    response = routed_run.post_step("account_type", {"account_type": "not-a-choice"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("account_type")
    followed = client.get(response["Location"])
    assert followed.status_code == HTTPStatus.OK
    assert followed.context["form"].errors == {
        "account_type": [
            "Select a valid choice. not-a-choice is not one of the available choices."
        ],
    }


def test_routed_wizard_get_completed_step_url_renders_prefilled_form(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})

    response = routed_run.get_step("account_type")

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].initial == {"account_type": "business"}


def test_routed_wizard_get_unknown_step_url_redirects_to_cursor(routed_run):
    response = routed_run.get_step("missing")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("account_type")


def test_routed_wizard_get_future_step_url_redirects_to_cursor(routed_run):
    response = routed_run.get_step("review")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("account_type")


def test_routed_wizard_trivial_edit_redirects_back_to_summary(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})

    response = routed_run.post_step("business_name", {"business_name": "Globex"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("review")
    state = routed_run.state
    assert state[1] == {"branch": {"0": [{"step": {"business_name": "Globex"}}]}}


def test_routed_wizard_diverting_edit_redirects_to_new_arm_step(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})

    response = routed_run.post_step("account_type", {"account_type": "personal"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("preferred_name")


def test_routed_wizard_invalid_edit_renders_errors_without_redirect(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})
    response = routed_run.post_step("business_name", {"business_name": ""}, follow=True)

    # Placement is placement: a rejected submission is kept and parked on,
    # exactly as for a step being answered the first time. The errors below
    # come from a *fresh walk* after the redirect, which is only possible if
    # the rejected data was persisted and replayed.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {
        "business_name": ["This field is required."],
    }


def test_routed_wizard_dormant_step_url_redirects_instead_of_500(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})
    routed_run.post_step("account_type", {"account_type": "personal"})

    response = routed_run.get_step("business_name")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("preferred_name")


def test_routed_wizard_stale_tab_post_redirects_without_storing(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})
    routed_run.post_step("account_type", {"account_type": "personal"})
    state_before = routed_run.state

    response = routed_run.post_step("review", {"confirmed": "on"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("preferred_name")
    assert routed_run.state == state_before


def test_routed_wizard_renders_back_link_to_previous_step(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})

    response = routed_run.get_step("business_name")

    assert response.status_code == HTTPStatus.OK
    back_url = routed_run.step_url("account_type")
    assertContains(response, f'<a href="{back_url}">Back</a>', html=True)


def test_routed_wizard_first_step_renders_without_back_link(routed_run):
    response = routed_run.get_step("account_type")

    assert response.status_code == HTTPStatus.OK
    assertNotContains(response, ">Back</a>", html=False)


def test_routed_wizard_step_behind_an_unanswered_step_is_unreachable(routed_run):
    """A claim is only honoured by arriving at it, and the walk stops at the
    first unanswered step. So a later step that still holds an answer is not
    renderable while something before it is missing — its form would
    otherwise run against a prefix the walk has not proven."""
    routed_run.seed_state(
        [
            {"step": None},
            {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
            {"step": {"confirmed": "on"}},
        ]
    )

    response = routed_run.get_step("review")

    assertRedirects(response, routed_run.step_url("account_type"))


def test_routed_wizard_final_submit_completes_run(routed_run):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})

    response = routed_run.post_step("review", {"confirmed": "on"})

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {routed_run.run_id}".encode()


def test_routed_wizard_unknown_step_url_on_completed_run_redirects_to_start(
    routed_run,
):
    routed_run.post_step("account_type", {"account_type": "business"})
    routed_run.post_step("business_name", {"business_name": "Acme"})
    routed_run.post_step("review", {"confirmed": "on"})

    response = routed_run.get_step("missing")

    # The run is finished, so there is no cursor to send the user back to —
    # every URL under a completed run resolves to `run_unavailable()`.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse("routed-wizard")


def test_unroutable_wizard_raises_improperly_configured(client):
    with pytest.raises(ImproperlyConfigured, match="FirstStepForm"):
        client.get(reverse("unroutable-wizard"))


def test_org_scoped_wizard_edit_render_receives_url_kwargs(wizard_driver):
    run = wizard_driver("org-scoped-wizard", org="acme").start()
    run.post_step("first", {"name": "Ada"})

    response = run.get_step("first")

    assert response.status_code == HTTPStatus.OK
    assert response.context["org"] == "acme"
    assert response.context["form"].initial == {"name": "Ada"}


def test_org_scoped_wizard_invalid_edit_error_render_receives_url_kwargs(
    wizard_driver,
):
    run = wizard_driver("org-scoped-wizard", org="acme").start()
    run.post_step("first", {"name": "Ada"})

    response = run.post_step("first", {"name": ""}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.context["org"] == "acme"
    assert response.context["form"].errors == {"name": ["This field is required."]}


def test_org_scoped_wizard_start_redirects_within_same_mount(client, wizard_driver):
    driver = wizard_driver("org-scoped-wizard", org="acme")

    response = client.get(driver.start_url)

    run = driver.only_run()
    assertRedirects(response, run.url, target_status_code=HTTPStatus.FOUND)


def test_org_scoped_wizard_submission_redirects_within_same_mount(wizard_driver):
    run = wizard_driver("org-scoped-wizard", org="acme").start()

    response = run.post_step("first", {"name": "Ada"})

    assertRedirects(response, run.step_url("review"))


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

    seed_run(client, "11111111-1111-1111-1111-111111111111", {})

    with pytest.raises(ImproperlyConfigured, match="get_step_url"):
        client.get(
            reverse(
                "misconfigured-wizard-run",
                kwargs={"run_id": "11111111-1111-1111-1111-111111111111"},
            )
        )


def test_programmatic_lookup_wizard_probes_step_not_found_mid_run(wizard_driver):
    run = wizard_driver("programmatic-lookup-wizard").start()
    run.post_step("first", {"name": "Ada"})

    response = run.get_step("second")

    assert response.status_code == HTTPStatus.OK
    assert response.context["lookup_probe"] == "step-not-found"
    assert response.context["name_lookup_probe"] == "first"


def test_programmatic_lookup_wizard_edit_of_missing_step_deletes_new_uploads(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("programmatic-lookup-wizard").start()
    run.post_step("first", {"name": "Ada"})

    response = run.post_step("second", {"email": "ada@example.com"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"completed edit-cleanup=True nav-probe=True resolve-status=200 "
        b"declaration-claim=True ambiguous=True"
    )


@pytest.fixture
def cross_branch_run(client, wizard_driver):
    """A run answered all the way down the business arm and then diverted to
    the personal one, so both branches hold dormant answers and the review
    answer still stands behind the step the divert re-asks.

    Filled with a `RunDriver` rather than seeded, because the last answer a
    browser would post is the review — which completes the run and fires
    `done()`. A driver places the same answers and stops there, leaving the
    run to be diverted afterwards. `metadata={}` for the same reason: this
    stands in for a journey somebody made in a browser, and a browser records
    nothing about a placement.
    """
    run = wizard_driver("cross-branch-wizard").start()
    session = client.session
    driver = RunDriver.resume(
        CrossBranchWizardViewSet,
        run.run_id,
        session=session,
    )
    driver.submit({"account_type": "business"}, metadata={})
    driver.submit({"business_name": "Acme"}, metadata={})
    driver.submit({"email": "ada@example.com"}, metadata={})
    driver.submit({"confirmed": "on"}, metadata={})
    driver.submit({"account_type": "personal"}, step="account_type", metadata={})
    # Nothing saves a session outside the request cycle, and the run the
    # test then requests is read back from the store.
    session.save()
    return run


def test_cross_branch_wizard_path_read_is_safe_mid_divert(cross_branch_run):
    response = cross_branch_run.get_step("preferred_name")

    assert response.status_code == HTTPStatus.OK
    assert response.context["path_names"] == ["account_type", "review"]


def test_cross_branch_wizard_edit_is_safe_mid_divert(cross_branch_run):
    response = cross_branch_run.post_step("account_type", {"account_type": "personal"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == cross_branch_run.step_url("preferred_name")
    state = cross_branch_run.state
    assert state[0] == {"step": {"account_type": "personal"}}
    assert state[1] == {"branch": {"0": [{"step": {"business_name": "Acme"}}]}}
    assert state[3] == {"step": {"confirmed": "on"}}


def test_branch_entry_wizard_renders_default_arm_first_step(wizard_driver):
    run = wizard_driver("branch-entry-wizard").start()

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_duplicate_step_names_are_rejected_when_the_wizard_resolves(client):
    """Two steps sharing a name is a declaration error, so it is caught when
    the wizard resolves rather than per request — a walk stops at the cursor
    and so cannot see a duplicate lying beyond it."""
    with pytest.raises(ImproperlyConfigured, match="must be unique"):
        client.get(reverse("duplicate-context-wizard"))


def test_wizard_viewset_without_done_raises_not_implemented_on_final_step(
    wizard_driver,
):
    run = wizard_driver("single-step-wizard-without-done").start()

    with pytest.raises(
        NotImplementedError,
        match="WizardViewSet subclasses must define done().",
    ):
        run.post_step("first", {"name": "Ada"}, follow=True)


def test_linear_wizard_submissions_do_not_leak_to_new_client(client, wizard_driver):
    second_client = client.__class__()
    first_run = wizard_driver("linear-wizard").start()
    second_run = WizardTestDriver(second_client, "linear-wizard").start()

    first_run.post_step("first", {"name": "Ada"}, follow=True)
    response = second_run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_submissions_persist_for_same_client(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_linear_wizard_submissions_do_not_leak_to_different_wizard(wizard_driver):
    linear_run = wizard_driver("linear-wizard").start()
    linear_run.post_step("first", {"name": "Ada"}, follow=True)

    other_run = wizard_driver("other-linear-wizard").start()
    response = other_run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_linear_wizard_submissions_survive_recreated_declaration(wizard_driver):
    run = wizard_driver("linear-wizard").start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    recreated_run = wizard_driver("recreated-linear-wizard").run(run.run_id)
    response = recreated_run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_wizard_viewset_rejects_invalid_wizard_type(client):
    with pytest.raises(
        TypeError,
        match="WizardViewSet.wizard must be a Wizard or ConfiguredWizard",
    ):
        client.get(reverse("invalid-wizard"))


def test_wizard_viewset_accepts_form_view_step(client, wizard_driver):
    driver = wizard_driver("form-view-step-wizard")
    response = client.get(driver.start_url)
    run = driver.only_run()

    assertRedirects(response, run.url, fetch_redirect_response=False)

    response = run.get(follow=True)
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)

    response = run.post_step("first", {"name": "Ada"}, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run.run_id}".encode()


def test_wizard_viewset_raises_when_form_step_has_no_template_name(client):
    with pytest.raises(
        ImproperlyConfigured,
        match="template_name",
    ):
        client.get(reverse("missing-template-wizard"))


def test_wizard_viewset_accepts_pre_configured_wizard(client, wizard_driver):
    driver = wizard_driver("pre-configured-wizard")
    response = client.get(driver.start_url)
    run = driver.only_run()

    assertRedirects(response, run.url, fetch_redirect_response=False)

    response = run.get(follow=True)
    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/single_step_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)

    response = run.post_step("first", {"name": "Ada"}, follow=True)
    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run.run_id}".encode()


def test_wizard_viewset_rejects_reconfiguring_configured_wizard(client):
    with pytest.raises(
        ImproperlyConfigured,
        match="ConfiguredWizard instances cannot be configured.",
    ):
        client.get(reverse("double-configured-wizard"))


def test_dynamic_wizard_generates_step_per_chosen_count(wizard_driver):
    run = wizard_driver("dynamic-wizard").start()

    first_response = run.get(follow=True)
    assert first_response.status_code == HTTPStatus.OK
    assert "count" in first_response.context["form"].fields

    run.post_step("count", {"count": "3"}, follow=True)

    for index, name in enumerate(("Ada", "Grace", "Mary")):
        response = run.get(follow=True)
        assert response.status_code == HTTPStatus.OK
        assert "name" in response.context["form"].fields
        done_response = run.post_step(f"item-{index}", {"name": name}, follow=True)

    # The final item's POST completes the run and fires done() there; the
    # run is tombstoned afterwards, so nothing re-fires it.
    assert done_response.status_code == HTTPStatus.OK
    assert done_response.content == b"completed Ada, Grace, Mary"


def test_dynamic_list_payload_wizard_condenses_items_into_list(wizard_driver):
    import json

    run = wizard_driver("dynamic-list-payload-wizard").start()

    response = run.post_steps(
        [
            ("count", {"count": "3"}),
            ("item-0", {"name": "Ada"}),
            ("item-1", {"name": "Grace"}),
            ("item-2", {"name": "Mary"}),
        ]
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


def test_dynamic_wizard_regenerates_tree_from_current_stored_state(
    client, wizard_driver
):
    """A run whose stored state already holds every answer: the GET has to
    rebuild the item steps from the count before it can call the run finished.

    A `RunDriver` fills it, because the browser's last POST would complete the
    run itself and there would be no request left to prove anything.
    """
    run = wizard_driver("dynamic-wizard").start()
    session = client.session
    driver = RunDriver.resume(
        DynamicWizardViewSet,
        run.run_id,
        session=session,
    )
    driver.prefill(
        {
            "count": {"count": "2"},
            "item-0": {"name": "Ada"},
            "item-1": {"name": "Grace"},
        }
    )
    session.save()

    done_response = run.get(follow=True)
    assert done_response.status_code == HTTPStatus.OK
    assert done_response.content == b"completed Ada, Grace"


def test_empty_wizard_run_returns_done_response_immediately(client, wizard_driver):
    driver = wizard_driver("empty-wizard")
    response = client.get(driver.start_url)

    run = driver.only_run()
    assertRedirects(response, run.url, fetch_redirect_response=False)

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run.run_id}".encode()


def test_linear_wizard_done_can_merge_cleaned_data_across_path(wizard_driver):
    run = wizard_driver("merged-payload-wizard").start()

    response = run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed name=Ada email=ada@example.com"


def test_step_view_can_pre_fill_initial_from_request_wizard_path(wizard_driver):
    run = wizard_driver("path-aware-linear-wizard").start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="ada@example.com"')


def test_step_view_can_pre_fill_initial_from_path_with_form_view_upstream(
    wizard_driver,
):
    run = wizard_driver("path-aware-form-view-first-step-wizard").start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="ada@example.com"')


def test_step_reading_the_run_from_get_initial_survives_being_walked_past(
    wizard_driver,
):
    # Answering the path-reading step leaves it behind the cursor, so every
    # later request replays it — re-entering the read from inside the walk.
    run = wizard_driver("path-aware-walked-past-wizard").start()

    run.post_step("first", {"name": "Ada"}, follow=True)
    response = run.post_step("second", {"email": "ada@example.com"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)


def test_step_reading_the_run_from_get_initial_completes_the_run(wizard_driver):
    # done() reduces over the path, which reconstructs every step's form —
    # including the reading step's, driving its get_initial() once more.
    run = wizard_driver("path-aware-walked-past-wizard").start()

    response = run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
            ("third", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed Ada at ada@example.com"


def test_first_step_reading_the_run_sees_an_empty_path(client, wizard_driver):
    # The prefix before the first step is empty, which must read as an empty
    # path rather than sending the read off to start its own walk.
    driver = wizard_driver("empty-path-first-step-wizard")

    response = client.get(driver.start_url, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="seen-0"')


def test_first_step_reading_the_run_sees_an_empty_path_on_replay(wizard_driver):
    # Rendering the first step is served from the recorded render context, so
    # the empty prefix only reaches the walk once the step is behind the
    # cursor and every later request replays it.
    run = wizard_driver("empty-path-first-step-wizard").start()

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], SecondStepForm)


def test_branch_predicate_at_position_zero_sees_an_empty_path(client, wizard_driver):
    # Same empty prefix, reached through a branch predicate instead of a step
    # view: the predicate reads no prior answers and takes the first arm.
    driver = wizard_driver("empty-path-branch-wizard")

    response = client.get(driver.start_url, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_branching_wizard_done_merges_cleaned_data_across_multi_step_arm_path(
    wizard_driver,
):
    run = wizard_driver("branching-merged-payload-wizard").start()

    response = run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme"}),
            ("second", {"email": "acme@example.com"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"account_type=business "
        b"business_name=Acme "
        b"email=acme@example.com "
        b"confirmed=True"
    )


def test_branching_wizard_with_unmatched_no_default_arm_drops_branch_from_path(
    wizard_driver,
):
    run = wizard_driver("empty-branch-arm-merged-payload-wizard").start()

    response = run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("skip_branch_account", {"account_type": "personal"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"name=Ada account_type=personal"


def test_branching_wizard_done_can_merge_cleaned_data_across_runtime_tree(
    wizard_driver,
):
    run = wizard_driver("runtime-tree-branching-merge-wizard").start()

    response = run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == (
        b"account_type=business business_name=Acme confirmed=True"
    )


def test_section_editing_wizard_uses_custom_step_router_for_get(wizard_driver):
    run = wizard_driver("section-editing-wizard").start()
    run.post_steps(
        [
            ("account", {"account_type": "personal"}),
            ("details", {"preferred_name": "Ada"}),
        ]
    )

    response = run.get_step("account")

    assert response.status_code == HTTPStatus.OK
    form = response.context["form"]
    assert isinstance(form, AccountTypeForm)
    assert form.initial == {"account_type": "personal"}


def test_section_editing_wizard_uses_custom_step_router_for_post(wizard_driver):
    run = wizard_driver("section-editing-wizard").start()
    run.post_steps(
        [
            ("account", {"account_type": "personal"}),
            ("details", {"preferred_name": "Ada"}),
        ]
    )

    response = run.post_step("account", {"account_type": "business"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], ReviewForm)
    assert run.state[0]["step"] == {"account_type": "business"}


_STORED_UPLOAD = re.compile(
    r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}-(?P<name>.+)$"
)


def uploads_stored_for(media_root, run_id):
    """The uploads still held for a run, under the names the user gave them.

    Every key carries a uuid segment so that two uploads of one filename
    cannot share one (#36); these tests are about which uploads survive an
    edit, not about the segment, and the pattern fails loudly if a key ever
    arrives without one.
    """
    run_dir = os.path.join(media_root, "gandalf", run_id)
    names = []
    for key in os.listdir(run_dir):
        match = _STORED_UPLOAD.match(key)
        assert match is not None, f"stored upload {key!r} carries no uuid segment"
        names.append(match["name"])
    return sorted(names)


def test_file_uploading_wizard_persists_upload_and_advances(
    wizard_driver, isolated_media_root
):
    import os

    run = wizard_driver("file-uploading-wizard").start()

    response = run.post_step(
        "photo",
        {"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assertContains(response, '<input type="text" name="name"')
    [photo_entry] = run.state
    tmp_name = photo_entry["files"]["photo"]["tmp_name"]
    assert tmp_name.startswith(f"gandalf/{run.run_id}/")
    assert tmp_name.endswith("-avatar.jpg")
    assert photo_entry["files"]["photo"]["name"] == "avatar.jpg"
    assert os.path.exists(os.path.join(isolated_media_root, tmp_name))


def test_file_uploading_wizard_done_cleans_up_files(wizard_driver, isolated_media_root):
    import os

    run = wizard_driver("file-uploading-wizard").start()
    run.post_step(
        "photo",
        {"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
    )

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed avatar.jpg"
    run_dir = os.path.join(isolated_media_root, "gandalf", run.run_id)
    assert not os.path.exists(run_dir) or os.listdir(run_dir) == []


def test_file_uploading_wizard_replay_after_upload_re_renders_next_step(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("file-uploading-wizard").start()
    run.post_step(
        "photo",
        {"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
    )

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, '<input type="text" name="name"')


def test_file_done_wizard_completion_page_can_read_the_uploaded_file(
    wizard_driver, isolated_media_root
):
    """Issue #39: `done()` may hand back a `TemplateResponse`, which Django
    renders after the view returns. A completion page reading the run back
    reopens the step's upload at that point, so cleaning the run's files up
    the moment `done()` returned took them out from under the render."""
    run = wizard_driver("file-done-wizard").start()

    response = run.post_step(
        "photo",
        {"photo": SimpleUploadedFile("avatar.jpg", b"binary")},
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/file_done_wizard.html")
    assertContains(response, "avatar.jpg")
    assert uploads_stored_for(isolated_media_root, run.run_id) == []


def test_file_editing_wizard_edit_replaces_photo_and_deletes_old(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("file-editing-wizard").start()
    run.post_step(
        "photo",
        {
            "label": "First",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    response = run.post_step(
        "photo",
        {
            "label": "First",
            "photo": SimpleUploadedFile("second.jpg", b"second-bytes"),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert uploads_stored_for(isolated_media_root, run.run_id) == ["second.jpg"]


def test_file_editing_wizard_edit_adds_photo_to_step_without_one(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("file-editing-wizard").start()
    run.post_step("photo", {"label": "No photo yet"}, follow=True)

    response = run.post_step(
        "photo",
        {
            "label": "Now with photo",
            "photo": SimpleUploadedFile("later.jpg", b"later-bytes"),
        },
        follow=True,
    )

    assert response.status_code == HTTPStatus.OK
    assert uploads_stored_for(isolated_media_root, run.run_id) == ["later.jpg"]


def test_file_editing_wizard_edit_changing_label_keeps_photo(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("file-editing-wizard").start()
    run.post_step(
        "photo",
        {
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    response = run.post_step("photo", {"label": "Renamed"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    state = run.state
    assert state[0]["step"]["label"] == "Renamed"
    assert uploads_stored_for(isolated_media_root, run.run_id) == ["first.jpg"]


def test_file_editing_wizard_edit_get_renders_existing_photo(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("file-editing-wizard").start()
    run.post_step(
        "photo",
        {
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    response = run.get_step("photo")

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"].initial.get("photo"), object)
    assert "first.jpg" in response.context["form"].initial["photo"].name


def test_file_editing_wizard_edit_with_invalid_submission_keeps_state_and_files(
    wizard_driver, isolated_media_root
):
    run = wizard_driver("file-editing-wizard").start()
    run.post_step(
        "photo",
        {
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )
    response = run.post_step(
        "photo",
        {
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
    assert uploads_stored_for(isolated_media_root, run.run_id) == ["rejected.jpg"]


def test_file_editing_wizard_rejected_upload_survives_the_correction(
    wizard_driver, isolated_media_root
):
    """Issue #44: a rejected edit used to delete the upload it arrived with,
    and browsers cannot repopulate a file input — so correcting the text field
    silently kept the *old* photo while the user believed the new one had been
    saved. A rejected submission is now kept whole, upload included, so the
    correction keeps the photo that came with it."""

    run = wizard_driver("file-editing-wizard").start()
    run.post_step(
        "photo",
        {
            "label": "Original",
            "photo": SimpleUploadedFile("first.jpg", b"first-bytes"),
        },
        follow=True,
    )

    # Pick a replacement photo, but leave a required field blank.
    run.post_step(
        "photo",
        {
            "label": "",
            "photo": SimpleUploadedFile("second.jpg", b"second-bytes"),
        },
        follow=True,
    )
    # Correct the field. No file is re-sent, exactly as a browser would behave.
    run.post_step("photo", {"label": "Fixed"}, follow=True)

    state = run.state
    assert state[0]["step"]["label"] == "Fixed"
    assert state[0]["files"]["photo"]["name"] == "second.jpg"
    assert uploads_stored_for(isolated_media_root, run.run_id) == ["second.jpg"]


def test_file_editing_wizard_unknown_step_url_redirects(
    wizard_driver, isolated_media_root
):
    import os

    run = wizard_driver("file-editing-wizard").start()
    run.post_step("photo", {"label": "Only label"}, follow=True)
    state_before = run.state

    response = run.post_step(
        "nonexistent",
        {
            "label": "ignored",
            "photo": SimpleUploadedFile("orphan.jpg", b"orphan-bytes"),
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("review")
    assert run.state == state_before
    run_dir = os.path.join(isolated_media_root, "gandalf", run.run_id)
    assert not os.path.exists(run_dir) or os.listdir(run_dir) == []


def test_empty_branch_arm_context_finder_walks_both_trees(wizard_driver):
    run = wizard_driver("empty-branch-arm-context-finder-wizard").start()

    response = run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("matched", {"email": "ada@example.com"}),
            ("review", {"confirmed": "on"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    # Declared tree finder visits both arm steps (matched + skipped) plus the
    # two outer steps (first + review) = 4. Runtime tree finder descends the
    # active arm (matched) and skips the empty one: first + matched + review = 3.
    assert response.content == b"completed declared=4 runtime=3"


def test_branch_edit_rejection_wizard_edit_post_branch_step_with_invalid_keeps_state(
    wizard_driver,
):
    run = wizard_driver("branch-edit-rejection-wizard").start()
    run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
            ("review", {"confirmed": "on"}),
        ]
    )
    response = run.post_step("review", {"confirmed": ""}, follow=True)

    # Placement is placement: a rejected submission is kept and parked on,
    # exactly as for a step being answered the first time. The errors below
    # come from a *fresh walk* after the redirect, which is only possible if
    # the rejected data was persisted and replayed.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {"confirmed": ["This field is required."]}


def test_branch_edit_rejection_wizard_unvisited_step_url_redirects_to_cursor(
    wizard_driver,
):
    run = wizard_driver("branch-edit-rejection-wizard").start()
    run.post_step("first", {"name": "Ada"}, follow=True)
    state_before = run.state

    response = run.post_step("review", {"confirmed": "on"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("second")
    assert run.state == state_before


def test_branch_edit_rejection_wizard_edit_in_branch_arm_with_invalid_keeps_state(
    wizard_driver,
):
    run = wizard_driver("branch-edit-rejection-wizard").start()
    run.post_steps(
        [
            ("first", {"name": "Ada"}),
            ("second", {"email": "ada@example.com"}),
            ("review", {"confirmed": "on"}),
        ]
    )
    response = run.post_step("second", {"email": "not-an-email"}, follow=True)

    # Kept and parked on, like any other rejected submission. These errors
    # come from a fresh walk after the redirect, so they prove it was stored.
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors == {
        "email": ["Enter a valid email address."]
    }


def test_parking_escape_redirects_away_without_storing_the_submission(
    wizard_driver,
):
    run = wizard_driver("escape-park-wizard").start()

    response = run.post_step("email", {"email": "existing@example.com"})

    assertRedirects(response, reverse("escape-landing"))
    # Nothing was ever written: the walk validates before it persists, so a
    # parking escape simply declines to store rather than storing and undoing.
    assert run.state == []


def test_parking_escape_leaves_the_run_on_the_escaping_step(wizard_driver):
    run = wizard_driver("escape-park-wizard").start()
    run.post_step("email", {"email": "existing@example.com"})

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], EmailLookupForm)
    assertContains(response, '<input type="email" name="email"')


def test_parked_run_still_accepts_a_non_escaping_submission(wizard_driver):
    run = wizard_driver("escape-park-wizard").start()
    run.post_step("email", {"email": "existing@example.com"})

    response = run.post_step("email", {"email": "new@example.com"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)
    assert run.state == [
        {"step": {"email": "new@example.com"}},
    ]


def test_non_escaping_submission_advances_normally(wizard_driver):
    run = wizard_driver("escape-park-wizard").start()

    response = run.post_step("email", {"email": "new@example.com"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/linear_wizard.html")
    assert isinstance(response.context["form"], FirstStepForm)
    assert run.state == [
        {"step": {"email": "new@example.com"}},
    ]


def test_advancing_escape_redirects_away_and_stores_the_submission(wizard_driver):
    run = wizard_driver("escape-advance-wizard").start()

    response = run.post_step(
        "newsletter", {"email": "ada@example.com", "subscribe": "on"}
    )

    assertRedirects(response, reverse("escape-landing"))
    assert run.state == [
        {"step": {"email": "ada@example.com", "subscribe": "on"}},
    ]


def test_advancing_escape_resumes_the_run_at_the_next_step(wizard_driver):
    run = wizard_driver("escape-advance-wizard").start()
    run.post_step("newsletter", {"email": "ada@example.com", "subscribe": "on"})

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_run_completes_after_an_advancing_escape(wizard_driver):
    run = wizard_driver("escape-advance-wizard").start()
    run.post_step("newsletter", {"email": "ada@example.com", "subscribe": "on"})

    response = run.post_step("first", {"name": "Ada"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed ada@example.com"


def test_advancing_escape_on_the_final_step_defers_the_done_response(
    wizard_driver,
):
    run = wizard_driver("escape-advance-final-step-wizard").start()

    response = run.post_step(
        "newsletter", {"email": "ada@example.com", "subscribe": "on"}
    )

    assertRedirects(response, reverse("escape-landing"))


def test_completed_run_returns_done_when_revisited_after_escaping(wizard_driver):
    run = wizard_driver("escape-advance-final-step-wizard").start()
    run.post_step("newsletter", {"email": "ada@example.com", "subscribe": "on"})

    response = run.get()

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"completed {run.run_id}".encode()


def test_obliterating_escape_removes_the_run(client, wizard_driver):
    run = wizard_driver("escape-obliterate-wizard").start()

    response = run.post_step("cancel", {"reason": "changed my mind", "cancel": "on"})

    assertRedirects(response, reverse("escape-landing"))
    assert run.run_id not in stored_runs(client)


def test_form_view_step_without_an_escape_advances_normally(wizard_driver):
    run = wizard_driver("escape-obliterate-wizard").start()

    response = run.post_step("cancel", {"reason": "carrying on"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], FirstStepForm)


def test_editing_a_completed_step_escapes_like_any_other_placement(wizard_driver):
    run = wizard_driver("escape-editing-wizard").start()
    run.post_step("email", {"email": "new@example.com"})

    response = run.post_step("email", {"email": "existing@example.com"})

    # A step that escapes escapes wherever it sits. Swallowing it behind the
    # cursor let an edit store an answer the form had explicitly rejected —
    # the opposite of what Park means — so the submit and edit paths now
    # honour it identically, and Park declines to store.
    assertRedirects(response, reverse("escape-landing"))
    assert run.state == [
        {"step": {"email": "new@example.com"}},
    ]


def test_bare_escape_is_rejected_as_misuse(wizard_driver):
    run = wizard_driver("bare-escape-wizard").start()

    with pytest.raises(ImproperlyConfigured):
        run.post_step("bare", {"name": "Ada"})


def test_parking_escape_keeps_answers_from_earlier_steps(wizard_driver):
    run = wizard_driver("mid-flow-escape-park-wizard").start()
    run.post_step("first", {"name": "Ada"})

    response = run.post_step("email", {"email": "existing@example.com"})

    assertRedirects(response, reverse("escape-landing"))
    assert run.state == [
        {"step": {"name": "Ada"}},
    ]


def test_parked_run_returns_to_the_escaping_step_with_earlier_answers_intact(
    wizard_driver,
):
    run = wizard_driver("mid-flow-escape-park-wizard").start()
    run.post_step("first", {"name": "Ada"})
    run.post_step("email", {"email": "existing@example.com"})

    response = run.get(follow=True)

    assert response.status_code == HTTPStatus.OK
    assert isinstance(response.context["form"], EmailLookupForm)


def test_parking_escape_discards_the_upload_it_escaped_with(
    wizard_driver, isolated_media_root
):
    import os

    run = wizard_driver("escape-park-file-wizard").start()

    response = run.post_step(
        "photo",
        {
            "photo": SimpleUploadedFile("avatar.jpg", b"binary"),
            "abandon": "on",
        },
    )

    assertRedirects(response, reverse("escape-landing"))
    # Nothing was ever written: the walk validates before it persists, so a
    # parking escape simply declines to store rather than storing and undoing.
    assert run.state == []
    assert not os.path.exists(
        os.path.join(isolated_media_root, "gandalf", run.run_id, "avatar.jpg")
    )


# --- Completion lifecycle -------------------------------------------------
#
# `done()` fires exactly once per run. The run is tombstoned once it has,
# so every later request for it — and every request for a run that never
# existed — resolves to `run_unavailable()`.


def _complete_single_step_run(driver):
    run = driver.start()
    response = run.post_step("first", {"name": "Ada"})
    return run, response


def test_completing_a_run_replaces_its_state_with_a_tombstone(wizard_driver):
    run, _ = _complete_single_step_run(wizard_driver("single-step-wizard"))

    assert run.data == {"completed": True}


def test_completed_run_step_url_no_longer_renders_an_edit_form(wizard_driver):
    driver = wizard_driver("single-step-wizard")
    run, _ = _complete_single_step_run(driver)

    response = run.get_step("first")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url


def test_reposting_a_completed_runs_final_step_neither_edits_nor_reruns_done(
    wizard_driver,
):
    driver = wizard_driver("single-step-wizard")
    run, completion = _complete_single_step_run(driver)
    assert completion.content == f"completed {run.run_id}".encode()

    response = run.post_step("first", {"name": "Grace"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url
    assert response.content != f"completed {run.run_id}".encode()
    assert run.data == {"completed": True}


def test_unknown_run_redirects_to_the_start_url(wizard_driver):
    driver = wizard_driver("single-step-wizard")
    driver.start()

    response = driver.run("11111111-1111-1111-1111-111111111111").get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url


def test_run_url_with_no_session_at_all_redirects_to_the_start_url(wizard_driver):
    driver = wizard_driver("single-step-wizard")

    response = driver.run("11111111-1111-1111-1111-111111111111").get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url


def test_post_to_an_unknown_run_redirects_without_starting_one(client, wizard_driver):
    driver = wizard_driver("single-step-wizard")
    run = driver.run("11111111-1111-1111-1111-111111111111")

    response = run.post_step("first", {"name": "Ada"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url
    assert stored_runs(client) == {}


def test_obliterated_run_revisit_redirects_to_the_start_url(wizard_driver):
    driver = wizard_driver("escape-obliterate-wizard")
    run = driver.start()
    run.post_step("cancel", {"reason": "changed my mind", "cancel": "on"})

    response = run.get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url


def test_advancing_escape_on_the_final_step_still_defers_done_to_the_revisit(
    wizard_driver,
):
    driver = wizard_driver("escape-advance-final-step-wizard")
    run = driver.start()
    run.post_step("newsletter", {"email": "ada@example.com", "subscribe": "on"})

    # The escape deferred done(), so the run is complete but unfinished: the
    # first revisit is what fires done(), and it tombstones the run.
    first = run.get()
    assert first.status_code == HTTPStatus.OK
    assert first.content == f"completed {run.run_id}".encode()

    second = run.get()

    assert second.status_code == HTTPStatus.FOUND
    assert second["Location"] == driver.start_url
    assert run.data == {"completed": True}


def test_run_unavailable_override_is_told_the_run_completed(wizard_driver):
    run, _ = _complete_single_step_run(wizard_driver("run-unavailable-wizard"))

    response = run.get()

    assert response.status_code == HTTPStatus.GONE
    assert response.content == b"unavailable: completed"


def test_run_unavailable_override_is_told_the_run_is_unknown(wizard_driver):
    driver = wizard_driver("run-unavailable-wizard")
    driver.start()

    response = driver.run("11111111-1111-1111-1111-111111111111").get()

    assert response.status_code == HTTPStatus.GONE
    assert response.content == b"unavailable: unknown"


def test_completed_run_redirect_keeps_the_mount_prefix_kwargs(wizard_driver):
    driver = wizard_driver("org-scoped-wizard", org="acme")
    run = driver.start()
    run.post_step("first", {"name": "Ada"})
    run.post_step("review", {"confirmed": "on"})

    response = run.get()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == driver.start_url


def test_dynamic_wizard_does_not_complete_before_its_generated_steps(wizard_driver):
    run = wizard_driver("dynamic-wizard").start()

    response = run.post_step("count", {"count": "3"})

    # The tree resolved at the start of this POST had no item steps yet, so
    # completion has to be judged against the tree the submission implies —
    # otherwise the run finishes here and done() fires three steps early.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("item-0")
    assert run.state == [{"step": {"count": "3"}}]


def test_bare_run_url_post_on_a_live_run_redirects_without_storing(routed_run):
    response = routed_run.post({"account_type": "business"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == routed_run.step_url("account_type")
    assert routed_run.state == []


def test_bare_run_url_post_on_a_complete_but_unfinished_run_returns_to_the_run(
    wizard_driver,
):
    run = wizard_driver("escape-advance-final-step-wizard").start()
    run.post_step("newsletter", {"email": "ada@example.com", "subscribe": "on"})

    # Advance deferred done(), so the run is complete with no cursor to point
    # at — a bare-URL POST goes back to the run URL, which finishes it.
    response = run.post({"email": "grace@example.com"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.url


def test_misconfigured_wizard_unknown_run_raises_improperly_configured(client):
    # A session that holds runs, none of them the one about to be requested.
    seed_run(client, "22222222-2222-2222-2222-222222222222", {})

    with pytest.raises(ImproperlyConfigured, match="get_start_url"):
        client.get(
            reverse(
                "misconfigured-wizard-run",
                kwargs={"run_id": "11111111-1111-1111-1111-111111111111"},
            )
        )


def test_completion_tombstones_are_pruned_to_the_storage_cap(client, wizard_driver):
    driver = wizard_driver("pruned-completion-wizard")
    completed = []

    for name in ("Ada", "Grace", "Mary"):
        run = driver.start()
        run.post_step("first", {"name": name})
        completed.append(run.run_id)

    # Storage keeps two tombstones, so the oldest completed run is dropped.
    assert list(stored_runs(client)) == completed[1:]


def test_wizard_configured_storage_class_raises_improperly_configured(client):
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match="WizardViewSet.storage_class"):
        client.get(reverse("wizard-configured-storage"))


# --- Stashing and resurrecting runs ----------------------------------------


def _complete_stashing_wizard(driver, name="Ada", label="Holiday", photo=None):
    run = driver.start()
    run.post_step("first", {"name": name}, follow=True)
    photo_data = {"label": label}
    if photo is not None:
        photo_data["photo"] = photo
    response = run.post_step("photo", photo_data, follow=True)
    return run, response


def test_completing_the_stashing_wizard_stores_a_files_free_payload(
    client, wizard_driver, isolated_media_root
):
    run, response = _complete_stashing_wizard(
        wizard_driver("stashing-wizard"),
        photo=SimpleUploadedFile("holiday.jpg", b"binary"),
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"stashed Ada"
    payload = stored_stash(client, "contact")
    assert payload["label"] == "contact"
    assert payload["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"label": "Holiday"}},
    ]
    assert run.data == {"completed": True}


def test_resurrecting_a_stash_lands_on_a_step_of_a_fresh_prefilled_run(
    client, wizard_driver
):
    driver = wizard_driver("stashing-wizard")
    old_run, _ = _complete_stashing_wizard(driver)

    response = client.get(reverse("stashing-wizard-resurrect"))

    new_run = driver.new_run(old_run)
    assertRedirects(
        response,
        new_run.step_url("first"),
        fetch_redirect_response=False,
    )
    assert new_run.state == [
        {"step": {"name": "Ada"}},
        {"step": {"label": "Holiday"}},
    ]

    landing = client.get(response["Location"])
    assert landing.status_code == HTTPStatus.OK
    assertContains(landing, 'value="Ada"')


def test_editing_a_resurrected_run_fires_done_again(client, wizard_driver):
    driver = wizard_driver("stashing-wizard")
    old_run, _ = _complete_stashing_wizard(driver)

    client.get(reverse("stashing-wizard-resurrect"))
    new_run = driver.new_run(old_run)
    # Every stored answer in a resurrected run validates, so one successful
    # edit walks straight through to completion and fires done() again —
    # wizards wanting an explicit confirm gate keep a review step.
    response = new_run.post_step("first", {"name": "Grace"}, follow=True)

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"stashed Grace"
    # The re-completion overwrote the stash with the edited answers, and the
    # original run's tombstone is untouched.
    payload = stored_stash(client, "contact")
    assert payload["state"][0] == {"step": {"name": "Grace"}}
    assert old_run.data == {"completed": True}


def test_resurrecting_twice_yields_two_independent_runs(client, wizard_driver):
    driver = wizard_driver("stashing-wizard")
    old_run, _ = _complete_stashing_wizard(driver)

    client.get(reverse("stashing-wizard-resurrect"))
    first_run = driver.new_run(old_run)
    client.get(reverse("stashing-wizard-resurrect"))
    second_run = driver.new_run(old_run, first_run)

    assert first_run.run_id != second_run.run_id
    assert first_run.state == second_run.state


def test_resurrecting_without_a_stash_is_gone(client):
    response = client.get(reverse("stashing-wizard-resurrect"))

    assert response.status_code == HTTPStatus.GONE
    assert stored_runs(client) == {}


def test_resurrecting_a_tampered_stash_version_is_gone(client, wizard_driver):
    _complete_stashing_wizard(wizard_driver("stashing-wizard"))
    payload = stored_stash(client, "contact")
    payload["version"] = 99
    seed_stash(client, "contact", payload)

    response = client.get(reverse("stashing-wizard-resurrect"))

    assert response.status_code == HTTPStatus.GONE


def test_a_tampered_stash_answer_is_revalidated_not_trusted(client, wizard_driver):
    """Resurrection replays the walk, so a mangled answer parks the run on
    the offending step with its errors — it can never complete silently."""
    driver = wizard_driver("stashing-wizard")
    old_run, _ = _complete_stashing_wizard(driver)
    payload = stored_stash(client, "contact")
    payload["state"][0]["step"]["name"] = ""
    seed_stash(client, "contact", payload)

    response = client.get(reverse("stashing-wizard-resurrect"))

    new_run = driver.new_run(old_run)
    assertRedirects(
        response,
        new_run.step_url("first"),
        fetch_redirect_response=False,
    )
    landing = client.get(response["Location"])
    assert landing.status_code == HTTPStatus.OK
    assertContains(landing, "This field is required.")


def test_resurrecting_a_required_file_stash_resumes_at_the_photo_step(
    client, wizard_driver, isolated_media_root
):
    driver = wizard_driver("required-photo-stashing-wizard")
    old_run = driver.start()
    old_run.post_step("first", {"name": "Ada"}, follow=True)
    response = old_run.post_step(
        "photo",
        {"photo": SimpleUploadedFile("portrait.jpg", b"binary")},
        follow=True,
    )
    assert response.content == b"stashed with photo"

    response = client.get(reverse("required-photo-stashing-wizard-resurrect"))

    # The stash dropped the upload, so the resurrected run cannot pass the
    # required photo step — it parks there for the user to re-upload.
    new_run = driver.new_run(old_run)
    assertRedirects(
        response,
        new_run.step_url("photo"),
        fetch_redirect_response=False,
    )
    landing = client.get(response["Location"])
    assert landing.status_code == HTTPStatus.OK
    assertContains(landing, 'type="file"')


def _complete_branching_stashing_wizard(driver):
    run = driver.start()
    response = run.post_steps(
        [
            ("account_type", {"account_type": "business"}),
            ("business_name", {"business_name": "Acme"}),
            ("count", {"count": "1"}),
            ("item-0", {"name": "Widget"}),
        ]
    )
    return run, response


def test_branching_stashing_wizard_stashes_nested_entries_without_a_label(
    client, wizard_driver
):
    _, response = _complete_branching_stashing_wizard(
        wizard_driver("branching-stashing-wizard")
    )

    assert response.content == b"stashed sections"
    payload = stored_stash(client, "sections")
    assert "label" not in payload
    assert payload["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        {"step": {"count": "1"}},
        {"expand": [{"step": {"name": "Widget"}}]},
    ]


def test_branching_stashing_wizard_strips_a_legacy_branch_entry(client, wizard_driver):
    """A run whose stored branch entry still uses the legacy bare-list shape
    stashes cleanly — the payload keeps the shape it found."""
    run = wizard_driver("branching-stashing-wizard").start()
    run.seed_state(
        [
            {"step": {"account_type": "business"}},
            {"branch": [{"step": {"business_name": "Acme"}}]},
            {"step": {"count": "1"}},
            {"expand": [{"step": {"name": "Widget"}}]},
        ]
    )

    response = run.get()

    assert response.content == b"stashed sections"
    payload = stored_stash(client, "sections")
    assert payload["state"][1] == {"branch": [{"step": {"business_name": "Acme"}}]}


def test_resurrecting_the_sections_stash_lands_on_the_named_step_and_consumes_it(
    client, wizard_driver
):
    driver = wizard_driver("branching-stashing-wizard")
    old_run, _ = _complete_branching_stashing_wizard(driver)

    response = client.get(reverse("branching-stashing-wizard-resurrect"))

    new_run = driver.new_run(old_run)
    assertRedirects(
        response,
        new_run.step_url("count"),
        fetch_redirect_response=False,
    )
    # The resurrect view pops the stash, so a second reopen finds nothing.
    assert client.get(reverse("branching-stashing-wizard-resurrect")).status_code == (
        HTTPStatus.GONE
    )


def test_stashed_section_keys_lists_completions_and_discard_removes_them(
    client, wizard_driver
):
    assert client.get(reverse("stashed-section-keys")).content == b""

    _complete_branching_stashing_wizard(wizard_driver("branching-stashing-wizard"))
    assert client.get(reverse("stashed-section-keys")).content == b"sections"

    client.get(reverse("discard-sections-stash"))
    assert client.get(reverse("stashed-section-keys")).content == b""


def test_resurrecting_an_empty_stash_completes_on_arrival(client, wizard_driver):
    """A stepless wizard has no step URL to land on, so resurrection falls
    back to the bare run URL — where the walk immediately completes."""
    response = client.get(reverse("resurrect-empty-stash"), follow=True)

    assert response.status_code == HTTPStatus.OK
    run = wizard_driver("empty-wizard").only_run()
    assert response.content == f"completed {run.run_id}".encode()


def test_resurrecting_a_stash_whose_state_is_not_a_list_is_gone(client, wizard_driver):
    _complete_stashing_wizard(wizard_driver("stashing-wizard"))
    payload = stored_stash(client, "contact")
    payload["state"] = "corrupt"
    seed_stash(client, "contact", payload)

    response = client.get(reverse("stashing-wizard-resurrect"))

    assert response.status_code == HTTPStatus.GONE


def test_resurrecting_a_stash_with_the_wrong_label_is_gone(client, wizard_driver):
    _complete_stashing_wizard(wizard_driver("stashing-wizard"))
    payload = stored_stash(client, "contact")
    payload["label"] = "billing"
    seed_stash(client, "contact", payload)

    response = client.get(reverse("stashing-wizard-resurrect"))

    assert response.status_code == HTTPStatus.GONE


def test_a_mounted_wizard_can_be_asked_what_it_is_without_starting_it(rf):
    """`resolve()` is the door for a caller holding a viewset rather than a
    wizard: bind it, read its shape, leave no run behind."""
    from tests.testapp import views

    request = rf.get("/")
    request.session = {}

    bound_wizard = views.BranchingWizardViewSet.resolve(request)

    assert [entry["kind"] for entry in bound_wizard.wizard.outline()] == [
        "step",
        "branch",
        "step",
    ]
    assert request.session == {}


def test_declaring_a_step_the_old_way_says_so_rather_than_routing_nowhere():
    """The upgrade trap: `context={...}` was how a step's context was
    passed up to 0.9, and under keywords it silently becomes a context key
    called "context"."""
    from django.core.exceptions import ImproperlyConfigured

    from gandalf.wizard import Wizard
    from tests.testapp.forms import FirstStepForm

    with pytest.raises(ImproperlyConfigured, match="name='email'"):
        Wizard().step(FirstStepForm, context={"name": "first"})
