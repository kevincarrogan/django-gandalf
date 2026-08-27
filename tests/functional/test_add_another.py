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
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from gandalf.collections import COMPLETE, INCOMPLETE, NOT_STARTED, CollectionView
from gandalf.context import WizardContext
from gandalf.driver import RunDriver
from tests.testapp.views import GuestCollectionView, GuestItemViewSet
from gandalf.testing import (
    seed_collection_item,
    stored_collection_items,
    stored_section_run,
    stored_stashes,
)


PAGE = "/party-guests/"
ITEM = "11111111-1111-1111-1111-111111111111"


def _door(item_id):
    return reverse("party-guests-item", kwargs={"item": item_id})


def _remove(item_id):
    return reverse("party-guests-remove", kwargs={"item": item_id})


def _statuses(response):
    return [row.status for row in response.context["collection"].rows]


def _titles(response):
    return [str(row.title) for row in response.context["collection"].rows]


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


def test_a_collection_nobody_has_added_to_offers_only_the_first_item(client):
    response = client.get(PAGE)

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/collection.html")
    assert response.context["collection"].is_empty
    assert response.context["collection"].status == NOT_STARTED
    assertContains(response, "You have not added any guests")


# --- adding -----------------------------------------------------------------


def test_adding_an_item_lands_the_user_on_its_first_step(client):
    response = client.post(PAGE, {"add_another": "yes"})

    (item_id,) = stored_collection_items(client, "guests")
    assertRedirects(
        response,
        reverse(
            "party-guest-step",
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

    assert len(stored_collection_items(client, "guests")) == 1
    assert stored_stashes(client) == {}


def test_an_item_the_user_started_but_never_finished_reads_as_incomplete(client):
    _answer(client, _add(client), "Ada")

    response = client.get(PAGE)

    assert _statuses(response) == [INCOMPLETE]
    assert response.context["collection"].status == INCOMPLETE


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
    assert len(stored_collection_items(client, "guests")) == 1


# --- changing ---------------------------------------------------------------


def test_the_door_resumes_a_half_finished_item_where_it_left_off(client):
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_collection_items(client, "guests")

    response = client.get(_door(item_id))

    assert response["Location"].rstrip("/").rsplit("/", 1)[-1] == "review"


def test_a_locked_items_door_sends_the_user_back_to_the_collection_page(client):
    """An app may gate its items too. The door then has nothing to hand back,
    and must say so rather than redirect to `None`."""
    seed_collection_item(client, "locked-guests", ITEM)

    response = client.get(reverse("locked-guests-item", kwargs={"item": ITEM}))

    assertRedirects(response, "/locked-guests/")


def test_adding_to_a_locked_collection_leaves_the_row_and_the_page(client):
    """`add_item()` registers before it enters, so the item exists even though
    the door declined — a listed, removable, not-started row."""
    response = client.post("/locked-guests/", {"add_another": "yes"})

    assertRedirects(response, "/locked-guests/")
    assert len(stored_collection_items(client, "locked-guests")) == 1


def test_the_door_reopens_a_finished_item_with_its_answers_in_place(client):
    _complete(client, "Ada")
    (item_id,) = stored_collection_items(client, "guests")

    response = client.get(_door(item_id), follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, 'value="Ada"')


def test_changing_a_finished_item_re_saves_it_and_re_caches_its_name(client):
    """A re-opened run arrives with every answer valid, so the next
    submission walks to the end and fires `done()` again — and `done()` is
    where the title is cached, so a rename shows on the page."""
    _complete(client, "Ada")
    (item_id,) = stored_collection_items(client, "guests")
    step_url = client.get(_door(item_id))["Location"]

    response = _answer(client, step_url, "Ada Lovelace")

    assertRedirects(response, PAGE)
    assert _titles(client.get(PAGE)) == ["Ada Lovelace"]


def test_reopening_an_item_leaves_the_others_untouched(client):
    _complete(client, "Ada")
    _complete(client, "Grace")
    first, second = stored_collection_items(client, "guests")

    client.get(_door(first))

    assert stored_collection_items(client, "guests") == [first, second]
    assert _titles(client.get(PAGE)) == ["Ada", "Grace"]


# --- removing ---------------------------------------------------------------


def test_removing_an_item_asks_first(client):
    _complete(client, "Ada")
    (item_id,) = stored_collection_items(client, "guests")

    response = client.get(_remove(item_id))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/collection_remove.html")
    assertContains(response, "Are you sure you want to remove Ada?")
    assert stored_collection_items(client, "guests") == [item_id]


def test_removing_an_item_takes_its_row_its_stash_and_its_run(client):
    _complete(client, "Ada")
    (item_id,) = stored_collection_items(client, "guests")

    response = client.post(_remove(item_id))

    assertRedirects(response, PAGE)
    assert stored_collection_items(client, "guests") == []
    assert stored_stashes(client) == {}
    assert stored_section_run(client, f"guests:{item_id}") is None


def test_removing_from_the_middle_renumbers_nothing(client):
    """The whole reason identity is opaque: the survivors keep their ids, so
    a link the user already has still names the item they meant."""
    for name in ("Ada", "Grace", "Katherine"):
        _complete(client, name)
    first, second, third = stored_collection_items(client, "guests")

    client.post(_remove(second))

    assert stored_collection_items(client, "guests") == [first, third]
    response = client.get(PAGE)
    assert _titles(response) == ["Ada", "Katherine"]
    assert [row.url for row in response.context["collection"].rows] == [
        _door(first),
        _door(third),
    ]


def test_removing_an_item_the_user_was_halfway_through_discards_its_run(client):
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_collection_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")

    client.post(_remove(item_id))

    assert run_id not in client.session.get("gandalf_runs", {})


def test_a_removed_items_own_wizard_url_is_refused(client):
    """A second tab still on a step URL must not answer for an item that no
    longer exists, and must not mint a fresh run for it either."""
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_collection_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")
    step_url = reverse(
        "party-guest-step",
        kwargs={"item": item_id, "run_id": run_id, "gandalf_step": "guest"},
    )
    client.post(_remove(item_id))

    response = client.post(step_url, {"name": "Ada", "dietary_requirements": ""})

    assertRedirects(response, PAGE)
    assert stored_collection_items(client, "guests") == []


def test_removing_the_last_item_empties_the_page(client):
    _complete(client, "Ada")
    (item_id,) = stored_collection_items(client, "guests")

    client.post(_remove(item_id))

    response = client.get(PAGE)
    assert response.context["collection"].is_empty
    assertContains(response, "You have not added any guests")


@pytest.mark.parametrize("method", ["get", "post"])
def test_an_item_this_collection_does_not_list_is_sent_back_to_the_page(client, method):
    unknown = "11111111-1111-1111-1111-111111111111"

    response = getattr(client, method)(_door(unknown))

    assertRedirects(response, PAGE)


def test_removing_an_item_this_collection_does_not_list_is_sent_back(client):
    unknown = "11111111-1111-1111-1111-111111111111"

    assertRedirects(client.post(_remove(unknown)), PAGE)


# --- declaring there are no more --------------------------------------------


def test_a_collection_is_only_complete_once_the_user_says_so(client):
    """No reading of storage can say whether there are more guests to add —
    only the user can, so the page asks."""
    _complete(client, "Ada")

    assert client.get(PAGE).context["collection"].status == INCOMPLETE

    response = client.post(PAGE, {"add_another": "no"})

    assertRedirects(response, "/party/", target_status_code=HTTPStatus.OK)
    assert client.get(PAGE).context["collection"].status == COMPLETE


def test_declaring_no_more_over_a_half_finished_item_is_still_incomplete(client):
    """The user can only see the question from a page that lists the item, so
    answering it while one is unfinished is legitimate — and the honest thing
    to report is Incomplete, not Complete over answers nobody gave."""
    _complete(client, "Ada")
    _answer(client, _add(client), "Grace")

    client.post(PAGE, {"add_another": "no"})

    assert client.get(PAGE).context["collection"].status == INCOMPLETE


def test_adding_another_withdraws_the_users_answer(client):
    """Pressing Add *is* the user changing their mind about the question, so
    the stored answer goes and they are put past it once more."""
    _complete(client, "Ada")
    client.post(PAGE, {"add_another": "no"})

    _add(client)

    assert client.get(PAGE).context["collection"].declared_done is False


def test_removing_an_item_does_not_re_ask_the_question(client):
    """Removal answers no question. Three guests minus one is still "and no
    more"."""
    _complete(client, "Ada")
    _complete(client, "Grace")
    client.post(PAGE, {"add_another": "no"})
    first, _second = stored_collection_items(client, "guests")

    client.post(_remove(first))

    assert client.get(PAGE).context["collection"].declared_done is True
    assert client.get(PAGE).context["collection"].status == COMPLETE


def test_a_collection_that_needs_an_item_is_incomplete_while_empty(client):
    page = "/minimum-guests/"

    client.post(page, {"add_another": "no"})

    assert client.get(page).context["collection"].status == INCOMPLETE


def test_a_collection_that_needs_an_item_completes_once_it_has_one(client):
    page = "/minimum-guests/"
    _complete(client, "Ada", page=page)

    client.post(page, {"add_another": "no"})

    assert client.get(page).context["collection"].status == COMPLETE


# --- the parent task list ---------------------------------------------------


def test_a_task_list_links_straight_at_a_collection_page(client):
    """A collection page is not a wizard, so the row links past the hub's own
    door — there is no run for the door to walk."""
    response = client.get("/party/")

    rows = {row.key: row for row in response.context["hub"].rows}
    assert rows["guests"].url == PAGE
    assert rows["venue"].url == reverse(
        "party-hub-section", kwargs={"section": "venue"}
    )


def test_a_task_list_reports_the_collections_own_status(client):
    _complete(client, "Ada")
    client.post(PAGE, {"add_another": "no"})

    response = client.get("/party/")

    rows = {row.key: row.status for row in response.context["hub"].rows}
    assert rows == {"venue": NOT_STARTED, "guests": COMPLETE}


def test_the_hub_door_refuses_a_row_that_is_not_a_wizard(client):
    """Rows never point there, so arriving is a hand-typed or stale URL."""
    response = client.get(reverse("party-hub-section", kwargs={"section": "guests"}))

    assertRedirects(response, "/party/")


# --- the invariants ---------------------------------------------------------


def test_a_collection_door_hands_out_a_step_url_not_a_bare_run_url(client):
    """The invariant, asserted directly: whatever state an item is in, its
    door redirects to a step URL."""
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_collection_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")

    response = client.get(_door(item_id))

    assert response["Location"] != reverse(
        "party-guest-run", kwargs={"item": item_id, "run_id": run_id}
    )
    assert response["Location"].endswith("/review/")


def test_an_item_parked_with_every_answer_valid_still_gets_a_step_url(client):
    """The hazard the invariant exists for: an `Advance` escape leaves a live,
    non-tombstoned run whose every stored answer validates — the exact state
    in which a bare run URL fires `done()` on a GET."""
    page = "/advancing-guests/"
    step_url = _add(client, page)
    client.post(step_url, {"email": "ada@example.com"})
    (item_id,) = stored_collection_items(client, "advancing-guests")

    response = client.get(reverse("advancing-guests-item", kwargs={"item": item_id}))

    run_id = stored_section_run(client, f"advancing-guests:{item_id}")
    assert response["Location"] != reverse(
        "advancing-guest-run", kwargs={"item": item_id, "run_id": run_id}
    )
    assert response["Location"].endswith("/newsletter/")


def test_the_collection_door_and_the_item_wizard_do_not_share_a_url():
    """A wizard mounted under the collection's own prefix would publish its
    start URL at the exact path of the door for that item, and whichever
    `include()` came first would silently win."""
    item_id = "11111111-1111-1111-1111-111111111111"

    assert _door(item_id) != reverse("party-guest", kwargs={"item": item_id})


def test_the_hub_door_and_the_collection_page_do_not_share_a_url():
    """`HubView` publishes `<slug:section>/`, which matches any single
    segment — so a collection mounted beneath a hub would be swallowed by the
    hub's own door for a section of that name."""
    assert PAGE != reverse("party-hub-section", kwargs={"section": "guests"})


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


def test_a_collection_forwards_its_mount_prefix_into_every_url_it_builds(client):
    page = "/org/acme/guests/"
    _add(client, page)
    (item_id,) = stored_collection_items(client, "org-guests")

    response = client.get(page)

    (row,) = response.context["collection"].rows
    assert row.url == f"/org/acme/guests/{item_id}/"
    assert row.remove_url == f"/org/acme/guests/{item_id}/remove/"


def test_an_item_wizard_carries_the_prefix_and_its_item_id_end_to_end(client):
    page = "/org/acme/guests/"

    step_url = _add(client, page)

    (item_id,) = stored_collection_items(client, "org-guests")
    assert step_url.startswith(f"/org/acme/guest/{item_id}/")


def test_a_finished_item_returns_to_its_collection_not_to_its_own_item_url(client):
    """`get_hub_url()` drops the item segment: it is the wizard's own mount,
    and the collection's URL has no place for it."""
    page = "/org/acme/guests/"

    response = _complete(client, "Ada", page=page)

    assertRedirects(response, page)


# --- misconfiguration -------------------------------------------------------


def test_an_item_label_that_drifts_from_its_collections_is_rejected(client):
    """A re-opened item would be refused at the door and could never be
    changed — the hub's key drift check, one level down."""
    with pytest.raises(ImproperlyConfigured, match="item label must match"):
        client.get("/drifted-guests/")


def test_a_seeded_item_with_no_run_reads_as_not_started(client):
    """A row exists from the moment the item is registered, so an item whose
    run the storage has since forgotten still has one."""
    seed_collection_item(client, "guests", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    response = client.get(PAGE)

    assert _statuses(response) == [NOT_STARTED]
    assert _titles(response) == ["Guest 1"]


def test_a_seeded_item_keeps_the_title_it_was_given(client):
    seed_collection_item(
        client, "guests", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", title="Ada"
    )

    assert _titles(client.get(PAGE)) == ["Ada"]


def test_every_item_url_the_page_hands_out_is_one_of_its_own_routes(client):
    """Belt and braces on the negative guarantee: nothing on the page points
    into the item wizard's own URL space."""
    _complete(client, "Ada")
    _answer(client, _add(client), "Grace")

    body = client.get(PAGE).content.decode()

    assert not re.search(r'href="/party-guest/', body)


# --- naming an item when nothing names it -----------------------------------


def test_an_item_whose_naming_step_is_off_its_route_falls_back_to_a_number(client):
    """A branch the user did not take names nothing, so the row numbers
    itself rather than inventing a name."""
    page = "/off-route-guests/"
    _complete(client, "Ada", page=page)

    response = client.get(page)

    assert _titles(response) == ["Guest 1"]
    assert _statuses(response) == [COMPLETE]


def test_a_collection_names_its_items_from_its_own_key_by_default(client):
    page = "/reshaped-guests/"
    _add(client, page)

    assert _titles(client.get(page)) == ["Reshaped guest 1"]


def test_a_reshaped_item_stamps_the_bumped_label_into_its_stash(client):
    """Both halves of the label move together, so a re-opened item is still
    accepted at the door."""
    page = "/reshaped-guests/"
    _complete(client, "Ada", page=page)
    (item_id,) = stored_collection_items(client, "reshaped-guests")

    assert stored_stashes(client)[f"reshaped-guests:{item_id}"]["label"] == "guests-v2"
    response = client.get(
        reverse("reshaped-guests-item", kwargs={"item": item_id}), follow=True
    )
    assertContains(response, 'value="Ada"')


# --- an item wizard reached for a run that is gone ---------------------------


def test_a_listed_item_whose_run_the_storage_forgot_returns_to_the_page(client):
    """Not to the item wizard's own start URL, which would mint a fresh run
    whose completion would stash under a key the page still lists."""
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_collection_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")
    step_url = reverse(
        "party-guest-step",
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
    misconfigured collection at it."""
    request = getattr(rf, method)(path, data=data or {})
    request.session = client.session
    return view.as_view()(request, **kwargs)


def test_a_collection_with_no_key_is_misconfigured(rf, client):
    class _Keyless(GuestCollectionView):
        collection_key = None

    with pytest.raises(ImproperlyConfigured, match="collection_key"):
        _dispatch(rf, client, _Keyless)


def test_a_collection_with_no_item_wizard_is_misconfigured(rf, client):
    class _Wizardless(GuestCollectionView):
        item_viewset = None

    with pytest.raises(ImproperlyConfigured, match="item_viewset"):
        _dispatch(rf, client, _Wizardless)


def test_a_collection_with_nowhere_to_continue_to_is_misconfigured(rf, client):
    class _Endless(GuestCollectionView):
        continue_url_name = None

    with pytest.raises(ImproperlyConfigured, match="continue_url_name"):
        _dispatch(rf, client, _Endless, method="post", data={"add_another": "no"})


def test_a_collection_without_a_url_name_cannot_reverse_its_own_pages(rf, client):
    class _Nameless(GuestCollectionView):
        url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _dispatch(rf, client, _Nameless)


def test_a_collection_without_a_url_name_cannot_reverse_an_items_links(rf, client):
    class _Nameless(GuestCollectionView):
        url_name = None

        def get_collection_url(self):
            return PAGE

    seed_collection_item(client, "guests", ITEM)

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _dispatch(rf, client, _Nameless)


def test_a_collection_without_a_url_name_cannot_publish_urls():
    class _Nameless(CollectionView):
        url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _Nameless.urls()


def test_a_collection_with_no_confirmation_page_is_misconfigured(rf, client):
    class _Blunt(GuestCollectionView):
        remove_template_name = None

    _add(client)
    (item_id,) = stored_collection_items(client, "guests")
    request = rf.get(f"{PAGE}{item_id}/remove/")
    request.session = client.session
    request.resolver_match = type("_Match", (), {"url_name": "party-guests-remove"})()

    with pytest.raises(ImproperlyConfigured, match="remove_template_name"):
        _Blunt.as_view()(request, item=item_id)


def test_an_item_wizard_that_cannot_name_its_items_says_so_at_completion(client):
    """Raised where the title would have been cached, not before."""
    page = "/anonymous-guests/"
    response = _answer(client, _add(client, page), "Ada")

    with pytest.raises(ImproperlyConfigured, match="item_title_step"):
        client.post(response["Location"], {})


def test_an_item_wizard_with_no_collection_key_is_misconfigured(rf, client):
    class _Homeless(GuestItemViewSet):
        collection_key = None

    request = rf.get(f"/party-guest/{ITEM}/")
    request.session = client.session

    with pytest.raises(ImproperlyConfigured, match="collection_key"):
        _Homeless.as_view()(request, item=ITEM)


def test_an_item_wizard_with_no_collection_url_is_misconfigured(rf, client):
    class _Adrift(GuestItemViewSet):
        collection_url_name = None

    request = rf.get(f"/party-guest/{ITEM}/")
    request.session = client.session
    view = _Adrift()
    view.setup(request, item=ITEM)

    with pytest.raises(ImproperlyConfigured, match="collection_url_name"):
        view.get_hub_url()


def test_an_item_wizard_with_no_item_segment_is_misconfigured(rf, client):
    request = rf.get("/party-guest/")
    request.session = client.session
    view = GuestItemViewSet()
    view.setup(request)

    with pytest.raises(ImproperlyConfigured, match="item segment"):
        view.get_item_id()


# --- the registry's edges ---------------------------------------------------


def test_registering_an_id_a_collection_already_lists_does_not_duplicate_it(rf, client):
    """Ids need not be uuids — a collection whose items are named by the
    domain can press Add twice for the same one."""

    from gandalf.storage import SessionCollectionStore

    class _Fixed(GuestCollectionView):
        def new_item_id(self):
            return ITEM

    session = client.session
    for _ in range(2):
        request = rf.post(PAGE, {"add_another": "yes"})
        request.session = session
        _Fixed.as_view()(request)

    store = SessionCollectionStore(WizardContext.from_request(request))
    assert store.item_ids("guests") == [ITEM]


def test_an_item_a_collection_lists_but_never_registered_is_named_by_position(
    rf, client
):
    """The seam for a collection built from the application's own records
    rather than the registry: there is no cached title to read."""

    class _FromElsewhere(GuestCollectionView):
        def get_item_ids(self):
            return [ITEM]

    response = _dispatch(rf, client, _FromElsewhere)

    (row,) = response.context_data["collection"].rows
    assert str(row.title) == "Guest 1"
    assert row.status == NOT_STARTED


def test_removing_an_item_that_was_never_registered_is_not_an_error(rf, client):
    class _FromElsewhere(GuestCollectionView):
        def get_item_ids(self):
            return [ITEM]

    response = _dispatch(
        rf,
        client,
        _FromElsewhere,
        method="post",
        path=f"{PAGE}{ITEM}/remove/",
        item=ITEM,
    )

    assert response["Location"] == PAGE


def test_removing_an_item_whose_run_the_storage_forgot_is_not_an_error(client):
    _answer(client, _add(client), "Ada")
    (item_id,) = stored_collection_items(client, "guests")
    run_id = stored_section_run(client, f"guests:{item_id}")
    session = client.session
    del session["gandalf_runs"][run_id]
    session.save()

    assertRedirects(client.post(_remove(item_id)), PAGE)
    assert stored_collection_items(client, "guests") == []


def test_a_collection_reports_its_own_shape_to_a_template(client):
    empty = client.get(PAGE).context["collection"]
    assert (empty.is_not_started, empty.is_incomplete, empty.is_complete) == (
        True,
        False,
        False,
    )

    _complete(client, "Ada")
    started = client.get(PAGE).context["collection"]
    assert (started.is_not_started, started.is_incomplete, started.is_complete) == (
        False,
        True,
        False,
    )

    client.post(PAGE, {"add_another": "no"})
    done = client.get(PAGE).context["collection"]
    assert (done.is_not_started, done.is_incomplete, done.is_complete) == (
        False,
        False,
        True,
    )


def test_a_driver_fills_one_item_of_a_collection():
    """An item is a run like any other, and its id is a URL kwarg.

    This is the shape an agent needs: one context held for whoever it is
    working for, addressing one item and then the next. It is here rather
    than in the driver's own tests because the thing worth proving is that
    the collection *page* then sees what the driver did — one registry,
    whichever door it was reached through.
    """
    context = WizardContext()
    page = GuestCollectionView()
    page.setup(context.http_request())
    page.add_item()
    item_id = page.get_item_ids()[-1]

    driver = RunDriver.begin(
        GuestItemViewSet, item=item_id, context=context, may_finish=True
    )
    driver.prefill({"guest": {"name": "Ada Lovelace"}})
    driver.submit({"confirmed": True}, step="review")
    driver.finish()

    seen = GuestCollectionView()
    seen.setup(context.http_request())
    assert [str(row.title) for row in seen.get_section_rows()] == ["Ada Lovelace"]


def test_addressing_a_second_item_does_not_disturb_the_first():
    """One context, two items. The url kwarg is the part that varies, and
    naming it must not hand the second run the first one's identity."""
    context = WizardContext()

    first = RunDriver.begin(GuestItemViewSet, item="one", context=context)
    second = RunDriver.begin(GuestItemViewSet, item="two", context=context)

    assert first.view.kwargs == {"item": "one"}
    assert second.view.kwargs == {"item": "two"}
    assert first.run_id != second.run_id
    # The context itself is untouched, so the next call starts from the
    # same place rather than from wherever the last one left it.
    assert context.url_kwargs == {}
