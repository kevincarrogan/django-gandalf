"""Unit coverage for the add-another layer.

A collection is a hub whose members are built from an ordered registry rather
than declared, so most of its behaviour is `HubViewSet`'s and is covered
there. What is genuinely its own: how far the whole thing has got, what an
item is called, what the four actions do in what order, and what it refuses
to be configured as.
"""

from dataclasses import replace

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf.collections import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnotherForm,
    Collection,
    CollectionPage,
    CollectionRow,
    CollectionViewSet,
    ItemNotFound,
    ItemViewSet,
)
from gandalf.context import WizardContext
from gandalf.hubs import Hub, HubPage, HubViewSet, Member
from gandalf.storage import SessionCollectionStore
from gandalf.wizard import Wizard

from tests.testapp.forms import GuestForm
from tests.testapp.views import GuestCollectionViewSet, LockedGuestCollectionViewSet


class _Session(dict):
    modified = False


#: The parts of a journey's record a test seeds, lifted under the journey
#: key the store reads them from. Everything else (`gandalf_runs`) passes
#: through untouched.
_JOURNEY_PARTS = ("runs", "stashes", "collections", "data", "completed")


def _session(seed=None, journey="default"):
    seed = dict(seed or {})
    record = {part: seed.pop(part) for part in _JOURNEY_PARTS if part in seed}
    if record:
        seed["gandalf_journeys"] = {journey: record}
    return _Session(seed)


GUESTS = Collection(
    Wizard().step(GuestForm, name="guest"),
    item_name="Guest",
    item_title=("guest", "name"),
    template_name="testapp/collection.html",
    remove_template_name="testapp/collection_remove.html",
)


class _Collection(CollectionViewSet):
    """Named after the test app's standalone collection, so every URL it
    builds reverses through the URLconf rather than being faked."""

    url_name = "standalone-guests"
    member_key = "guests"
    member_template_name = "testapp/linear_wizard.html"
    collection = GUESTS
    hub_url_name = "party-hub"


_ItemViewSet = _Collection.item_viewset

PAGE = "/standalone-guests/"


def _page(cls, rf, session=None, path=PAGE, method="get", **kwargs):
    request = getattr(rf, method)(path)
    request.session = _session(session or {})
    view = cls()
    view.setup(request, **kwargs)
    return view


@pytest.fixture
def collection(rf):
    def build(session=None):
        return _page(_Collection, rf, session)

    return build


#: Real uuids, because a collection's routes match `<uuid:item>` and a row
#: has to be able to reverse its own links.
ITEM_A = "11111111-1111-1111-1111-111111111111"
ITEM_B = "22222222-2222-2222-2222-222222222222"
ITEM_C = "33333333-3333-3333-3333-333333333333"
RUN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _seed(items=(), declared_done=False, key="guests"):
    return {
        "collections": {
            key: {
                "items": [{"id": i, "title": t} for i, t in items],
                "declared_done": declared_done,
            }
        }
    }


def _item_view(rf, cls=None, session=None, item="7", run_id=None):
    path = f"{PAGE}{item}/" + (f"{run_id}/" if run_id else "")
    request = rf.get(path)
    request.session = _session(session or {})
    view = (cls or _ItemViewSet)()
    view.setup(request, item=item)
    return view


# --- the declaration --------------------------------------------------------


def test_a_collection_materialises_its_item_viewset():
    assert issubclass(_ItemViewSet, ItemViewSet)
    assert _ItemViewSet.collection_key == "guests"
    assert _ItemViewSet.url_name == "standalone-guests-item"
    assert _ItemViewSet.hub_url_name == "standalone-guests"
    assert _ItemViewSet.item_title == ("guest", "name")
    assert _ItemViewSet.template_name == "testapp/linear_wizard.html"
    assert _Collection.template_name == "testapp/collection.html"
    assert _Collection.remove_template_name == "testapp/collection_remove.html"


def test_a_collections_pages_can_be_named_on_the_viewset_instead():
    class _OwnPages(_Collection):
        template_name = "testapp/hub.html"
        remove_template_name = None

    assert _OwnPages.template_name == "testapp/hub.html"
    assert _OwnPages.remove_template_name is None


def test_a_hub_builds_a_collection_beneath_itself():
    class _Party(HubViewSet):
        url_name = "party-hub"
        hub = Hub().collection("guests", GUESTS, title="Guests")

    viewset = _Party.viewset_for("guests")

    assert issubclass(viewset, CollectionViewSet)
    assert viewset.member_key == "guests"
    assert viewset.url_name == "party-hub-guests"
    assert viewset.hub_url_name == "party-hub"
    assert viewset.item_viewset.collection_key == "guests"


def test_a_hub_can_declare_a_collection_from_a_wizard_and_its_options():
    class _Party(HubViewSet):
        url_name = "party-hub"
        hub = Hub().collection(
            "guests",
            GUESTS.wizard,
            min_items=2,
            item_name="Guest",
            item_title=("guest", "name"),
        )

    assert _Party.viewset_for("guests").collection == replace(
        GUESTS, min_items=2, template_name=None, remove_template_name=None
    )


def test_a_hub_names_the_base_its_collections_are_built_on():
    class _Base(CollectionViewSet):
        pass

    class _Party(HubViewSet):
        url_name = "party-hub"
        collection_viewset_class = _Base
        hub = Hub().collection("guests", GUESTS)

    assert issubclass(_Party.viewset_for("guests"), _Base)


def test_a_nested_collection_is_keyed_under_its_hubs_prefix():
    class _Root(HubViewSet):
        url_name = "readme-apply"
        hub = Hub().hub("supporting", Hub().collection("guests", GUESTS))

    viewset = _Root.viewset_for("supporting").viewset_for("guests")

    assert viewset.member_key == "supporting:guests"
    assert viewset.item_viewset.collection_key == "supporting:guests"


# --- the add-another question ----------------------------------------------


def test_the_question_has_to_be_answered_before_it_means_anything():
    form = AddAnotherForm(data={})

    assert not form.is_valid()
    assert form.errors["add_another"] == ["Select yes if you want to add another"]


@pytest.mark.parametrize(("answer", "wants_another"), [("yes", True), ("no", False)])
def test_the_question_reads_back_as_whether_the_user_wants_one_more(
    answer, wants_another
):
    form = AddAnotherForm(data={"add_another": answer})

    assert form.is_valid()
    assert form.wants_another is wants_another


# --- how far the whole thing has got ---------------------------------------


def test_a_collection_nobody_has_added_to_has_not_started(collection):
    assert collection().get_collection().status == NOT_STARTED


def test_a_collection_with_items_the_user_has_not_signed_off_is_incomplete(
    collection,
):
    """Every item can be finished and the collection still not be — only the
    user can say there are no more."""
    page = collection(
        _seed(items=[(ITEM_A, "Ada")]) | {"stashes": {f"guests:{ITEM_A}": {}}}
    )

    assert page.get_collection().status == INCOMPLETE


def test_a_declared_collection_whose_items_are_all_finished_is_complete(collection):
    page = collection(
        _seed(items=[(ITEM_A, "Ada")], declared_done=True)
        | {"stashes": {f"guests:{ITEM_A}": {}}}
    )

    assert page.get_collection().status == COMPLETE


def test_a_declared_collection_with_an_unfinished_item_is_incomplete(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    assert page.get_collection().status == INCOMPLETE


def test_an_empty_declared_collection_is_complete_when_none_are_required(collection):
    """Which is right for "any other income?" — the honest answer is none."""
    page = collection(_seed(declared_done=True))

    assert page.get_collection().status == COMPLETE


def test_an_empty_declared_collection_is_incomplete_when_one_is_required(rf):
    class _AtLeastOne(_Collection):
        collection = replace(GUESTS, min_items=1)

    page = _page(_AtLeastOne, rf, _seed(declared_done=True))

    assert page.get_collection().status == INCOMPLETE


def test_the_collection_reports_its_own_shape_to_a_template(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada"), (ITEM_B, None)]))

    result = page.get_collection()

    assert isinstance(result, CollectionPage)
    assert result.count == 2
    assert result.is_empty is False
    assert (result.is_not_started, result.is_incomplete, result.is_complete) == (
        False,
        True,
        False,
    )
    assert result.declared_done is False
    assert result.url == PAGE
    assert result.key == "guests"


def test_an_empty_collection_says_so(collection):
    result = collection().get_collection()

    assert result.is_empty is True
    assert result.count == 0
    assert result.is_not_started is True


def test_the_collection_counts_its_items_the_way_a_hub_counts_its_members(
    collection,
):
    """ "2 of 3 guests finished" is the page's own heading, and deriving it in
    the template means the loop the `HubPage` counts exist to remove."""
    page = collection(
        _seed(items=[(ITEM_A, "Ada"), (ITEM_B, "Grace"), (ITEM_C, None)])
        | {"stashes": {f"guests:{ITEM_A}": {}, f"guests:{ITEM_B}": {}}}
    )

    result = page.get_collection()

    assert isinstance(result, HubPage)
    assert (result.count, result.completed, result.remaining) == (3, 2, 1)
    assert result.blocked == 0


def test_an_item_the_user_cannot_start_yet_is_counted_as_blocked(rf):
    """The hook is the hub's, and a collection inherits it — so the counts
    have to answer for it too. Every item shares one declaration, so the
    row is what tells them apart."""

    class _Locked(_Collection):
        def member_blocked(self, member, store):
            return member.key == ITEM_B

    page = _page(
        _Locked,
        rf,
        _seed(items=[(ITEM_A, "Ada"), (ITEM_B, "Grace")])
        | {"stashes": {f"guests:{ITEM_A}": {}, f"guests:{ITEM_B}": {}}},
    )

    result = page.get_collection()

    assert (result.count, result.completed, result.blocked) == (2, 1, 1)
    assert result.remaining == 1
    assert page.enter(page.get_item(ITEM_B)) is None


def test_a_locked_item_is_refused_at_the_door_and_an_open_one_is_not(rf):
    class _Locked(_Collection):
        def member_blocked(self, member, store):
            return member.key == ITEM_B

    page = _page(_Locked, rf, _seed(items=[(ITEM_A, None), (ITEM_B, None)]))

    assert page.enter(page.get_item(ITEM_B)) is None
    assert page.enter(page.get_item(ITEM_A)).startswith(f"{PAGE}{ITEM_A}/")


def test_a_collection_can_hide_its_items_one_by_one(rf):
    """`member_hidden()` reaches a collection through the same seam
    `member_blocked()` does."""

    class _Hiding(_Collection):
        def member_hidden(self, member, store):
            return member.key == ITEM_B

    page = _page(_Hiding, rf, _seed(items=[(ITEM_A, "Ada"), (ITEM_B, "Grace")]))

    assert [row.item_id for row in page.get_collection().rows] == [ITEM_A]


def test_the_collection_says_how_many_items_it_needs(rf):
    """A page that asks for at least one has to be able to say so."""

    class _AtLeastTwo(_Collection):
        collection = replace(GUESTS, min_items=2)

    assert _page(_AtLeastTwo, rf).get_collection().min_items == 2
    assert _page(_Collection, rf).get_collection().min_items == 0


# --- what an item is called -------------------------------------------------


def test_an_item_is_named_by_the_title_its_own_member_cached(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada Lovelace")]))

    (row,) = page.get_collection().rows

    assert row.title == "Ada Lovelace"
    assert row.item_id == ITEM_A
    assert row.position == 0


def test_an_item_that_has_never_finished_is_named_by_its_position(collection):
    page = collection(_seed(items=[(ITEM_A, None), (ITEM_B, None)]))

    rows = page.get_collection().rows

    assert [str(row.title) for row in rows] == ["Guest 1", "Guest 2"]


def test_an_item_name_is_derived_from_the_collection_key_by_default(rf):
    class _Unnamed(_Collection):
        collection = replace(GUESTS, item_name=None)

    class _Nested(_Unnamed):
        member_key = "party:guests"

    for cls, key in ((_Unnamed, "guests"), (_Nested, "party:guests")):
        page = _page(cls, rf, _seed(items=[(ITEM_A, None)], key=key))
        assert str(page.get_collection().rows[0].title) == "Guest 1"


def test_a_row_carries_both_links_a_crud_list_needs(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    (row,) = page.get_collection().rows

    assert row.url == f"{PAGE}{ITEM_A}/"
    assert row.remove_url == f"{PAGE}{ITEM_A}/remove/"


def test_a_collections_rows_are_also_its_members_rows(collection):
    """So a template written for a hub reads a collection unchanged."""
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    context = page.get_context_data()

    assert list(page.get_member_rows()) == list(context["collection"].rows)
    assert isinstance(context["collection"].rows[0], CollectionRow)
    assert isinstance(context["form"], AddAnotherForm)


def test_a_collection_page_publishes_no_hub_beside_its_collection(collection):
    """Two statuses derived two ways would be on the one page: a collection is
    complete when the user says there are no more, which no count of rows can
    tell you."""
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    assert "hub" not in page.get_context_data()


# --- the actions ------------------------------------------------------------


def test_adding_an_item_registers_it_before_entering_its_wizard(collection):
    """Write the durable fact, then do the thing that can fail — so a failure
    leaves a listed, removable row rather than an orphan run."""
    page = collection()

    page.add_item()

    store = SessionCollectionStore(page.request, "default")
    (item_id,) = store.item_ids("guests")
    assert store.get_run(f"guests:{item_id}") is not None


def test_adding_an_item_withdraws_the_users_answer(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    page.add_item()

    assert (
        SessionCollectionStore(page.request, "default").is_declared_done("guests")
        is False
    )


def test_declaring_no_more_records_the_answer_and_moves_the_user_on(collection):
    page = collection(
        _seed(items=[(ITEM_A, "Ada")]) | {"stashes": {f"guests:{ITEM_A}": {}}}
    )

    response = page.declare_done()

    assert (
        SessionCollectionStore(page.request, "default").is_declared_done("guests")
        is True
    )
    assert response.status_code == 302
    assert response["Location"] == "/party/"


def test_removing_an_item_destroys_the_pointer_last(collection):
    """The mirror of `MemberViewSet.done()`: a hook that raises leaves the
    item still listed and still removable."""
    events = []

    class _Failing(_Collection):
        def item_removed(self, item_id, member, store):
            events.append(
                (
                    store.get_item_title("guests", item_id),
                    store.has_item("guests", item_id),
                )
            )
            raise RuntimeError("nope")

    page = _Failing()
    page.setup(collection(_seed(items=[(ITEM_A, "Ada")])).request)

    with pytest.raises(RuntimeError):
        page.remove_item(ITEM_A)

    store = SessionCollectionStore(page.request, "default")
    assert events == [(None, True)]
    assert store.item_ids("guests") == [ITEM_A]


def test_removing_an_item_leaves_the_users_answer_alone(collection):
    """Removal answers no question — three guests minus one is still "and no
    more"."""
    page = collection(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    page.remove_item(ITEM_A)

    assert (
        SessionCollectionStore(page.request, "default").is_declared_done("guests")
        is True
    )


def test_discarding_a_run_the_storage_has_forgotten_is_not_an_error(collection):
    page = collection(
        _seed(items=[(ITEM_A, "Ada")]) | {"runs": {f"guests:{ITEM_A}": "gone"}}
    )

    page.remove_item(ITEM_A)

    assert SessionCollectionStore(page.request, "default").item_ids("guests") == []


def test_an_item_id_the_registry_does_not_list_is_refused(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    assert page.get_item(ITEM_A).key == ITEM_A
    assert page.full_key(page.get_item(ITEM_A)) == f"guests:{ITEM_A}"
    with pytest.raises(ItemNotFound):
        page.get_item(ITEM_B)


def test_an_unavailable_item_is_sent_back_to_the_page(collection):
    response = collection().member_unavailable("nope")

    assert response.status_code == 302
    assert response["Location"] == PAGE


def test_item_ids_are_opaque_and_unique(collection):
    page = collection()

    assert page.new_item_id() != page.new_item_id()


# --- an item's own viewset --------------------------------------------------


def test_an_item_keys_itself_from_the_url(rf):
    view = _item_view(rf)

    assert view.get_member_key() == "guests:7"


def test_every_item_of_a_collection_stamps_one_label(rf):
    """One shape, one label, however many items wear it — a per-item uuid in
    the stash would make the deploy guard match nothing."""
    view = _item_view(rf)

    assert view.get_member_label() == "guests"


def test_a_collections_item_label_moves_with_its_items(rf):
    """One declaration carries the label, so the stamp and the check cannot
    drift apart."""

    class _Reshaped(_Collection):
        collection = replace(GUESTS, label="guests-v2")

    page = _page(_Reshaped, rf, _seed(items=[(ITEM_A, "Ada")]))
    view = _item_view(rf, cls=_Reshaped.item_viewset)

    assert page.get_item_label() == "guests-v2"
    assert page.stash_label(page.get_item_member(ITEM_A)) == "guests-v2"
    assert view.get_member_label() == "guests-v2"


def test_a_finished_item_returns_to_its_collection_without_its_own_id(rf):
    view = _item_view(rf)

    assert view.get_hub_url() == PAGE


def test_an_item_caches_the_answer_that_names_it(rf):
    view = _item_view(
        rf,
        session={
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
            "collections": {
                "guests": {
                    "items": [{"id": "7", "title": None}],
                    "declared_done": False,
                }
            },
        },
        run_id="run-1",
    )

    view.done(_ItemViewSet.inspect(view.request, "run-1", item="7"))

    store = SessionCollectionStore(WizardContext.from_request(view.request), "default")
    assert store.get_item_title("guests", "7") == "Ada"
    assert store.get_stash("guests:7")["label"] == "guests"


def test_an_item_can_be_named_by_a_callable_of_its_run(rf):
    class _Callable(_Collection):
        collection = replace(
            GUESTS,
            item_title=lambda bound_wizard: bound_wizard.get_state()[0]["step"][
                "name"
            ].upper(),
        )

    view = _item_view(
        rf,
        cls=_Callable.item_viewset,
        session={"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        run_id="run-1",
    )

    bound_wizard = _Callable.item_viewset.inspect(view.request, "run-1", item="7")

    assert view.get_item_title(bound_wizard) == "ADA"


def test_the_declared_done_runs_when_an_item_finishes(rf):
    seen = []

    class _Deciding(_Collection):
        collection = replace(
            GUESTS,
            done=lambda store, bound_wizard: seen.append(
                bound_wizard.context.url_kwargs["item"]
            ),
        )

    view = _item_view(
        rf,
        cls=_Deciding.item_viewset,
        session={
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
            "collections": {
                "guests": {
                    "items": [{"id": "7", "title": None}],
                    "declared_done": False,
                }
            },
        },
        run_id="run-1",
    )

    view.done(_Deciding.item_viewset.inspect(view.request, "run-1", item="7"))

    assert seen == ["7"]


def test_an_item_whose_naming_step_is_off_the_route_falls_back(rf):
    """A branch the user did not take names nothing, so the row is honest and
    numbers itself instead."""

    class _Elsewhere(_Collection):
        collection = replace(GUESTS, item_title=("not-on-this-route", "name"))

    view = _item_view(
        rf,
        cls=_Elsewhere.item_viewset,
        session={"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        run_id="run-1",
    )

    bound_wizard = _Elsewhere.item_viewset.inspect(view.request, "run-1", item="7")
    assert view.get_item_title(bound_wizard) == ""


def test_a_removed_items_wizard_sends_the_user_back_to_the_collection(rf):
    """Never to its own start URL, which would mint a fresh run for an item
    no row lists."""
    view = _item_view(rf)

    response = view.run_unavailable(None, reason="unknown")

    assert response.status_code == 302
    assert response["Location"] == PAGE


def test_an_item_wizard_refuses_a_request_for_an_item_that_is_gone(rf):
    request = rf.get(f"{PAGE}7/")
    request.session = _session()

    response = _ItemViewSet.as_view()(request, item="7")

    assert response.status_code == 302
    assert response["Location"] == PAGE


# --- misconfiguration -------------------------------------------------------


def test_a_collection_without_a_key_is_misconfigured():
    with pytest.raises(ImproperlyConfigured, match="member_key"):
        type("_Keyless", (_Collection,), {"member_key": None})


def test_a_collection_without_a_declaration_is_misconfigured(rf):
    class _Undeclared(CollectionViewSet):
        url_name = "standalone-guests"
        member_key = "guests"

    with pytest.raises(ImproperlyConfigured, match="collection"):
        _page(_Undeclared, rf).get_collection()


def test_a_collection_listed_by_no_hub_is_a_root_and_needs_a_journey_done(rf):
    """No `hub_url_name` means nothing above: Continue is then the journey's
    submit, and a root with nothing to do at submit is misconfigured — the
    same refusal a root hub gives."""

    class _Endless(_Collection):
        hub_url_name = None

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        _page(_Endless, rf).declare_done()


def test_a_collection_without_a_url_name_is_misconfigured(collection):
    page = collection()
    page.url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        page.get_page_url()
    with pytest.raises(ImproperlyConfigured, match="url_name"):
        page.get_item_url(ITEM_A)
    with pytest.raises(ImproperlyConfigured, match="url_name"):

        class _NamelessView(CollectionViewSet):
            url_name = None

        _NamelessView.urls()


def test_an_item_wizard_without_a_collection_key_is_misconfigured(rf):
    class _Homeless(_ItemViewSet):
        collection_key = None

    view = _item_view(rf, cls=_Homeless)

    with pytest.raises(ImproperlyConfigured, match="collection"):
        view.get_member_key()


def test_an_item_wizard_not_mounted_under_an_item_segment_is_misconfigured(rf):
    view = _ItemViewSet()
    view.setup(rf.get(PAGE))

    with pytest.raises(ImproperlyConfigured, match="item segment"):
        view.get_item_id()


def test_an_item_wizard_without_a_collection_url_is_misconfigured(rf):
    class _Adrift(_ItemViewSet):
        hub_url_name = None

    view = _item_view(rf, cls=_Adrift)

    with pytest.raises(ImproperlyConfigured, match="hub_url_name"):
        view.get_hub_url()


def test_an_item_wizard_that_cannot_name_its_items_is_misconfigured(rf):
    class _Anonymous(_Collection):
        collection = replace(GUESTS, item_title=None)

    view = _item_view(
        rf,
        cls=_Anonymous.item_viewset,
        session={"gandalf_runs": {"run-1": {"state": []}}},
        run_id="run-1",
    )

    with pytest.raises(ImproperlyConfigured, match="item_title"):
        view.get_item_title(
            _Anonymous.item_viewset.inspect(view.request, "run-1", item="7")
        )


def test_a_collection_view_needs_a_remove_template_to_confirm_with(rf):
    class _Blunt(_Collection):
        remove_template_name = None

    request = rf.get(f"{PAGE}a/remove/")
    view = _Blunt()
    view.setup(request)
    view.request.resolver_match = type(
        "_Match", (), {"url_name": "standalone-guests-remove"}
    )()

    with pytest.raises(ImproperlyConfigured, match="remove_template_name"):
        view.get_template_names()


# --- the view over its three routes -----------------------------------------


KEY = "standalone-guests"


def _view_request(rf, method="get", path=PAGE, data=None, session=None):
    request = getattr(rf, method)(path, data=data or {})
    request.session = _session(session or {})
    return request


def _resolved(request, url_name):
    """Stand in for the URLconf's own resolution, which the view reads to
    tell its page route from its remove route."""
    request.resolver_match = type("_Match", (), {"url_name": url_name})()
    return request


def test_the_page_route_renders_the_collection(rf):
    request = _view_request(rf, session=_seed(items=[(ITEM_A, "Ada")], key=KEY))

    response = GuestCollectionViewSet.as_view()(request)

    assert response.status_code == 200
    assert response.context_data["collection"].count == 1
    assert response.template_name == ["testapp/collection.html"]


def test_the_page_route_registers_an_item_and_redirects_into_its_wizard(rf):
    request = _view_request(rf, "post", data={"add_another": "yes"})

    response = GuestCollectionViewSet.as_view()(request)

    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    (item_id,) = store.item_ids(KEY)
    assert response.status_code == 302
    assert response["Location"].startswith(f"{PAGE}{item_id}/")
    assert response["Location"].endswith("/guest/")


def test_an_unanswered_question_re_renders_the_page(rf):
    request = _view_request(rf, "post", session=_seed(items=[(ITEM_A, "Ada")], key=KEY))

    response = GuestCollectionViewSet.as_view()(request)

    assert response.status_code == 200
    assert response.context_data["form"].errors["add_another"] == [
        "Select yes if you want to add another"
    ]


def test_answering_no_records_it_and_moves_the_user_on(rf):
    request = _view_request(
        rf,
        "post",
        data={"add_another": "no"},
        session=_seed(items=[(ITEM_A, "Ada")], key=KEY)
        | {"stashes": {f"{KEY}:{ITEM_A}": {}}},
    )

    response = GuestCollectionViewSet.as_view()(request)

    assert response["Location"] == "/party/"
    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.is_declared_done(KEY) is True


def test_the_item_route_enters_the_item_it_names(rf):
    request = _view_request(
        rf, path=f"{PAGE}{ITEM_A}/", session=_seed(items=[(ITEM_A, "Ada")], key=KEY)
    )

    response = GuestCollectionViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 302
    assert response["Location"].startswith(f"{PAGE}{ITEM_A}/")


def test_the_item_route_declines_an_item_the_collection_has_locked(rf):
    """An app may gate its items too. The door then has nothing to hand back,
    and sends the user to the page rather than redirecting to `None`."""
    request = _view_request(
        rf,
        path=f"/locked-guests/{ITEM_A}/",
        session=_seed(items=[(ITEM_A, "Ada")], key="locked-guests"),
    )

    response = LockedGuestCollectionViewSet.as_view()(request, item=ITEM_A)

    assert response["Location"] == "/locked-guests/"


def test_adding_to_a_locked_collection_still_registers_the_item(rf):
    """`add_item()` writes the durable fact before it enters, so the user is
    left with a listed, removable row and the page they pressed Add on."""
    request = _view_request(
        rf, "post", path="/locked-guests/", data={"add_another": "yes"}
    )

    response = LockedGuestCollectionViewSet.as_view()(request)

    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert response["Location"] == "/locked-guests/"
    assert len(store.item_ids("locked-guests")) == 1


def test_the_remove_route_asks_before_it_destroys_anything(rf):
    request = _resolved(
        _view_request(
            rf,
            path=f"{PAGE}{ITEM_A}/remove/",
            session=_seed(items=[(ITEM_A, "Ada")], key=KEY),
        ),
        "standalone-guests-remove",
    )

    response = GuestCollectionViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 200
    assert response.template_name == ["testapp/collection_remove.html"]
    assert response.context_data["row"].title == "Ada"
    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.item_ids(KEY) == [ITEM_A]


def test_posting_to_the_remove_route_destroys_the_item(rf):
    request = _resolved(
        _view_request(
            rf,
            "post",
            path=f"{PAGE}{ITEM_A}/remove/",
            session=_seed(items=[(ITEM_A, "Ada")], key=KEY),
        ),
        "standalone-guests-remove",
    )

    response = GuestCollectionViewSet.as_view()(request, item=ITEM_A)

    assert response["Location"] == PAGE
    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.item_ids(KEY) == []


def test_removing_an_item_reclaims_whatever_its_run_was_holding(rf):
    """The run is obliterated — state and uploaded bytes — before the
    pointers to it go."""
    request = _resolved(
        _view_request(
            rf,
            "post",
            path=f"{PAGE}{ITEM_A}/remove/",
            session=_seed(items=[(ITEM_A, None)], key=KEY)
            | {
                "runs": {f"{KEY}:{ITEM_A}": "run-1"},
                "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
            },
        ),
        "standalone-guests-remove",
    )

    GuestCollectionViewSet.as_view()(request, item=ITEM_A)

    assert "run-1" not in request.session["gandalf_runs"]


def test_a_door_naming_an_unlisted_item_is_sent_back_to_the_page(rf):
    request = _resolved(
        _view_request(rf, path=f"{PAGE}{ITEM_B}/"), "standalone-guests-item"
    )

    response = GuestCollectionViewSet.as_view()(request, item=ITEM_B)

    assert response.status_code == 302
    assert response["Location"] == PAGE


def test_removing_an_unlisted_item_is_sent_back_to_the_page(rf):
    request = _resolved(
        _view_request(rf, "post", path=f"{PAGE}{ITEM_B}/remove/"),
        "standalone-guests-remove",
    )

    response = GuestCollectionViewSet.as_view()(request, item=ITEM_B)

    assert response.status_code == 302
    assert response["Location"] == PAGE


def test_posting_to_an_items_door_removes_nothing(rf):
    """The door and the remove route both carry an item id, and only one of
    them destroys anything (#101). A form posting to the URL a row links to
    used to take the item with it."""
    request = _resolved(
        _view_request(
            rf,
            "post",
            path=f"{PAGE}{ITEM_A}/",
            session=_seed(items=[(ITEM_A, "Ada")], key=KEY),
        ),
        "standalone-guests-item",
    )

    response = GuestCollectionViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 405
    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.item_ids(KEY) == [ITEM_A]


def test_a_collection_publishes_its_page_an_item_a_remove_and_the_item_wizard():
    """The item wizard is mounted beneath the door for its item, minus the
    bare start URL the door already stands in for."""
    page, door, remove, wizard = GuestCollectionViewSet.urls()

    assert [pattern.name for pattern in (page, door, remove)] == [
        "standalone-guests",
        "standalone-guests-item",
        "standalone-guests-remove",
    ]
    assert [str(pattern.pattern) for pattern in (page, door, remove, wizard)] == [
        "",
        "<uuid:item>/",
        "<uuid:item>/remove/",
        "<uuid:item>/",
    ]
    assert [p.name for p in wizard.url_patterns] == [
        "standalone-guests-item-run",
        "standalone-guests-item-step",
    ]


def test_a_collection_reports_its_status_to_a_parent_task_list(rf):
    """A collection is a hub, so a parent lists it as a member like any
    other, and asks `status_for()` — the collection's own status, which no
    stash key could express."""
    request = _view_request(
        rf,
        path="/party/",
        session=_seed(items=[(ITEM_A, "Ada")], declared_done=True, key=KEY)
        | {"stashes": {f"{KEY}:{ITEM_A}": {}}},
    )
    member = Member("guests", GuestCollectionViewSet, title="Guests")

    assert HubViewSet.is_hub(member)
    assert GuestCollectionViewSet.status_for(request, {}) == COMPLETE


def test_an_item_wizard_serves_a_request_for_an_item_the_registry_lists(rf):
    request = _view_request(
        rf,
        path=f"{PAGE}{ITEM_A}/{RUN}/",
        session=_seed(items=[(ITEM_A, None)], key=KEY),
    )

    response = GuestCollectionViewSet.item_viewset.as_view()(
        request, item=ITEM_A, run_id=RUN
    )

    # A run the storage has never seen: back to the collection page.
    assert response.status_code == 302
    assert response["Location"] == PAGE


# --- the journey -------------------------------------------------------------


def test_a_collection_keeps_its_registry_under_its_journey(rf):
    class _Journeyed(_Collection):
        journey = "app-1"

    request = rf.get(PAGE)
    request.session = _session(_seed(items=[(ITEM_A, "Ada")]), journey="app-1")

    assert _Journeyed.item_viewset.journey == "app-1"
    assert _page(_Collection, rf).get_collection().count == 0
    page = _Journeyed()
    page.setup(request)
    assert page.get_collection().count == 1


def test_a_collection_reports_its_status_under_its_own_journey(rf):
    """`status_for()` answers for the journey the collection is on."""

    class _Journeyed(GuestCollectionViewSet):
        journey = "app-1"

    request = _view_request(
        rf,
        path="/party/",
        session=_session(
            _seed(items=[(ITEM_A, "Ada")], declared_done=True, key=KEY)
            | {"stashes": {f"{KEY}:{ITEM_A}": {}}},
            journey="app-1",
        ),
    )

    assert _Journeyed.status_for(request, {}) == COMPLETE
    assert GuestCollectionViewSet.status_for(request, {}) == NOT_STARTED


def test_a_collection_under_a_submitted_journey_sends_the_user_on(rf):
    """The hub above it is the page that can say what a submitted journey
    looks like; a collection has no page of its own for that."""
    request = _view_request(rf, session={"completed": True})

    response = GuestCollectionViewSet.as_view()(request)

    assert response.status_code == 302
    assert response["Location"] == "/party/"
