"""Drive every README example through the Django test client.

Each example in ``README.md`` has a runnable counterpart in
``tests/testapp/readme_examples.py`` mounted under ``readme/``. These tests
exercise those counterparts end to end, so a README snippet that stops working
(or a "Try it live" link that stops resolving) fails CI.
"""

import tempfile
from http import HTTPStatus

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
import pytest
from pytest_django.asserts import assertContains, assertRedirects


def start_url(name, url_kwargs=None):
    return reverse(name, kwargs=url_kwargs or None)


def run_url(name, run_id, url_kwargs=None):
    return reverse(f"{name}-run", kwargs={**(url_kwargs or {}), "run_id": run_id})


def step_url(name, run_id, step, url_kwargs=None):
    return f"{run_url(name, run_id, url_kwargs)}{step}/"


def start_run(client, name, url_kwargs=None):
    """GET the start URL and return the freshly created run id."""
    client.get(start_url(name, url_kwargs))
    runs = client.session["gandalf_runs"]
    assert len(runs) == 1
    return next(iter(runs))


def drive(client, name, steps, url_kwargs=None):
    """Run a wizard to completion, POSTing ``steps`` as ``(step, data)`` pairs.

    Returns the final (followed) response.
    """
    run_id = start_run(client, name, url_kwargs)
    response = None
    for step, data in steps:
        response = client.post(
            step_url(name, run_id, step, url_kwargs), data=data, follow=True
        )
    return response, run_id


# --- Every start URL reverses (the "Try it live" links resolve) -------------


@pytest.mark.parametrize(
    "name, url_kwargs",
    [
        ("readme-signup", None),
        ("readme-branching", None),
        ("readme-onboarding", {"plan": "solo"}),
        ("readme-expand", None),
        ("readme-file-upload", None),
        ("readme-escape", None),
        ("readme-editing", None),
    ],
)
def test_readme_example_start_url_is_reachable(client, name, url_kwargs):
    response = client.get(start_url(name, url_kwargs))

    # The start URL creates a run and redirects to it, so the link is live.
    assert response.status_code == HTTPStatus.FOUND


# --- Quickstart: linear signup ----------------------------------------------


def test_signup_wizard_collects_and_merges_both_steps(client):
    response, _ = drive(
        client,
        "readme-signup",
        [
            ("name", {"name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
        ],
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Signed up Ada <ada@example.com>"


# --- Branching --------------------------------------------------------------


def test_branching_wizard_takes_business_arm(client):
    response, _ = drive(
        client,
        "readme-branching",
        [
            ("account_type", {"account_type": "business"}),
            ("business", {"business_name": "Acme"}),
            ("review", {"confirmed": "on"}),
        ],
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Acme"


def test_branching_wizard_takes_personal_arm(client):
    response, _ = drive(
        client,
        "readme-branching",
        [
            ("account_type", {"account_type": "personal"}),
            ("personal", {"preferred_name": "Ada"}),
            ("review", {"confirmed": "on"}),
        ],
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Ada"


# --- Dynamic wizards: get_wizard() ------------------------------------------


def test_onboarding_solo_plan_skips_the_company_step(client):
    response, _ = drive(
        client,
        "readme-onboarding",
        [
            ("name", {"name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
        ],
        url_kwargs={"plan": "solo"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Ada on the solo plan"


def test_onboarding_team_plan_inserts_the_company_step(client):
    response, _ = drive(
        client,
        "readme-onboarding",
        [
            ("name", {"name": "Ada"}),
            ("company", {"business_name": "Acme"}),
            ("email", {"email": "ada@example.com"}),
        ],
        url_kwargs={"plan": "team"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Ada on the team plan"


# --- .expand() --------------------------------------------------------------


def test_expand_wizard_grows_item_steps_mid_walk(client):
    response, _ = drive(
        client,
        "readme-expand",
        [
            ("count", {"count": "2"}),
            ("item-0", {"name": "x"}),
            ("item-1", {"name": "y"}),
            ("review", {"confirmed": "on"}),
        ],
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Collected x, y"


# --- File uploads -----------------------------------------------------------


def test_file_upload_wizard_stores_and_reports_the_upload(client):
    with tempfile.TemporaryDirectory() as media_root:
        with override_settings(MEDIA_ROOT=media_root):
            run_id = start_run(client, "readme-file-upload")
            client.post(
                step_url("readme-file-upload", run_id, "photo"),
                data={
                    "photo": SimpleUploadedFile(
                        "avatar.png", b"bytes", content_type="image/png"
                    )
                },
                follow=True,
            )
            response = client.post(
                step_url("readme-file-upload", run_id, "name"),
                data={"name": "Ada"},
                follow=True,
            )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Uploaded avatar.png"


# --- Escaping the wizard ----------------------------------------------------


def test_escape_wizard_parks_a_known_email(client):
    run_id = start_run(client, "readme-escape")

    response = client.post(
        step_url("readme-escape", run_id, "email"),
        data={"email": "existing@example.com"},
    )

    # Park redirects the user out (to the landing page) and does not store the
    # answer, so the run keeps no stored steps and stays on the email step.
    assertRedirects(
        response, reverse("escape-landing"), fetch_redirect_response=False
    )
    assert client.session["gandalf_runs"][run_id].get("state", []) == []


def test_escape_wizard_continues_for_a_new_email(client):
    response, run_id = drive(
        client,
        "readme-escape",
        [
            ("email", {"email": "new@example.com"}),
            ("name", {"name": "Ada"}),
        ],
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == f"Signed up {run_id}".encode()


# --- Back-navigation / editing ----------------------------------------------


def test_editing_wizard_renders_a_completed_step_prefilled(client):
    run_id = start_run(client, "readme-editing")
    client.post(
        step_url("readme-editing", run_id, "account_type"),
        data={"account_type": "personal"},
        follow=True,
    )

    # A completed step's own URL renders it again, pre-filled — this is the
    # edit affordance the review template links to.
    response = client.get(
        step_url("readme-editing", run_id, "account_type"), follow=True
    )

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'name="account_type"')


# --- Dormant memory: flipping a branch and back -----------------------------


def test_flip_flop_wizard_restores_a_dormant_arm_answer(client):
    name = "readme-flip-flop"
    run_id = start_run(client, name)

    # Business arm: answer the account type and the company name.
    client.post(
        step_url(name, run_id, "account_type"),
        data={"account_type": "business"},
        follow=True,
    )
    client.post(
        step_url(name, run_id, "business_name"),
        data={"business_name": "Acme"},
        follow=True,
    )

    # Edit the account type to personal — the business arm goes dormant.
    client.post(
        step_url(name, run_id, "account_type"),
        data={"account_type": "personal"},
        follow=True,
    )
    # Flip back to business — the dormant "Acme" is restored, not re-asked.
    client.post(
        step_url(name, run_id, "account_type"),
        data={"account_type": "business"},
        follow=True,
    )

    # The company step is satisfied again from dormant memory: GETting it shows
    # Acme pre-filled, and completing the run reports it without re-entry.
    prefilled = client.get(step_url(name, run_id, "business_name"), follow=True)
    assertContains(prefilled, "Acme")

    response = client.post(
        step_url(name, run_id, "review"), data={"confirmed": "on"}, follow=True
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Onboarded Acme"
