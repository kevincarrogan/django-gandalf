"""A hub and spoke task list over HTTP.

A hub lists parallel wizards the user drops in and out of, showing each as
Not started, Incomplete or Complete, and hands out one link per section that
resumes, re-opens or starts it as appropriate.

The load-bearing guarantee here is negative: **no hub link is ever a bare run
URL.** A run whose every stored answer validates completes on a GET, so a hub
row pointing at one would fire `done()` — and its side effects — on a click.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from gandalf.sections import COMPLETE, INCOMPLETE, NOT_STARTED, Section
from gandalf.testing import (
    seed_run,
    seed_section_run,
    stored_runs,
    stored_section_run,
    stored_stash,
    stored_stashes,
)
from tests.testapp.readme_examples import ContactSectionViewSet


HUB_URL = "/readme/hub/"


def _door(section):
    return reverse("readme-hub-section", kwargs={"section": section})


def _statuses(response):
    return {row.key: row.status for row in response.context["sections"]}


def _complete_contact(client):
    """Drive the contact section to its end, leaving a stash behind."""
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    for step, data in [
        ("name", {"name": "Ada"}),
        ("email", {"email": "ada@example.com"}),
        ("review", {}),
    ]:
        client.post(
            reverse(
                "readme-hub-contact-step",
                kwargs={"run_id": run_id, "gandalf_step": step},
            ),
            data,
            follow=True,
        )
    return run_id


# --- the page --------------------------------------------------------------


def test_a_fresh_hub_lists_every_section_as_not_started(client):
    response = client.get(HUB_URL)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/hub.html")
    assert _statuses(response) == {"contact": NOT_STARTED, "address": NOT_STARTED}
    assertContains(response, ">Contact details</a>")
    assertContains(response, 'class="tag tag--not-started">Not started</strong>')


def test_a_section_left_half_answered_reads_as_incomplete(client):
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"name": "Ada"},
        follow=True,
    )

    response = client.get(HUB_URL)

    assert _statuses(response) == {"contact": INCOMPLETE, "address": NOT_STARTED}
    assertContains(response, 'class="tag tag--incomplete">Incomplete</strong>')


def test_a_section_the_user_opened_and_left_untouched_reads_as_not_started(client):
    client.get(_door("contact"), follow=True)

    response = client.get(HUB_URL)

    assert _statuses(response)["contact"] == NOT_STARTED


def test_a_finished_section_reads_as_complete(client):
    _complete_contact(client)

    response = client.get(HUB_URL)

    assert _statuses(response) == {"contact": COMPLETE, "address": NOT_STARTED}
    assertContains(response, 'class="tag tag--complete">Complete</strong>')


def test_finishing_a_section_stashes_its_answers_and_returns_to_the_hub(client):
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"name": "Ada"},
        follow=True,
    )
    client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "email"},
        ),
        {"email": "ada@example.com"},
        follow=True,
    )

    response = client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "review"},
        ),
        {},
    )

    assertRedirects(response, HUB_URL)
    assert stored_stash(client, "contact")["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
        {"step": {}},
    ]
    # The run is finished, so nothing points at it any more.
    assert stored_section_run(client, "contact") is None


def test_sections_progress_independently_of_each_other(client):
    _complete_contact(client)
    client.get(_door("address"), follow=True)
    address_run = stored_section_run(client, "address")
    client.post(
        reverse(
            "readme-hub-address-step",
            kwargs={"run_id": address_run, "gandalf_step": "address"},
        ),
        {"line_one": "1 Main St", "postcode": "SW1A 1AA"},
        follow=True,
    )

    response = client.get(HUB_URL)

    assert _statuses(response) == {"contact": COMPLETE, "address": INCOMPLETE}


# --- the door --------------------------------------------------------------


def test_entering_a_not_started_section_lands_on_its_first_step(client):
    response = client.get(_door("contact"))

    run_id = stored_section_run(client, "contact")
    assertRedirects(
        response,
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
    )


def test_entering_an_incomplete_section_resumes_its_own_run(client):
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"name": "Ada"},
        follow=True,
    )

    response = client.get(_door("contact"))

    assert stored_section_run(client, "contact") == run_id
    assertRedirects(
        response,
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "email"},
        ),
    )


def test_reopening_a_completed_section_seeds_a_new_prefilled_run(client):
    original = _complete_contact(client)

    response = client.get(_door("contact"), follow=True)

    reopened = stored_section_run(client, "contact")
    assert reopened != original
    assert response.status_code == HTTPStatus.OK
    # `reopen_step` lands on the review page, which shows every answer.
    assertTemplateUsed(response, "testapp/summary_wizard.html")
    assertContains(response, "Ada")
    assert stored_stashes(client)["contact"]["state"][0] == {"step": {"name": "Ada"}}


def test_reopening_a_completed_section_lands_on_a_step_not_the_run_url(client):
    """Every answer in a re-opened section validates, so the bare run URL
    would walk straight to completion and fire `done()` again untouched."""
    _complete_contact(client)

    response = client.get(_door("contact"))

    run_id = stored_section_run(client, "contact")
    assertRedirects(
        response,
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "review"},
        ),
        target_status_code=HTTPStatus.OK,
    )


def test_one_edit_in_a_reopened_section_re_stashes_and_returns_to_the_hub(client):
    """Re-opening is edit-and-re-save: every stored answer already validates,
    so the next successful submission walks to the end and fires `done()`
    again. A review step does not gate that — landing the user on it (via
    `reopen_step`) is what gives them the answers to check first."""
    _complete_contact(client)
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")

    response = client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"name": "Grace"},
    )

    assertRedirects(response, HUB_URL)
    assert stored_stash(client, "contact")["state"][0] == {"step": {"name": "Grace"}}
    assert _statuses(client.get(HUB_URL))["contact"] == COMPLETE


def test_confirming_a_reopened_section_without_editing_keeps_it_complete(client):
    _complete_contact(client)
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")

    response = client.post(
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "review"},
        ),
        {},
    )

    assertRedirects(response, HUB_URL)
    assert stored_stash(client, "contact")["state"][0] == {"step": {"name": "Ada"}}


def test_a_completed_section_already_being_edited_resumes_that_edit(client):
    """Resume before reopen: otherwise every click would resurrect a run
    beside the in-flight edit and the user's changes would be unreachable."""
    _complete_contact(client)
    client.get(_door("contact"), follow=True)
    editing = stored_section_run(client, "contact")

    client.get(_door("contact"), follow=True)

    assert stored_section_run(client, "contact") == editing


def test_a_section_whose_run_the_session_has_forgotten_starts_again(client):
    seed_section_run(client, "contact", "00000000-0000-0000-0000-000000000000")

    response = client.get(_door("contact"))

    run_id = stored_section_run(client, "contact")
    assert run_id != "00000000-0000-0000-0000-000000000000"
    assertRedirects(
        response,
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
    )


def test_a_section_pointing_at_a_forgotten_run_reads_as_not_started(client):
    """An expired session or an obliterated run leaves nothing to pick up."""
    seed_section_run(client, "contact", "00000000-0000-0000-0000-000000000000")

    response = client.get(HUB_URL)

    assert _statuses(response)["contact"] == NOT_STARTED


def test_a_section_whose_recorded_run_was_tombstoned_starts_again(client):
    """A completed run is *found*, not missing, so resuming has to ask
    `is_complete` too — sending the user into a tombstone would bounce every
    request back to the start URL with nothing to explain it."""
    tombstoned = "00000000-0000-0000-0000-000000000001"
    seed_run(client, tombstoned, {"completed": True})
    seed_section_run(client, "contact", tombstoned)

    response = client.get(_door("contact"))

    run_id = stored_section_run(client, "contact")
    assert run_id != tombstoned
    assertRedirects(
        response,
        reverse(
            "readme-hub-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
    )


def test_an_unknown_section_key_redirects_back_to_the_hub(client):
    response = client.get(_door("nope"))

    assertRedirects(response, HUB_URL)


# --- the bare-run-URL hazard ------------------------------------------------


def test_a_section_that_advances_out_of_its_final_step_never_yields_a_run_url(
    client,
):
    """`Advance` at a final step persists and redirects out without reaching
    `_finish`, leaving a live run whose every answer validates. Re-entering
    it must still land on a step — a bare run URL here would fire `done()`
    and its side effects on a click.
    """
    hub_url = reverse("scenario-hub")
    door = reverse("scenario-hub-section", kwargs={"section": "advancing"})
    client.get(door, follow=True)
    run_id = stored_section_run(client, "advancing")
    client.post(
        reverse(
            "hub-advancing-section-step",
            kwargs={"run_id": run_id, "gandalf_step": "newsletter"},
        ),
        {"email": "ada@example.com", "subscribe": "on"},
    )

    response = client.get(door)

    # Still a live run — the escape deferred completion rather than firing it.
    assert stored_runs(client)[run_id].get("completed") is None
    assert "advancing" not in stored_stashes(client)
    assertRedirects(
        response,
        reverse(
            "hub-advancing-section-step",
            kwargs={"run_id": run_id, "gandalf_step": "newsletter"},
        ),
    )
    assert client.get(hub_url).status_code == HTTPStatus.OK


@pytest.mark.parametrize("section", ["plain", "advancing"])
def test_no_hub_link_is_ever_a_bare_run_url(client, section):
    """The invariant, asserted directly: whatever state a section is in, its
    door redirects to a step URL."""
    door = reverse("scenario-hub-section", kwargs={"section": section})

    response = client.get(door)

    run_id = stored_section_run(client, section)
    assert response["Location"] != reverse(
        f"hub-{section}-section-run", kwargs={"run_id": run_id}
    )
    assert response["Location"].rstrip("/").rsplit("/", 1)[-1] in {
        "first",
        "newsletter",
    }


# --- mount-prefix kwargs ----------------------------------------------------


def test_a_hub_forwards_its_mount_prefix_into_every_url_it_builds(client):
    response = client.get("/org/acme/hub/")

    assert response.status_code == HTTPStatus.OK
    (row,) = response.context["sections"]
    assert row.url == "/org/acme/hub/details/"


def test_entering_a_prefixed_section_keeps_the_prefix(client):
    response = client.get("/org/acme/hub/details/")

    run_id = stored_section_run(client, "details")
    assertRedirects(response, f"/org/acme/hub-details/{run_id}/first/")


# --- rows a template can branch on ------------------------------------------


def test_a_row_reports_its_status_as_a_boolean_per_state(client):
    """What a template branches on, rather than comparing status strings."""
    seed_section_run(client, "address", "00000000-0000-0000-0000-000000000000")
    seed_run(
        client,
        "00000000-0000-0000-0000-000000000000",
        {"state": [{"step": {"line_one": "1 Main St", "postcode": "SW1A 1AA"}}]},
    )
    _complete_contact(client)

    rows = {row.key: row for row in client.get(HUB_URL).context["sections"]}

    assert (rows["contact"].is_complete, rows["contact"].is_incomplete) == (True, False)
    assert rows["address"].is_incomplete
    assert not rows["address"].is_not_started


# --- misconfiguration --------------------------------------------------------


def _hub_view(**attributes):
    from gandalf.sections import HubView

    return type("_Hub", (HubView,), {"template_name": "testapp/hub.html", **attributes})


def _dispatch(rf, client, view, path="/readme/hub/", **kwargs):
    """Dispatch a hand-built hub against the client's session, so a test can
    arrange state through the real flow and then point a misconfigured hub
    at it."""
    request = rf.get(path)
    request.session = client.session
    return view.as_view()(request, **kwargs)


def test_a_hub_with_no_sections_declared_is_misconfigured(rf, client):
    view = _hub_view(url_name="readme-hub", section_url_name="readme-hub-section")

    with pytest.raises(ImproperlyConfigured, match="sections"):
        _dispatch(rf, client, view)


def test_a_hub_with_duplicate_section_keys_is_misconfigured(rf, client):
    view = _hub_view(
        url_name="readme-hub",
        section_url_name="readme-hub-section",
        sections=[
            Section("contact", ContactSectionViewSet),
            Section("contact", ContactSectionViewSet),
        ],
    )

    with pytest.raises(ImproperlyConfigured, match="unique"):
        _dispatch(rf, client, view)


def test_a_section_key_that_drifts_from_its_viewsets_own_key_is_misconfigured(
    rf, client
):
    """The hub would read a stash key the section never writes, so the
    section could complete and still render as not started, forever."""
    view = _hub_view(
        url_name="readme-hub",
        section_url_name="readme-hub-section",
        sections=[Section("billing", ContactSectionViewSet)],
    )

    with pytest.raises(ImproperlyConfigured, match="section_key"):
        _dispatch(rf, client, view)


def test_a_hub_without_a_url_name_cannot_publish_urls():
    from gandalf.sections import HubView

    class _Nameless(HubView):
        pass

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _Nameless.urls()


def test_a_hub_without_a_section_url_name_is_misconfigured(rf, client):
    view = _hub_view(
        url_name="readme-hub",
        sections=[Section("contact", ContactSectionViewSet)],
    )

    with pytest.raises(ImproperlyConfigured, match="section_url_name"):
        _dispatch(rf, client, view)


def test_a_hub_without_a_url_name_cannot_reverse_itself(rf, client):
    view = _hub_view(
        section_url_name="readme-hub-section",
        sections=[Section("contact", ContactSectionViewSet)],
    )

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _dispatch(rf, client, view, path="/readme/hub/nope/", section="nope")


def test_a_section_without_a_key_cannot_register_as_finished(rf, client):
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Keyless(ContactSectionViewSet):
        section_key = None

    request = rf.get("/readme/hub-contact/")
    request.session = client.session
    view = _Keyless()
    view.setup(request)
    bound_wizard = BoundWizard(request, SessionStorage(request))
    bound_wizard.initialise()

    with pytest.raises(ImproperlyConfigured, match="section_key"):
        view.done(bound_wizard)


def test_a_dynamic_section_that_derives_no_key_is_misconfigured(rf, client):
    """`SectionMixin`'s usual advice — set the class attribute — is wrong for
    a section that deliberately has none, so it is told something else."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Undecided(ContactSectionViewSet):
        section_key = None
        dynamic_section_key = True

    request = rf.get("/readme/hub-contact/")
    request.session = client.session
    view = _Undecided()
    view.setup(request)
    bound_wizard = BoundWizard(request, SessionStorage(request))
    bound_wizard.initialise()

    with pytest.raises(ImproperlyConfigured, match="get_section_key"):
        view.done(bound_wizard)


def test_a_row_that_is_not_a_wizard_must_say_where_and_how_far(rf, client):
    """A section with no viewset answers for itself. Without a `url_name` the
    hub builds a door it cannot open; without a `status` it derives one from a
    stash key nothing writes."""
    view = _hub_view(
        url_name="readme-hub",
        section_url_name="readme-hub-section",
        sections=[Section("elsewhere", url_name="readme-hub")],
    )

    with pytest.raises(ImproperlyConfigured, match="url_name and status"):
        _dispatch(rf, client, view)


def test_a_row_that_is_not_a_wizard_links_past_the_door_and_answers_for_itself(
    rf, client
):
    """A collection page, a payment redirect, a page in another app: there is
    no run for the door to walk, so the row addresses it directly."""
    view = _hub_view(
        url_name="readme-hub",
        section_url_name="readme-hub-section",
        sections=[
            Section(
                "elsewhere",
                title="Elsewhere",
                url_name="readme-hub",
                status=lambda request: COMPLETE,
            )
        ],
    )

    response = _dispatch(rf, client, view)

    (row,) = response.context_data["sections"]
    assert (row.title, row.status, row.url) == ("Elsewhere", COMPLETE, HUB_URL)


def test_the_door_refuses_a_row_it_cannot_walk(rf, client):
    """Rows never point there, so arriving is a hand-typed or stale URL."""
    view = _hub_view(
        url_name="readme-hub",
        section_url_name="readme-hub-section",
        sections=[
            Section("elsewhere", url_name="readme-hub", status=lambda r: COMPLETE)
        ],
    )

    response = _dispatch(
        rf, client, view, path="/readme/hub/elsewhere/", section="elsewhere"
    )

    # `assertRedirects` needs a client-fetched response; this one is built
    # from a `RequestFactory`, so the redirect is checked directly.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == HUB_URL


def test_a_section_without_a_hub_url_name_cannot_send_the_user_back(rf):
    class _Homeless(ContactSectionViewSet):
        hub_url_name = None

    view = _Homeless()
    view.setup(rf.get("/readme/hub-contact/"))

    with pytest.raises(ImproperlyConfigured, match="hub_url_name"):
        view.get_hub_url()


def test_a_section_can_bump_its_stash_label_without_renaming_itself(rf, client):
    """The guard rail for a deploy that reshapes a section: a payload from
    the old shape is refused at the door rather than walked into a tree it
    no longer matches."""
    from gandalf.runtime import InvalidStash

    _complete_contact(client)
    view = _hub_view(
        url_name="readme-hub",
        section_url_name="readme-hub-section",
        sections=[
            Section("contact", ContactSectionViewSet, label="contact-v2"),
        ],
    )

    with pytest.raises(InvalidStash):
        _dispatch(rf, client, view, path="/readme/hub/contact/", section="contact")


def test_stash_unusable_can_be_overridden_to_start_the_section_over(rf, client):
    """The other half of the reshaped-section story: a hub that would rather
    lose the old answers than 500."""
    _complete_contact(client)

    class _Forgiving(_hub_view(url_name="readme-hub")):
        section_url_name = "readme-hub-section"
        sections = [Section("contact", ContactSectionViewSet, label="contact-v2")]

        def stash_unusable(self, section, error):
            self.get_section_store().delete_stash(section.key)
            return self.enter(section)

    request = rf.get("/readme/hub/contact/")
    request.session = client.session
    response = _Forgiving.as_view()(request, section="contact")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].endswith("/name/")
    assert "contact" not in request.session["gandalf_stashes"]


def test_a_section_without_a_title_is_named_from_its_key(client):
    response = client.get(reverse("scenario-hub"))

    titles = {row.key: row.title for row in response.context["sections"]}
    assert titles == {"plain": "Plain", "advancing": "Advancing"}


def test_a_section_stamps_its_declared_label_into_the_stash(rf, client):
    """`section_label` is the *shape's* identity — bumped when a deploy
    reshapes the wizard, without renaming the section."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Reshaped(ContactSectionViewSet):
        section_label = "contact-v2"

    request = rf.get("/readme/hub-contact/")
    request.session = client.session
    view = _Reshaped()
    view.setup(request)
    bound_wizard = BoundWizard(request, SessionStorage(request))
    bound_wizard.initialise()

    view.done(bound_wizard)

    assert request.session["gandalf_stashes"]["contact"]["label"] == "contact-v2"


def test_a_hubs_declaration_is_vetted_once_per_request(rf, client):
    """Both halves of the hub ask for the sections — the rows and the door —
    and the checks are properties of the declaration, not of either use."""
    calls = []

    class _Counting(_hub_view(url_name="readme-hub")):
        section_url_name = "readme-hub-section"

        def get_sections(self):
            calls.append(1)
            return [Section("contact", ContactSectionViewSet)]

    request = rf.get(HUB_URL)
    request.session = client.session
    page = _Counting()
    page.setup(request)

    page.get_section_rows()
    page.get_section("contact")

    assert len(calls) == 1
