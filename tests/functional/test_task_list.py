"""A task list over HTTP.

A task list page lists parallel wizards the user drops in and out of, showing each as
Not started, Incomplete or Complete, and hands out one link per section that
resumes, re-opens or starts it as appropriate.

The load-bearing guarantee here is negative: **no link on the page is ever a bare run
URL.** A run whose every stored answer validates completes on a GET, so a page
row pointing at one would fire `done()` — and its side effects — on a click.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from gandalf.context import WizardContext
from gandalf.driver import RunDriver
from gandalf.tasklists import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    EntryUnavailable,
    Link,
    Section,
    TaskList,
    TaskListViewSet,
)
from gandalf.viewsets import DoorRefused
from gandalf.testing import (
    seed_run,
    seed_section_run,
    stored_runs,
    stored_section_run,
    stored_section_stash,
    stored_section_stashes,
)
from tests.testapp.readme.ch12_task_list import GrantApplicationViewSet, contact
from tests.testapp.readme.ch14_gated import GatedViewSet as ReadmeGatedViewSet
from tests.testapp.views import GatedViewSet


ContactSectionViewSet = GrantApplicationViewSet.viewset_for("contact")


HUB_URL = "/readme/task-list/"


def _door(section):
    return reverse("readme-task-list-entry", kwargs={"entry": section})


def _statuses(response):
    return {row.key: row.status for row in response.context["task_list"].rows}


def _complete_contact(client):
    """Drive the contact section to its end, leaving a stash behind."""
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    for step, data in [
        ("name", {"full_name": "Ada"}),
        ("email", {"email": "ada@example.com"}),
        ("review", {}),
    ]:
        client.post(
            reverse(
                "readme-task-list-contact-step",
                kwargs={"run_id": run_id, "gandalf_step": step},
            ),
            data,
            follow=True,
        )
    return run_id


def _complete_address(client):
    """Drive the address section to its end, leaving a stash behind."""
    client.get(_door("address"), follow=True)
    run_id = stored_section_run(client, "address")
    answers = {"line_1": "1 Main St", "town": "Ely", "postcode": "CB1 1AA"}
    for step, data in [("address", answers), ("review", {})]:
        client.post(
            reverse(
                "readme-task-list-address-step",
                kwargs={"run_id": run_id, "gandalf_step": step},
            ),
            data,
            follow=True,
        )
    return run_id


# --- the page --------------------------------------------------------------


def test_a_fresh_page_lists_every_section_as_not_started(client):
    response = client.get(HUB_URL)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/readme_task_list.html")
    assert _statuses(response) == {"contact": NOT_STARTED, "address": NOT_STARTED}
    assertContains(response, ">Contact details</a>")
    assertContains(response, 'class="tag tag--not-started">Not started</strong>')


def test_a_section_left_half_answered_reads_as_incomplete(client):
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"full_name": "Ada"},
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


# --- a section the user cannot start yet ------------------------------------


GATED_URL = "/gated-task-list/"


def _gated_statuses(client):
    return {
        row.key: row.status for row in client.get(GATED_URL).context["task_list"].rows
    }


def _complete_gated_first(client):
    client.get("/gated-task-list/first/", follow=True)
    run_id = stored_section_run(client, "first")
    client.post(
        reverse(
            "gated-task-list-first-step",
            kwargs={"run_id": run_id, "gandalf_step": "first"},
        ),
        {"name": "Ada"},
        follow=True,
    )


def test_a_section_waiting_on_another_renders_as_cannot_start_yet(client):
    response = client.get(GATED_URL)

    assert _gated_statuses(client) == {"first": NOT_STARTED, "second": BLOCKED}
    assertContains(response, 'class="tag tag--blocked">Cannot start yet</strong>')

    page = response.context["task_list"]
    assert (page.blocked, page.remaining) == (1, 2)
    assert page.is_not_started


def test_a_locked_sections_door_sends_the_user_back_to_the_task_list(client):
    """The row rendered a link. A stale link or a typed URL reaches the door
    regardless, and it must not start the run."""
    response = client.get("/gated-task-list/second/")

    assertRedirects(response, GATED_URL)
    assert stored_section_run(client, "second") is None


def test_a_locked_sections_door_refuses_a_driver_too(client):
    """The gate was on the browser's door alone. A driver comes through
    `for_context()` and never dispatches, so it asked none of the questions
    the page asks — and opened a section whose row reads *Cannot start
    yet*, then accepted answers into it.

    Two doors, one set of rules. Which one a caller came through is not a
    thing the rules should turn on.
    """
    context = WizardContext(session=client.session)

    with pytest.raises(DoorRefused) as refusal:
        RunDriver.begin(GatedViewSet.viewset_for("second"), context=context)

    assert refusal.value.reason == EntryUnavailable.BLOCKED
    assert stored_section_run(client, "second") is None


def test_a_hidden_sections_door_refuses_a_driver(client):
    """A hidden entry is *gone* for the person — not listed, not counted,
    its door refusing a stale link. A driver could open it regardless,
    which is the same refusal for a stronger reason: hidden says this
    section is not part of the journey at all."""
    context = WizardContext(session=client.session)

    with pytest.raises(DoorRefused) as refusal:
        RunDriver.begin(
            ReadmeGatedViewSet.viewset_for("match-funding"), context=context
        )

    assert refusal.value.reason == EntryUnavailable.HIDDEN


def test_a_submitted_journey_cannot_be_answered_by_a_driver(client, rf):
    """`JourneyScoped.dispatch` buys the guarantee that a submitted journey
    can never be answered again, one store read per request. A driver makes
    no request, so it made no such read — and a section finished through
    one wrote its stash into the tombstone, which is the exact thing the
    guarantee exists to prevent."""
    session = client.session
    request = rf.get(HUB_URL)
    request.session = session
    page = GrantApplicationViewSet()
    page.setup(request)
    page.get_journey_store().complete()

    context = WizardContext(session=session)
    with pytest.raises(DoorRefused) as refusal:
        RunDriver.begin(GrantApplicationViewSet.viewset_for("contact"), context=context)

    assert refusal.value.reason == EntryUnavailable.SUBMITTED
    assert not page.get_journey_store().has_stash("contact")


def test_a_driver_may_still_open_a_section_the_page_would_open(client):
    """The gate is the page's rules, not a rule against drivers."""
    context = WizardContext(session=client.session)

    driver = RunDriver.begin(GatedViewSet.viewset_for("first"), context=context)

    assert driver.describe().step == "first"


def test_a_section_unlocks_once_its_prerequisite_is_finished(client):
    _complete_gated_first(client)

    assert _gated_statuses(client) == {"first": COMPLETE, "second": NOT_STARTED}

    response = client.get("/gated-task-list/second/", follow=True)

    assert response.status_code == HTTPStatus.OK
    assert stored_section_run(client, "second") is not None


def test_a_fresh_page_reports_the_whole_page_as_not_started(client):
    page = client.get(HUB_URL).context["task_list"]

    assert (page.count, page.completed, page.remaining) == (2, 0, 2)
    assert page.is_not_started


def test_one_finished_section_makes_the_whole_page_incomplete(client):
    _complete_contact(client)

    page = client.get(HUB_URL).context["task_list"]

    assert (page.count, page.completed, page.remaining) == (2, 1, 1)
    assert page.is_incomplete
    assertContains(client.get(HUB_URL), "You have completed 1 of 2 sections.")


def test_a_page_is_complete_only_once_every_section_is(client):
    _complete_contact(client)
    _complete_address(client)

    page = client.get(HUB_URL).context["task_list"]

    assert (page.completed, page.remaining) == (2, 0)
    assert page.is_complete
    assert str(page.status_label) == "Complete"


def test_finishing_a_section_stashes_its_answers_and_returns_to_the_page(client):
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"full_name": "Ada"},
        follow=True,
    )
    client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "email"},
        ),
        {"email": "ada@example.com"},
        follow=True,
    )

    response = client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "review"},
        ),
        {},
    )

    assertRedirects(response, HUB_URL)
    assert stored_section_stash(client, "contact")["state"] == [
        {"step": {"full_name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
        {"step": {}},
    ]
    # The run is finished, so nothing points at it any more.
    assert stored_section_run(client, "contact") is None


def test_a_csrf_token_an_earlier_version_stored_does_not_reach_the_stash(client):
    """A stash is the one thing that carries answers out of the session they
    were given to, and the page's lives on past the run. New answers never carry
    a token — the viewset drops it as the POST is read — but a run already in
    flight when that landed does, so the way out is swept too."""
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    seed_run(
        client,
        run_id,
        {"state": [{"step": {"full_name": "Ada", "csrfmiddlewaretoken": "sekrit"}}]},
    )

    for step, data in [("email", {"email": "ada@example.com"}), ("review", {})]:
        client.post(
            reverse(
                "readme-task-list-contact-step",
                kwargs={"run_id": run_id, "gandalf_step": step},
            ),
            data,
            follow=True,
        )

    assert stored_section_stash(client, "contact")["state"][0] == {
        "step": {"full_name": "Ada"}
    }


def test_sections_progress_independently_of_each_other(client):
    _complete_contact(client)
    client.get(_door("address"), follow=True)
    address_run = stored_section_run(client, "address")
    client.post(
        reverse(
            "readme-task-list-address-step",
            kwargs={"run_id": address_run, "gandalf_step": "address"},
        ),
        {"line_1": "1 Main St", "town": "Ely", "postcode": "SW1A 1AA"},
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
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
    )


def test_entering_an_incomplete_section_resumes_its_own_run(client):
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")
    client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"full_name": "Ada"},
        follow=True,
    )

    response = client.get(_door("contact"))

    assert stored_section_run(client, "contact") == run_id
    assertRedirects(
        response,
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "email"},
        ),
    )


def test_reopening_a_completed_section_seeds_a_new_prefilled_run(client):
    original = _complete_contact(client)

    response = client.get(_door("contact"), follow=True)

    reopened = stored_section_run(client, "contact")
    assert reopened != original
    assert response.status_code == HTTPStatus.OK
    # `reopen_at` lands on the review page, which shows every answer.
    assertTemplateUsed(response, "testapp/summary_wizard.html")
    assertContains(response, "Ada")
    assert stored_section_stashes(client)["contact"]["state"][0] == {
        "step": {"full_name": "Ada"}
    }


def test_reopening_a_completed_section_lands_on_a_step_not_the_run_url(client):
    """Every answer in a re-opened section validates, so the bare run URL
    would walk straight to completion and fire `done()` again untouched."""
    _complete_contact(client)

    response = client.get(_door("contact"))

    run_id = stored_section_run(client, "contact")
    assertRedirects(
        response,
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "review"},
        ),
        target_status_code=HTTPStatus.OK,
    )


def test_one_edit_in_a_reopened_section_re_stashes_and_returns_to_the_page(client):
    """Re-opening is edit-and-re-save: every stored answer already validates,
    so the next successful submission walks to the end and fires `done()`
    again. A review step does not gate that — landing the user on it (via
    `reopen_at`) is what gives them the answers to check first."""
    _complete_contact(client)
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")

    response = client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
        {"full_name": "Grace"},
    )

    assertRedirects(response, HUB_URL)
    assert stored_section_stash(client, "contact")["state"][0] == {
        "step": {"full_name": "Grace"}
    }
    assert _statuses(client.get(HUB_URL))["contact"] == COMPLETE


def test_confirming_a_reopened_section_without_editing_keeps_it_complete(client):
    _complete_contact(client)
    client.get(_door("contact"), follow=True)
    run_id = stored_section_run(client, "contact")

    response = client.post(
        reverse(
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "review"},
        ),
        {},
    )

    assertRedirects(response, HUB_URL)
    assert stored_section_stash(client, "contact")["state"][0] == {
        "step": {"full_name": "Ada"}
    }


def test_a_completed_section_already_being_edited_resumes_that_edit(client):
    """Resume before reopen: otherwise every click would re-open a run
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
            "readme-task-list-contact-step",
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
            "readme-task-list-contact-step",
            kwargs={"run_id": run_id, "gandalf_step": "name"},
        ),
    )


def test_an_unknown_key_redirects_back_to_the_page(client):
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
    page_url = reverse("scenario-task-list")
    door = reverse("scenario-task-list-entry", kwargs={"entry": "advancing"})
    client.get(door, follow=True)
    run_id = stored_section_run(client, "advancing")
    client.post(
        reverse(
            "scenario-task-list-advancing-step",
            kwargs={"run_id": run_id, "gandalf_step": "newsletter"},
        ),
        {"email": "ada@example.com", "subscribe": "on"},
    )

    response = client.get(door)

    # Still a live run — the escape deferred completion rather than firing it.
    assert stored_runs(client)[run_id].get("completed") is None
    assert "advancing" not in stored_section_stashes(client)
    assertRedirects(
        response,
        reverse(
            "scenario-task-list-advancing-step",
            kwargs={"run_id": run_id, "gandalf_step": "newsletter"},
        ),
    )
    assert client.get(page_url).status_code == HTTPStatus.OK


@pytest.mark.parametrize("section", ["plain", "advancing"])
def test_no_page_link_is_ever_a_bare_run_url(client, section):
    """The invariant, asserted directly: whatever state a section is in, its
    door redirects to a step URL."""
    door = reverse("scenario-task-list-entry", kwargs={"entry": section})

    response = client.get(door)

    run_id = stored_section_run(client, section)
    assert response["Location"] != reverse(
        f"scenario-task-list-{section}-run", kwargs={"run_id": run_id}
    )
    assert response["Location"].rstrip("/").rsplit("/", 1)[-1] in {
        "first",
        "newsletter",
    }


# --- mount-prefix kwargs ----------------------------------------------------


def test_a_page_forwards_its_mount_prefix_into_every_url_it_builds(client):
    """Every section is mounted beneath the page, so the slug the request came
    in through reaches every URL the page builds without being declared."""
    response = client.get("/org/acme/task-list/")

    assert response.status_code == HTTPStatus.OK
    rows = {row.key: row for row in response.context["task_list"].rows}
    assert rows["details"].url == "/org/acme/task-list/details/"
    assert (rows["org_guests"].url, rows["org_guests"].status) == (
        "/org/acme/task-list/org_guests/",
        NOT_STARTED,
    )
    # An add-another's segment under the page is its own page, not a door.
    assert client.get("/org/acme/task-list/org_guests/").status_code == HTTPStatus.OK


def test_entering_a_prefixed_section_keeps_the_prefix(client):
    response = client.get("/org/acme/task-list/details/")

    run_id = stored_section_run(client, "details")
    assertRedirects(response, f"/org/acme/task-list/details/{run_id}/first/")


# --- rows a template can branch on ------------------------------------------


def test_a_row_reports_its_status_as_a_boolean_per_state(client):
    """What a template branches on, rather than comparing status strings."""
    seed_section_run(client, "address", "00000000-0000-0000-0000-000000000000")
    seed_run(
        client,
        "00000000-0000-0000-0000-000000000000",
        {
            "state": [
                {"step": {"line_1": "1 Main St", "town": "Ely", "postcode": "SW1A 1AA"}}
            ]
        },
    )
    _complete_contact(client)

    rows = {row.key: row for row in client.get(HUB_URL).context["task_list"].rows}

    assert (rows["contact"].is_complete, rows["contact"].is_incomplete) == (True, False)
    assert rows["address"].is_incomplete
    assert not rows["address"].is_not_started


# --- misconfiguration --------------------------------------------------------


def _list(**entries):
    return type("_List", (TaskList,), entries)


def _view(task_list=None, **attributes):
    return type(
        "_ViewSet",
        (TaskListViewSet,),
        {
            "template_name": "testapp/task_list.html",
            "section_template_name": "testapp/linear_wizard.html",
            "task_list": task_list,
            **attributes,
        },
    )


def _dispatch(rf, client, view, path="/readme/task-list/", **kwargs):
    """Dispatch a hand-built page against the client's session, so a test
    can arrange state through the real flow and then point a misconfigured
    page at it."""
    request = rf.get(path)
    request.session = client.session
    return view.as_view()(request, **kwargs)


def test_a_page_with_no_task_list_is_misconfigured(rf, client):
    view = _view(url_name="readme-task-list")

    with pytest.raises(ImproperlyConfigured, match="task_list"):
        _dispatch(rf, client, view)


def test_a_page_without_a_url_name_cannot_publish_urls():
    view = _view(_list(contact=Section(contact)))

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        view.urls()


def test_a_page_without_a_url_name_cannot_reverse_itself(rf, client):
    view = _view(_list(contact=Section(contact)))

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _dispatch(rf, client, view, path="/readme/task-list/nope/", entry="nope")


def test_a_section_without_a_key_cannot_register_as_finished(rf, client):
    from gandalf.runtime import Run
    from gandalf.storage import SessionStorage

    class _Keyless(ContactSectionViewSet):
        key = None

    request = rf.get("/readme/task-list/contact/")
    request.session = client.session
    view = _Keyless()
    view.setup(request)
    context = WizardContext.from_request(request)
    run = Run(context, SessionStorage(context))
    run.initialise()

    with pytest.raises(ImproperlyConfigured, match="key"):
        view.finish(run)


def test_a_groups_page_must_list_a_task_list():
    from gandalf.tasklists import Group, TaskList, TaskListViewSet

    class _Pageless(TaskListViewSet):
        template_name = "testapp/nested_task_list.html"

    class _Listed(TaskList):
        inner = Group(_Pageless)

    with pytest.raises(ImproperlyConfigured, match="no task list to be a group of"):
        type(
            "_Root", (TaskListViewSet,), {"url_name": "pageless", "task_list": _Listed}
        )


def test_a_link_must_say_how_far_it_has_got():
    """An entry with no viewset answers for itself: without a `status` the
    page would derive one from a stash key nothing writes."""
    with pytest.raises(ImproperlyConfigured, match="status"):
        Link("readme-task-list")


def test_a_link_links_past_the_door_and_answers_for_itself(rf, client):
    """A payment redirect, a page in another app: there is no run for the
    door to walk, so the row addresses it directly."""
    view = _view(
        _list(
            elsewhere=Link(
                "readme-task-list",
                title="Elsewhere",
                status=lambda request, kwargs: COMPLETE,
            )
        ),
        url_name="readme-task-list",
    )

    response = _dispatch(rf, client, view)

    (row,) = response.context_data["task_list"].rows
    assert (row.title, row.status, row.url) == ("Elsewhere", COMPLETE, HUB_URL)


def test_the_door_refuses_a_row_it_cannot_walk(rf, client):
    """Rows never point there, so arriving is a hand-typed or stale URL."""
    view = _view(
        _list(elsewhere=Link("readme-task-list", status=lambda r, k: COMPLETE)),
        url_name="readme-task-list",
    )

    response = _dispatch(
        rf, client, view, path="/readme/task-list/elsewhere/", entry="elsewhere"
    )

    # `assertRedirects` needs a client-fetched response; this one is built
    # from a `RequestFactory`, so the redirect is checked directly.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == HUB_URL


def test_a_section_without_a_page_to_return_to_cannot_send_the_user_back(rf):
    class _Homeless(ContactSectionViewSet):
        task_list_url_name = None

    view = _Homeless()
    view.setup(rf.get("/readme/task-list/contact/"))

    with pytest.raises(ImproperlyConfigured, match="task_list_url_name"):
        view.get_task_list_url()


def test_a_section_can_bump_its_stash_label_without_renaming_itself(rf, client):
    """The guard rail for a deploy that reshapes a section: a payload from
    the old shape is refused at the door rather than walked into a tree it
    no longer matches."""
    from gandalf.runtime import InvalidStash

    _complete_contact(client)
    view = _view(
        _list(contact=Section(contact, label="contact-v2")), url_name="readme-task-list"
    )

    with pytest.raises(InvalidStash):
        _dispatch(rf, client, view, path="/readme/task-list/contact/", entry="contact")


def test_stash_unusable_can_be_overridden_to_start_the_section_over(rf, client):
    """The other half of the reshaped-section story: a page that would
    rather lose the old answers than 500."""
    _complete_contact(client)

    class _Forgiving(TaskListViewSet):
        template_name = "testapp/task_list.html"
        section_template_name = "testapp/linear_wizard.html"
        url_name = "readme-task-list"
        task_list = _list(contact=Section(contact, label="contact-v2"))

        def stash_unusable(self, entry, error):
            self.get_journey_store().delete_stash(entry.key)
            return self.enter(entry)

    request = rf.get("/readme/task-list/contact/")
    request.session = client.session
    response = _Forgiving.as_view()(request, entry="contact")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].endswith("/name/")
    assert "contact" not in request.session["gandalf_journeys"]["default"]["stashes"]


def test_a_section_without_a_title_is_named_from_its_key(client):
    response = client.get(reverse("scenario-task-list"))

    titles = {row.key: row.title for row in response.context["task_list"].rows}
    assert titles == {"plain": "Plain", "advancing": "Advancing"}


def test_a_section_stamps_its_declared_label_into_the_stash(rf, client):
    """`label` is the *shape's* identity — bumped when a deploy reshapes the
    wizard, without renaming the section — and the section's own viewset
    is what stamps it."""

    view_class = _view(
        _list(contact=Section(contact, label="contact-v2")), url_name="readme-task-list"
    ).viewset_for("contact")
    request = rf.get("/readme/task-list/contact/")
    request.session = client.session
    view = view_class()
    view.setup(request)
    run = view_class.begin(request)

    view.finish(run)

    stashes = request.session["gandalf_journeys"]["default"]["stashes"]
    assert stashes["contact"]["label"] == "contact-v2"


def test_a_pages_entries_are_chosen_once_per_request(rf, client):
    """Both halves of the page ask for the entries — the rows and the door
    — and `get_entries()` is a per-request choice, so it is asked once."""
    calls = []

    class _Counting(TaskListViewSet):
        template_name = "testapp/task_list.html"
        section_template_name = "testapp/linear_wizard.html"
        url_name = "readme-task-list"
        task_list = _list(contact=Section(contact))

        def get_entries(self):
            calls.append(1)
            return super().get_entries()

    request = rf.get(HUB_URL)
    request.session = client.session
    page = _Counting()
    page.setup(request)

    page.get_rows()
    page.get_entry("contact")

    assert len(calls) == 1
