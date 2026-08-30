"""Add another: a collection of items over HTTP.

The user grows the list, so every item is its own run — separately resumable,
separately completable, separately destroyable. Two guarantees carry the whole
design.

**No collection link is ever a bare run URL.** A run whose every stored answer
validates completes on a GET, so a row pointing at one would fire `done()` on a
click. Inherited from the hub, and asserted here again because a collection
reaches states a hub cannot.

**Removing from the middle renumbers nothing.** Identity is opaque, so the
survivors keep their ids and their URLs, and a link the user already has still
names the item they meant.
"""

import re
from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import resolve, reverse
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from gandalf.add_another import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnotherViewSet,
    ItemViewSet,
)
from gandalf.form_views import StepFormView
from gandalf.wizard import Wizard
from tests.testapp.forms import GuestForm
from gandalf.context import WizardContext
from gandalf.driver import RunDriver
from tests.testapp.views import GuestsViewSet, PartyViewSet
from gandalf.testing import (
    seed_item,
    stored_items,
    stored_section_run,
    stored_section_stashes,
)


PAGE = "/party/guests/"
#: The same collection mounted on its own, for tests that subclass its viewset.
STANDALONE = "/standalone-guests/"
ITEM = "11111111-1111-1111-1111-111111111111"


def _door(item_id):
    return reverse("party-hub-guests-item", kwargs={"item": item_id})


def _remove(item_id):
    return reverse("party-hub-guests-remove", kwargs={"item": item_id})


def _statuses(response):
    return [row.status for row in response.context["items"].rows]


def _titles(response):
    return [str(row.title) for row in response.context["items"].rows]


def _add(client, page=PAGE):
    """Press *add another* and land on the new item's first step."""
    return client.post(page, {"add_another": "yes"})["Location"]


def _answer(client, step_url, name):
    """Answer the guest step, returning wherever that lands."""
    return client.post(step_url, {"name": name, "dietary_requirements": ""})


def _complete(client, name, page=PAGE):
    """Add one item and drive it to its end, leaving a stash behind."""
    response = _answer(client, _add(client, page), name)
    return client.post(response["Location"], {})


# --- the empty page ---------------------------------------------------------


def test_a_list_nobody_has_added_to_offers_only_the_first_item(client):
    response = client.get(PAGE)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/collection.html")
    assert response.context["items"].is_empty
    assert response.context["items"].status == NOT_STARTED
    assertContains(response, "You have not added any guests")


# --- adding -----------------------------------------------------------------


def test_adding_an_item_lands_the_user_on_its_first_step(client):
    response = client.post(PAGE, {"add_another": "yes"})

    (item_id,) = stored_items(client, "guests")
    assertRedirects(
        response,
        reverse(
            "party-hub-guests-item-step",
            kwargs={
                "item": item_id,
                "run_id": stored_section_run(client, f"guests:{item_id}"),
                "gandalf_step": "guest",
            },
        ),
        target_status_code=HTTPStatus.OK,
    )


def test_an_item_is_registered_before_its_wizard_starts(client):
    """Which is what lets a half-finished item have a row at all — and what
    leaves a recoverable row rather than an orphan run if entering fails."""
    _add(client)

    assert len(stored_items(client, "guests")) == 1
    assert stored_section_stashes(client) == {}


def test_an_item_the_user_started_but_never_finished_reads_as_incomplete(client):
    _answer(client, _add(client), "Ada")

    response = client.get(PAGE)

    assert _statuses(response) == [INCOMPLETE]
    assert response.context["items"].status == INCOMPLETE


def test_an_unfinished_item_is_named_by_its_position(client):
    """Nothing it has answered is known to name it, so the page says so
    rather than inventing a name."""
    _add(client)

    assert _titles(client.get(PAGE)) == ["Guest 1"]


def test_finishing_an_item_names_it_and_returns_to_the_page(client):
    response = _complete(client, "Ada")

    assertRedirects(response, PAGE)
    listing = client.get(PAGE)
    assert _statuses(listing) == [COMPLETE]
    assert _titles(listing) == ["Ada"]
    assertContains(listing, "You have added 1 guest")


def test_the_page_counts_the_items_the_user_has_added(client):
    _complete(client, "Ada")
    _complete(client, "Grace")

    response = client.get(PAGE)

    assert _titles(response) == ["Ada", "Grace"]
    assertContains(response, "You have added 2 guests")


def test_the_add_another_question_has_to_be_answered(client):
    _complete(client, "Ada")

    response = client.post(PAGE, {})

    assert response.status_code == HTTPStatus.OK
    assertContains(response, "Select yes if you want to add another")
    assert len(stored_items(client, "guests")) == 1


# --- changing ---------------------------------------------------------------


def test_the_door_resumes_a_half_finished_item_where_it_left_off(client):
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_items(client, "guests")

    response = client.get(_door(item_id))

    assert response["Location"].rstrip("/").rsplit("/", 1)[-1] == "review"


def test_a_locked_items_door_sends_the_user_back_to_the_list_page(client):
    """An app may gate its items too. The door then has nothing to hand back,
    and must say so rather than redirect to `None`."""
    seed_item(client, "locked-guests", ITEM)

    response = client.get(reverse("locked-guests-item", kwargs={"item": ITEM}))

    assertRedirects(response, "/locked-guests/")


def test_adding_to_a_locked_list_leaves_the_row_and_the_page(client):
    """`add_item()` registers before it enters, so the item exists even though
    the door declined — a listed, removable, not-started row."""
    response = client.post("/locked-guests/", {"add_another": "yes"})

    assertRedirects(response, "/locked-guests/")
    assert len(stored_items(client, "locked-guests")) == 1


def test_the_door_reopens_a_finished_item_with_its_answers_in_place(client):
    _complete(client, "Ada")
    (item_id,) = stored_items(client, "guests")

    response = client.get(_door(item_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="Ada"')


def test_changing_a_finished_item_re_saves_it_and_re_caches_its_name(client):
    """A re-opened run arrives with every answer valid, so the next
    submission walks to the end and fires `done()` again — and `done()` is
    where the title is cached, so a rename shows on the page."""
    _complete(client, "Ada")
    (item_id,) = stored_items(client, "guests")
    step_url = client.get(_door(item_id))["Location"]

    response = _answer(client, step_url, "Ada Lovelace")

    assertRedirects(response, PAGE)
    assert _titles(client.get(PAGE)) == ["Ada Lovelace"]


def test_reopening_an_item_leaves_the_others_untouched(client):
    _complete(client, "Ada")
    _complete(client, "Grace")
    first, second = stored_items(client, "guests")

    client.get(_door(first))

    assert stored_items(client, "guests") == [first, second]
    assert _titles(client.get(PAGE)) == ["Ada", "Grace"]


# --- removing ---------------------------------------------------------------


def test_removing_an_item_asks_first(client):
    _complete(client, "Ada")
    (item_id,) = stored_items(client, "guests")

    response = client.get(_remove(item_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/collection_remove.html")
    assertContains(response, "Are you sure you want to remove Ada?")
    assert stored_items(client, "guests") == [item_id]


def test_removing_an_item_takes_its_row_its_stash_and_its_run(client):
    _complete(client, "Ada")
    (item_id,) = stored_items(client, "guests")

    response = client.post(_remove(item_id))

    assertRedirects(response, PAGE)
    assert stored_items(client, "guests") == []
    assert stored_section_stashes(client) == {}
    assert stored_section_run(client, f"guests:{item_id}") is None


def test_removing_from_the_middle_renumbers_nothing(client):
    """The whole reason identity is opaque: the survivors keep their ids, so
    a link the user already has still names the item they meant."""
    for name in ("Ada", "Grace", "Katherine"):
        _complete(client, name)
    first, second, third = stored_items(client, "guests")

    client.post(_remove(second))

    assert stored_items(client, "guests") == [first, third]
    response = client.get(PAGE)
    assert _titles(response) == ["Ada", "Katherine"]
    assert [row.url for row in response.context["items"].rows] == [
        _door(first),
        _door(third),
    ]


def test_removing_an_item_the_user_was_halfway_through_discards_its_run(client):
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")

    client.post(_remove(item_id))

    assert run_id not in client.session.get("gandalf_runs", {})


def test_a_removed_items_own_wizard_url_is_refused(client):
    """A second tab still on a step URL must not answer for an item that no
    longer exists, and must not mint a fresh run for it either."""
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")
    step_url = reverse(
        "party-hub-guests-item-step",
        kwargs={"item": item_id, "run_id": run_id, "gandalf_step": "guest"},
    )
    client.post(_remove(item_id))

    response = client.post(step_url, {"name": "Ada", "dietary_requirements": ""})

    assertRedirects(response, PAGE)
    assert stored_items(client, "guests") == []


def test_removing_the_last_item_empties_the_page(client):
    _complete(client, "Ada")
    (item_id,) = stored_items(client, "guests")

    client.post(_remove(item_id))

    response = client.get(PAGE)
    assert response.context["items"].is_empty
    assertContains(response, "You have not added any guests")


def test_an_item_this_list_does_not_list_is_sent_back_to_the_page(client):
    unknown = "11111111-1111-1111-1111-111111111111"

    assertRedirects(client.get(_door(unknown)), PAGE)


def test_posting_to_an_items_door_is_refused_and_removes_nothing(client):
    """The door opens an item; the remove route destroys one. Both carry an
    id, and the view used to branch on the id alone — so a POST to the URL a
    row links to took the item with it (#101)."""
    _complete(client, "Ada")
    (item_id,) = stored_items(client, "guests")

    response = client.post(_door(item_id))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert stored_items(client, "guests") == [item_id]
    assert _titles(client.get(PAGE)) == ["Ada"]


def test_removing_an_item_this_list_does_not_list_is_sent_back(client):
    unknown = "11111111-1111-1111-1111-111111111111"

    assertRedirects(client.post(_remove(unknown)), PAGE)


# --- declaring there are no more --------------------------------------------


def test_a_list_is_only_complete_once_the_user_says_so(client):
    """No reading of storage can say whether there are more guests to add —
    only the user can, so the page asks."""
    _complete(client, "Ada")

    assert client.get(PAGE).context["items"].status == INCOMPLETE

    response = client.post(PAGE, {"add_another": "no"})

    assertRedirects(response, "/party/", target_status_code=HTTPStatus.OK)
    assert client.get(PAGE).context["items"].status == COMPLETE


def test_declaring_no_more_over_a_half_finished_item_is_still_incomplete(client):
    """The user can only see the question from a page that lists the item, so
    answering it while one is unfinished is legitimate — and the honest thing
    to report is Incomplete, not Complete over answers nobody gave."""
    _complete(client, "Ada")
    _answer(client, _add(client), "Grace")

    response = client.post(PAGE, {"add_another": "no"})

    # The answer stands, but Continue is a submit and an incomplete one is
    # refused: back to the page, not up to the hub.
    assertRedirects(response, PAGE)
    assert client.get(PAGE).context["items"].declared_done is True
    assert client.get(PAGE).context["items"].status == INCOMPLETE


def test_adding_another_withdraws_the_users_answer(client):
    """Pressing Add *is* the user changing their mind about the question, so
    the stored answer goes and they are put past it once more."""
    _complete(client, "Ada")
    client.post(PAGE, {"add_another": "no"})

    _add(client)

    assert client.get(PAGE).context["items"].declared_done is False


def test_removing_an_item_does_not_re_ask_the_question(client):
    """Removal answers no question. Three guests minus one is still "and no
    more"."""
    _complete(client, "Ada")
    _complete(client, "Grace")
    client.post(PAGE, {"add_another": "no"})
    first, _second = stored_items(client, "guests")

    client.post(_remove(first))

    assert client.get(PAGE).context["items"].declared_done is True
    assert client.get(PAGE).context["items"].status == COMPLETE


def test_a_list_that_needs_an_item_is_incomplete_while_empty(client):
    page = "/minimum-guests/"

    client.post(page, {"add_another": "no"})

    assert client.get(page).context["items"].status == INCOMPLETE


def test_a_list_that_needs_an_item_completes_once_it_has_one(client):
    page = "/minimum-guests/"
    _complete(client, "Ada", page=page)

    client.post(page, {"add_another": "no"})

    assert client.get(page).context["items"].status == COMPLETE


# --- the parent task list ---------------------------------------------------


def test_a_task_list_links_straight_at_a_list_page(client):
    """A collection page is not a wizard, so the row links past the hub's own
    door — there is no run for the door to walk."""
    response = client.get("/party/")

    rows = {row.key: row for row in response.context["task_list"].rows}
    assert rows["guests"].url == PAGE
    assert rows["venue"].url == reverse("party-hub-entry", kwargs={"entry": "venue"})


def test_a_task_list_reports_the_lists_own_status(client):
    _complete(client, "Ada")
    client.post(PAGE, {"add_another": "no"})

    response = client.get("/party/")

    rows = {row.key: row.status for row in response.context["task_list"].rows}
    assert rows == {"venue": NOT_STARTED, "guests": COMPLETE}


def test_the_hub_door_for_a_list_is_its_page(client):
    """A collection is mounted at its own segment beneath the hub, so the
    URL the hub's door would answer for it is the page itself."""
    door = reverse("party-hub-entry", kwargs={"entry": "guests"})

    assert door == PAGE
    assert client.get(door).status_code == HTTPStatus.OK


# --- the invariants ---------------------------------------------------------


def test_a_list_door_hands_out_a_step_url_not_a_bare_run_url(client):
    """The invariant, asserted directly: whatever state an item is in, its
    door redirects to a step URL."""
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")

    response = client.get(_door(item_id))

    assert response["Location"] != reverse(
        "party-hub-guests-item-run", kwargs={"item": item_id, "run_id": run_id}
    )
    assert response["Location"].endswith("/review/")


def test_an_item_parked_with_every_answer_valid_still_gets_a_step_url(client):
    """The hazard the invariant exists for: an `Advance` escape leaves a live,
    non-tombstoned run whose every stored answer validates — the exact state
    in which a bare run URL fires `done()` on a GET."""
    page = "/advancing-guests/"
    step_url = _add(client, page)
    client.post(step_url, {"email": "ada@example.com"})
    (item_id,) = stored_items(client, "advancing-guests")

    response = client.get(reverse("advancing-guests-item", kwargs={"item": item_id}))

    run_id = stored_section_run(client, f"advancing-guests:{item_id}")
    assert response["Location"] != reverse(
        "advancing-guests-item-run", kwargs={"item": item_id, "run_id": run_id}
    )
    assert response["Location"].endswith("/newsletter/")


def test_the_item_wizards_bare_url_is_the_lists_door():
    """The item wizard is mounted beneath the door for its item, and its
    start URL — the one that would complete a valid run on a GET — is the
    door itself, so there is no bare run URL to publish."""
    item_id = "11111111-1111-1111-1111-111111111111"

    match = resolve(_door(item_id))
    assert match.func.view_class is PartyViewSet.viewset_for("guests")
    assert match.url_name == "party-hub-guests-item"


def test_building_the_rows_never_walks_an_item(client, monkeypatch):
    """A collection of thirty items costs thirty dict lookups, not thirty
    walks. The title was worked out once, when the item finished."""
    from gandalf.runtime import CursorWalker

    for name in ("Ada", "Grace"):
        _complete(client, name)

    def _refuse(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("rendering a collection row walked an item")

    monkeypatch.setattr(CursorWalker, "walk", _refuse)

    response = client.get(PAGE)

    assert _titles(response) == ["Ada", "Grace"]


# --- mount-prefix kwargs ----------------------------------------------------


def test_a_list_forwards_its_mount_prefix_into_every_url_it_builds(client):
    page = "/org/acme/hub/org_guests/"
    _add(client, page)
    (item_id,) = stored_items(client, "org_guests")

    response = client.get(page)

    (row,) = response.context["items"].rows
    assert row.url == f"{page}{item_id}/"
    assert row.remove_url == f"{page}{item_id}/remove/"


def test_an_item_wizard_carries_the_prefix_and_its_item_id_end_to_end(client):
    page = "/org/acme/hub/org_guests/"

    step_url = _add(client, page)

    (item_id,) = stored_items(client, "org_guests")
    assert step_url.startswith(f"{page}{item_id}/")


def test_a_finished_item_returns_to_its_list_not_to_its_own_item_url(client):
    """`get_hub_url()` drops the item segment: it is the wizard's own mount,
    and the collection's URL has no place for it."""
    page = "/org/acme/hub/org_guests/"

    response = _complete(client, "Ada", page=page)

    assertRedirects(response, page)


def test_a_seeded_item_with_no_run_reads_as_not_started(client):
    """A row exists from the moment the item is registered, so an item whose
    run the storage has since forgotten still has one."""
    seed_item(client, "guests", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    response = client.get(PAGE)

    assert _statuses(response) == [NOT_STARTED]
    assert _titles(response) == ["Guest 1"]


def test_a_seeded_item_keeps_the_title_it_was_given(client):
    seed_item(client, "guests", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", title="Ada")

    assert _titles(client.get(PAGE)) == ["Ada"]


def test_every_item_url_the_page_hands_out_is_one_of_its_own_routes(client):
    """Belt and braces on the negative guarantee: nothing on the page points
    into the item wizard's own URL space."""
    _complete(client, "Ada")
    _answer(client, _add(client), "Grace")

    body = client.get(PAGE).content.decode()

    # A run URL is an item id followed by a run id.
    uuid = "[0-9a-f-]{36}"
    assert not re.search(rf'href="[^"]*/{uuid}/{uuid}/', body)


# --- naming an item when nothing names it -----------------------------------


def test_an_item_whose_naming_step_is_off_its_route_falls_back_to_a_number(client):
    """A branch the user did not take names nothing, so the row numbers
    itself rather than inventing a name."""
    page = "/off-route-guests/"
    _complete(client, "Ada", page=page)

    response = client.get(page)

    assert _titles(response) == ["Guest 1"]
    assert _statuses(response) == [COMPLETE]


def test_a_list_names_its_items_from_its_own_key_by_default(client):
    page = "/reshaped-guests/"
    _add(client, page)

    assert _titles(client.get(page)) == ["Reshaped guest 1"]


def test_a_reshaped_item_stamps_the_bumped_label_into_its_stash(client):
    """Both halves of the label move together, so a re-opened item is still
    accepted at the door."""
    page = "/reshaped-guests/"
    _complete(client, "Ada", page=page)
    (item_id,) = stored_items(client, "reshaped-guests")

    assert (
        stored_section_stashes(client)[f"reshaped-guests:{item_id}"]["label"]
        == "guests-v2"
    )
    response = client.get(
        reverse("reshaped-guests-item", kwargs={"item": item_id}), follow=True
    )
    assertContains(response, 'value="Ada"')


# --- an item wizard reached for a run that is gone ---------------------------


def test_a_listed_item_whose_run_the_storage_forgot_returns_to_the_page(client):
    """Not to the item wizard's own start URL, which would mint a fresh run
    whose completion would stash under a key the page still lists."""
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")
    step_url = reverse(
        "party-hub-guests-item-step",
        kwargs={"item": item_id, "run_id": run_id, "gandalf_step": "guest"},
    )
    session = client.session
    del session["gandalf_runs"][run_id]
    session.save()

    response = client.get(step_url)

    assertRedirects(response, PAGE)


# --- misconfiguration -------------------------------------------------------


def _dispatch(rf, client, view, path=PAGE, method="get", data=None, **kwargs):
    """Dispatch a hand-built collection against the client's session, so a
    test can arrange state through the real flow and then point a
    misconfigured collection at it.

    Resolved through the real URLconf, because the view reads `resolver_match`
    to tell its three routes apart and a request that never went through a
    resolver answers for none of them.
    """
    request = getattr(rf, method)(path, data=data or {})
    request.session = client.session
    request.resolver_match = resolve(path)
    return view.as_view()(request, **kwargs)


def test_a_list_with_no_key_is_misconfigured():
    with pytest.raises(ImproperlyConfigured, match="key"):
        type("_Keyless", (GuestsViewSet,), {"key": None})


def test_a_list_with_no_declaration_is_misconfigured(rf, client):
    class _Undeclared(AddAnotherViewSet):
        url_name = "standalone-guests"
        key = "guests"

    with pytest.raises(ImproperlyConfigured, match="add_another"):
        _dispatch(rf, client, _Undeclared)


def test_a_list_listed_by_no_hub_is_a_root_and_needs_a_journey_done(rf, client):
    class _Endless(GuestsViewSet):
        task_list_url_name = None

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        _dispatch(rf, client, _Endless, method="post", data={"add_another": "no"})


def test_a_list_without_a_url_name_cannot_publish_urls():
    class _Nameless(AddAnotherViewSet):
        url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _Nameless.urls()


def test_an_item_title_field_no_step_declares_is_refused():
    with pytest.raises(ImproperlyConfigured, match="'nickname', a field no step"):

        class _Nameless(GuestsViewSet):
            add_another = GuestsViewSet.add_another.replace(item_title="nickname")


def test_an_item_title_field_two_steps_declare_is_refused():
    with pytest.raises(ImproperlyConfigured, match="steps guest, plus_one all declare"):

        class _Ambiguous(GuestsViewSet):
            add_another = GuestsViewSet.add_another.replace(
                wizard=Wizard()
                .step(GuestForm, name="guest")
                .step(GuestForm, name="plus_one")
            )


def test_a_step_view_that_picks_its_form_at_request_time_declares_no_fields():
    class _Undecided(StepFormView):
        template_name = "testapp/linear_wizard.html"

        def get_form_class(self):
            return GuestForm

    with pytest.raises(ImproperlyConfigured, match="a field no step"):

        class _Unreadable(GuestsViewSet):
            add_another = GuestsViewSet.add_another.replace(
                wizard=Wizard().step(_Undecided, name="guest")
            )


def test_an_item_wizard_the_declaration_cannot_see_is_taken_on_trust(rf):
    class _PerRequest(ItemViewSet):
        def get_wizard(self, run):
            return Wizard().step(GuestForm, name="guest")

    class _Trusted(GuestsViewSet):
        add_another = GuestsViewSet.add_another.replace(
            wizard=_PerRequest, item_title="anything", item_name=None
        )

    class _Growing(GuestsViewSet):
        add_another = GuestsViewSet.add_another.replace(
            wizard=Wizard()
            .step(GuestForm, name="guest")
            .expand(lambda context: Wizard())
        )

    assert _Trusted.item_viewset.item_title == "anything"
    assert _Growing.item_viewset.item_title == "name"
    view = _Trusted()
    view.setup(rf.get(PAGE))
    assert view.get_item_name() == "Standalone guest"


def test_an_add_another_base_that_names_its_own_pages_keeps_them():
    class _Themed(AddAnotherViewSet):
        template_name = "testapp/hub.html"

    class _Party(PartyViewSet):
        url_name = "themed-party"
        add_another_viewset_class = _Themed

    assert _Party.viewset_for("guests").template_name == "testapp/hub.html"
    assert (
        _Party.viewset_for("guests").remove_template_name
        == "testapp/collection_remove.html"
    )


def test_a_list_with_no_confirmation_page_is_misconfigured(rf, client):
    class _Blunt(GuestsViewSet):
        remove_template_name = None

    _add(client, STANDALONE)
    (item_id,) = stored_items(client, "standalone-guests")
    request = rf.get(f"{STANDALONE}{item_id}/remove/")
    request.session = client.session
    request.resolver_match = type(
        "_Match", (), {"url_name": "standalone-guests-remove"}
    )()

    with pytest.raises(ImproperlyConfigured, match="remove_template_name"):
        _Blunt.as_view()(request, item=item_id)


def test_an_item_wizard_that_cannot_name_its_items_says_so_at_completion(client):
    """Raised where the title would have been cached, not before."""
    page = "/anonymous-guests/"
    response = _answer(client, _add(client, page), "Ada")

    with pytest.raises(ImproperlyConfigured, match="item_title"):
        client.post(response["Location"], {})


def test_an_item_wizard_with_no_list_key_is_misconfigured(rf, client):
    class _Homeless(GuestsViewSet.item_viewset):
        list_key = None

    request = rf.get(f"/standalone-guests/{ITEM}/")
    request.session = client.session

    with pytest.raises(ImproperlyConfigured, match="no list"):
        _Homeless.as_view()(request, item=ITEM)


def test_an_item_wizard_not_mounted_under_an_item_is_misconfigured(rf, client):
    request = rf.get("/standalone-guests/")
    request.session = client.session

    with pytest.raises(ImproperlyConfigured, match="item segment"):
        GuestsViewSet.item_viewset.as_view()(request)


def test_a_driver_can_address_one_item_of_a_list(client):
    """The generated item viewset is public, for a script or an agent that
    adds an item without a browser."""
    _add(client)
    (item_id,) = stored_items(client, "guests")
    context = WizardContext(session=client.session)

    driver = RunDriver.begin(
        PartyViewSet.viewset_for("guests").item_viewset,
        item=item_id,
        context=context,
    )

    assert driver.run.context.url_kwargs == {"item": item_id}


# --- the registry's edges ---------------------------------------------------


def test_registering_an_id_a_list_already_lists_does_not_duplicate_it(rf, client):
    """Ids need not be uuids — a collection whose items are named by the
    domain can press Add twice for the same one."""

    from gandalf.storage import SessionCollectionStore

    class _Fixed(GuestsViewSet):
        def new_item_id(self):
            return ITEM

    session = client.session
    for _ in range(2):
        request = rf.post(PAGE, {"add_another": "yes"})
        request.session = session
        _Fixed.as_view()(request)

    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.item_ids("standalone-guests") == [ITEM]


def test_an_item_a_list_lists_but_never_registered_is_named_by_position(rf, client):
    """The seam for a collection built from the application's own records
    rather than the registry: there is no cached title to read."""

    class _FromElsewhere(GuestsViewSet):
        def get_item_ids(self):
            return [ITEM]

    response = _dispatch(rf, client, _FromElsewhere)

    (row,) = response.context_data["items"].rows
    assert str(row.title) == "Guest 1"
    assert row.status == NOT_STARTED


def test_removing_an_item_that_was_never_registered_is_not_an_error(rf, client):
    class _FromElsewhere(GuestsViewSet):
        def get_item_ids(self):
            return [ITEM]

    response = _dispatch(
        rf,
        client,
        _FromElsewhere,
        method="post",
        path=f"{STANDALONE}{ITEM}/remove/",
        item=ITEM,
    )

    assert response["Location"] == STANDALONE


def test_removing_an_item_whose_run_the_storage_forgot_is_not_an_error(client):
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")
    session = client.session
    del session["gandalf_runs"][run_id]
    session.save()

    assertRedirects(client.post(_remove(item_id)), PAGE)
    assert stored_items(client, "guests") == []


def test_a_list_reports_its_own_shape_to_a_template(client):
    empty = client.get(PAGE).context["items"]
    assert (empty.is_not_started, empty.is_incomplete, empty.is_complete) == (
        True,
        False,
        False,
    )

    _complete(client, "Ada")
    started = client.get(PAGE).context["items"]
    assert (started.is_not_started, started.is_incomplete, started.is_complete) == (
        False,
        True,
        False,
    )

    client.post(PAGE, {"add_another": "no"})
    done = client.get(PAGE).context["items"]
    assert (done.is_not_started, done.is_incomplete, done.is_complete) == (
        False,
        False,
        True,
    )


def test_a_list_page_counts_its_items_without_a_loop_in_the_template(client):
    """The `Hub` counts, on the object that already was one. A page saying
    "2 of 3 finished" derived it by looping the rows until now."""
    _complete(client, "Ada")
    _complete(client, "Grace")
    _add(client)

    collection = client.get(PAGE).context["items"]

    assert (collection.count, collection.completed, collection.remaining) == (3, 2, 1)
    assert collection.blocked == 0
    assertContains(client.get(PAGE), "You have completed 2 of 3 guests")


def test_a_driver_fills_one_item_of_a_list():
    """An item is a run like any other, and its id is a URL kwarg.

    This is the shape an agent needs: one context held for whoever it is
    working for, addressing one item and then the next. It is here rather
    than in the driver's own tests because the thing worth proving is that
    the collection *page* then sees what the driver did — one registry,
    whichever door it was reached through.
    """
    context = WizardContext()
    page = GuestsViewSet()
    page.setup(context.http_request())
    page.add_item()
    item_id = page.get_item_ids()[-1]

    driver = RunDriver.begin(
        GuestsViewSet.item_viewset,
        item=item_id,
        context=context,
        may_finish=True,
    )
    driver.prefill({"guest": {"name": "Ada Lovelace"}})
    driver.submit({"confirmed": True}, step="review")
    driver.finish()

    seen = GuestsViewSet()
    seen.setup(context.http_request())
    assert [str(row.title) for row in seen.get_rows()] == ["Ada Lovelace"]


def test_addressing_a_second_item_does_not_disturb_the_first():
    """One context, two items. The url kwarg is the part that varies, and
    naming it must not hand the second run the first one's identity."""
    context = WizardContext()

    first = RunDriver.begin(GuestsViewSet.item_viewset, item="one", context=context)
    second = RunDriver.begin(GuestsViewSet.item_viewset, item="two", context=context)

    assert first.view.kwargs == {"item": "one"}
    assert second.view.kwargs == {"item": "two"}
    assert first.run_id != second.run_id
    # The context itself is untouched, so the next call starts from the
    # same place rather than from wherever the last one left it.
    assert context.url_kwargs == {}
