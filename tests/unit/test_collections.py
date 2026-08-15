"""Unit coverage for the add-another layer.

A collection is a hub whose sections are built from an ordered registry rather
than declared, so most of its behaviour is `HubMixin`'s and is covered there.
What is genuinely its own: how far the whole thing has got, what an item is
called, what the four actions do in what order, and what it refuses to be
configured as.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf.collections import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnotherForm,
    CollectionMixin,
    CollectionRow,
    CollectionView,
    ItemNotFound,
    ItemSectionMixin,
)
from gandalf.storage import SessionCollectionStore
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from tests.testapp.forms import GuestForm
from tests.testapp.views import GuestCollectionView, GuestItemViewSet


class _Session(dict):
    modified = False


class _ItemViewSet(ItemSectionMixin, WizardViewSet):
    url_name = "party-guest"
    template_name = "testapp/linear_wizard.html"
    collection_key = "guests"
    collection_url_name = "party-guests"
    item_title_step = "guest"
    item_title_field = "name"
    wizard = Wizard().step(GuestForm, name="guest")


class _TemplateView:
    """Stands in for the Django view a collection is mixed into."""

    def get_context_data(self, **kwargs):
        return dict(kwargs)


class _Collection(CollectionMixin, _TemplateView):
    url_name = "party-guests"
    collection_key = "guests"
    item_viewset = _ItemViewSet
    item_name = "Guest"
    continue_url_name = "party-hub"

    def __init__(self, request, **kwargs):
        self.request = request
        self.kwargs = kwargs


@pytest.fixture
def collection(rf):
    def build(session=None):
        request = rf.get("/party-guests/")
        request.session = _Session(session or {})
        return _Collection(request)

    return build


#: Real uuids, because a collection's routes match `<uuid:item>` and a row
#: has to be able to reverse its own links.
ITEM_A = "11111111-1111-1111-1111-111111111111"
ITEM_B = "22222222-2222-2222-2222-222222222222"


def _seed(items=(), declared_done=False):
    return {
        "gandalf_collections": {
            "guests": {
                "items": [{"id": i, "title": t} for i, t in items],
                "declared_done": declared_done,
            }
        }
    }


def _bound(request, run_id="run-1"):
    return _ItemViewSet.inspect(request, run_id)


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
        _seed(items=[(ITEM_A, "Ada")]) | {"gandalf_stashes": {f"guests:{ITEM_A}": {}}}
    )

    assert page.get_collection().status == INCOMPLETE


def test_a_declared_collection_whose_items_are_all_finished_is_complete(collection):
    page = collection(
        _seed(items=[(ITEM_A, "Ada")], declared_done=True)
        | {"gandalf_stashes": {f"guests:{ITEM_A}": {}}}
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
        min_items = 1

    request = rf.get("/party-guests/")
    request.session = _Session(_seed(declared_done=True))

    assert _AtLeastOne(request).get_collection().status == INCOMPLETE


def test_the_collection_reports_its_own_shape_to_a_template(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada"), (ITEM_B, None)]))

    result = page.get_collection()

    assert result.count == 2
    assert result.is_empty is False
    assert (result.is_not_started, result.is_incomplete, result.is_complete) == (
        False,
        True,
        False,
    )
    assert result.declared_done is False


def test_an_empty_collection_says_so(collection):
    result = collection().get_collection()

    assert result.is_empty is True
    assert result.count == 0
    assert result.is_not_started is True


# --- what an item is called -------------------------------------------------


def test_an_item_is_named_by_the_title_its_own_section_cached(collection):
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
        item_name = None

    request = rf.get("/party-guests/")
    request.session = _Session(_seed(items=[(ITEM_A, None)]))

    assert str(_Unnamed(request).get_collection().rows[0].title) == "Guest 1"


def test_a_row_carries_both_links_a_crud_list_needs(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    (row,) = page.get_collection().rows

    assert row.url.endswith(f"/{ITEM_A}/")
    assert row.remove_url.endswith(f"/{ITEM_A}/remove/")


def test_a_collections_rows_are_also_its_sections_rows(collection):
    """So a template written for a hub reads a collection unchanged."""
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    context = page.get_context_data()

    assert context["sections"] == list(context["collection"].rows)
    assert isinstance(context["sections"][0], CollectionRow)
    assert isinstance(context["form"], AddAnotherForm)


# --- the actions ------------------------------------------------------------


def test_adding_an_item_registers_it_before_entering_its_wizard(collection):
    """Write the durable fact, then do the thing that can fail — so a failure
    leaves a listed, removable row rather than an orphan run."""
    page = collection()

    page.add_item()

    store = SessionCollectionStore(page.request)
    (item_id,) = store.item_ids("guests")
    assert store.get_run(f"guests:{item_id}") is not None


def test_adding_an_item_withdraws_the_users_answer(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    page.add_item()

    assert SessionCollectionStore(page.request).is_declared_done("guests") is False


def test_declaring_no_more_records_the_answer_and_moves_the_user_on(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    response = page.declare_done()

    assert SessionCollectionStore(page.request).is_declared_done("guests") is True
    assert response.status_code == 302
    assert response["Location"] == "/party/"


def test_removing_an_item_destroys_the_pointer_last(collection):
    """The mirror of `SectionMixin.done()`: a hook that raises leaves the item
    still listed and still removable."""
    events = []

    class _Failing(_Collection):
        def item_removed(self, item_id, section, store):
            events.append(
                (
                    store.get_item_title("guests", item_id),
                    store.has_item("guests", item_id),
                )
            )
            raise RuntimeError("nope")

    page = _Failing(collection(_seed(items=[(ITEM_A, "Ada")])).request)

    with pytest.raises(RuntimeError):
        page.remove_item(ITEM_A)

    store = SessionCollectionStore(page.request)
    assert events == [(None, True)]
    assert store.item_ids("guests") == [ITEM_A]


def test_removing_an_item_leaves_the_users_answer_alone(collection):
    """Removal answers no question — three guests minus one is still "and no
    more"."""
    page = collection(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    page.remove_item(ITEM_A)

    assert SessionCollectionStore(page.request).is_declared_done("guests") is True


def test_discarding_a_run_the_storage_has_forgotten_is_not_an_error(collection):
    page = collection(
        _seed(items=[(ITEM_A, "Ada")])
        | {"gandalf_section_runs": {f"guests:{ITEM_A}": "gone"}}
    )

    page.remove_item(ITEM_A)

    assert SessionCollectionStore(page.request).item_ids("guests") == []


def test_an_item_id_the_registry_does_not_list_is_refused(collection):
    page = collection(_seed(items=[(ITEM_A, "Ada")]))

    assert page.get_item(ITEM_A).key == f"guests:{ITEM_A}"
    with pytest.raises(ItemNotFound):
        page.get_item(ITEM_B)


def test_an_unavailable_item_is_sent_back_to_the_page(collection):
    response = collection().item_unavailable("nope")

    assert response.status_code == 302
    assert response["Location"] == "/party-guests/"


def test_item_ids_are_opaque_and_unique(collection):
    page = collection()

    assert page.new_item_id() != page.new_item_id()


# --- an item's own viewset --------------------------------------------------


def test_an_item_keys_itself_from_the_url(rf):
    view = _ItemViewSet()
    view.setup(rf.get("/party-guest/7/"), item="7")

    assert view.get_section_key() == "guests:7"


def test_every_item_of_a_collection_stamps_one_label(rf):
    """One shape, one label, however many items wear it — a per-item uuid in
    the stash would make the deploy guard match nothing."""
    view = _ItemViewSet()
    view.setup(rf.get("/party-guest/7/"), item="7")

    assert view.get_section_label() == "guests"


def test_a_collections_item_label_can_be_bumped_alongside_its_items(collection):
    """Both halves move together, or the drift check refuses the pair."""

    class _Reshaped(_ItemViewSet):
        section_label = "guests-v2"

    class _ReshapedCollection(_Collection):
        item_viewset = _Reshaped
        item_label = "guests-v2"

    page = _ReshapedCollection(collection(_seed(items=[(ITEM_A, "Ada")])).request)

    assert page.get_item_label() == "guests-v2"
    assert page.get_item_section(ITEM_A).stash_label == "guests-v2"


def test_an_items_label_can_be_bumped_when_its_shape_changes(rf):
    class _Reshaped(_ItemViewSet):
        section_label = "guests-v2"

    view = _Reshaped()
    view.setup(rf.get("/party-guest/7/"), item="7")

    assert view.get_section_label() == "guests-v2"


def test_a_finished_item_returns_to_its_collection_without_its_own_id(rf):
    view = _ItemViewSet()
    view.setup(rf.get("/party-guest/7/"), item="7")

    assert view.get_hub_url() == "/party-guests/"


def test_an_item_caches_the_answer_that_names_it(rf):
    request = rf.get("/party-guest/7/run-1/")
    request.session = _Session(
        {
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
            "gandalf_collections": {
                "guests": {
                    "items": [{"id": "7", "title": None}],
                    "declared_done": False,
                }
            },
        }
    )
    view = _ItemViewSet()
    view.setup(request, item="7")

    view.done(_ItemViewSet.inspect(request, "run-1", item="7"))

    store = SessionCollectionStore(request)
    assert store.get_item_title("guests", "7") == "Ada"
    assert store.get_stash("guests:7")["label"] == "guests"


def test_an_item_whose_naming_step_is_off_the_route_falls_back(rf):
    """A branch the user did not take names nothing, so the row is honest and
    numbers itself instead."""

    class _Elsewhere(_ItemViewSet):
        item_title_step = "not-on-this-route"

    request = rf.get("/party-guest/7/run-1/")
    request.session = _Session(
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    view = _Elsewhere()
    view.setup(request, item="7")

    assert view.get_item_title(_Elsewhere.inspect(request, "run-1", item="7")) == ""


def test_a_removed_items_wizard_sends_the_user_back_to_the_collection(rf):
    """Never to its own start URL, which would mint a fresh run for an item
    no row lists."""
    request = rf.get("/party-guest/7/")
    request.session = _Session()
    view = _ItemViewSet()
    view.setup(request, item="7")

    response = view.run_unavailable(None, reason="unknown")

    assert response.status_code == 302
    assert response["Location"] == "/party-guests/"


def test_an_item_wizard_refuses_a_request_for_an_item_that_is_gone(rf):
    request = rf.get("/party-guest/7/")
    request.session = _Session()

    response = _ItemViewSet.as_view()(request, item="7")

    assert response.status_code == 302
    assert response["Location"] == "/party-guests/"


# --- misconfiguration -------------------------------------------------------


def test_a_collection_without_a_key_is_misconfigured(collection):
    class _Keyless(_Collection):
        collection_key = None

    with pytest.raises(ImproperlyConfigured, match="collection_key"):
        _Keyless(collection().request).get_collection()


def test_a_collection_without_an_item_viewset_is_misconfigured(collection):
    class _Wizardless(_Collection):
        item_viewset = None

    with pytest.raises(ImproperlyConfigured, match="item_viewset"):
        _Wizardless(collection().request).get_collection()


def test_a_collection_without_a_continue_url_is_misconfigured(collection):
    class _Endless(_Collection):
        continue_url_name = None

    with pytest.raises(ImproperlyConfigured, match="continue_url_name"):
        _Endless(collection().request).declare_done()


def test_a_collection_without_a_url_name_is_misconfigured(collection):
    class _Nameless(_Collection):
        url_name = None

    page = _Nameless(collection().request)

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        page.get_collection_url()
    with pytest.raises(ImproperlyConfigured, match="url_name"):
        page.get_item_url(ITEM_A)
    with pytest.raises(ImproperlyConfigured, match="url_name"):

        class _NamelessView(CollectionView):
            url_name = None

        _NamelessView.urls()


def test_an_item_label_that_drifts_from_its_collections_is_rejected(collection):
    """A re-opened item would be refused at the door and could never be
    changed."""

    class _Drifted(_ItemViewSet):
        section_label = "guests-v2"

    class _Mismatched(_Collection):
        item_viewset = _Drifted

    with pytest.raises(ImproperlyConfigured, match="item label must match"):
        _Mismatched(collection().request).get_collection()


def test_an_item_wizard_without_a_collection_key_is_misconfigured(rf):
    class _Homeless(_ItemViewSet):
        collection_key = None

    view = _Homeless()
    view.setup(rf.get("/party-guest/7/"), item="7")

    with pytest.raises(ImproperlyConfigured, match="collection_key"):
        view.get_section_key()


def test_an_item_wizard_not_mounted_under_an_item_segment_is_misconfigured(rf):
    view = _ItemViewSet()
    view.setup(rf.get("/party-guest/"))

    with pytest.raises(ImproperlyConfigured, match="item segment"):
        view.get_item_id()


def test_an_item_wizard_without_a_collection_url_is_misconfigured(rf):
    class _Adrift(_ItemViewSet):
        collection_url_name = None

    view = _Adrift()
    view.setup(rf.get("/party-guest/7/"), item="7")

    with pytest.raises(ImproperlyConfigured, match="collection_url_name"):
        view.get_hub_url()


def test_an_item_wizard_that_cannot_name_its_items_is_misconfigured(rf):
    class _Anonymous(_ItemViewSet):
        item_title_step = None

    request = rf.get("/party-guest/7/run-1/")
    request.session = _Session({"gandalf_runs": {"run-1": {"state": []}}})
    view = _Anonymous()
    view.setup(request, item="7")

    with pytest.raises(ImproperlyConfigured, match="item_title_step"):
        view.get_item_title(_Anonymous.inspect(request, "run-1", item="7"))


def test_a_collection_view_needs_a_remove_template_to_confirm_with(rf):
    class _Blunt(CollectionView):
        url_name = "party-guests"
        collection_key = "guests"
        item_viewset = _ItemViewSet
        remove_template_name = None

    request = rf.get("/party-guests/a/remove/")
    view = _Blunt()
    view.setup(request)
    view.request.resolver_match = type(
        "_Match", (), {"url_name": "party-guests-remove"}
    )()

    with pytest.raises(ImproperlyConfigured, match="remove_template_name"):
        view.get_template_names()


# --- the view over its three routes -----------------------------------------


def _view_request(rf, method="get", path="/party-guests/", data=None, session=None):
    request = getattr(rf, method)(path, data=data or {})
    request.session = _Session(session or {})
    return request


def _resolved(request, url_name):
    """Stand in for the URLconf's own resolution, which the view reads to
    tell its page route from its remove route."""
    request.resolver_match = type("_Match", (), {"url_name": url_name})()
    return request


def test_the_page_route_renders_the_collection(rf):
    request = _view_request(rf, session=_seed(items=[(ITEM_A, "Ada")]))

    response = GuestCollectionView.as_view()(request)

    assert response.status_code == 200
    assert response.context_data["collection"].count == 1
    assert response.template_name == ["testapp/collection.html"]


def test_the_page_route_registers_an_item_and_redirects_into_its_wizard(rf):
    request = _view_request(rf, "post", data={"add_another": "yes"})

    response = GuestCollectionView.as_view()(request)

    (item_id,) = SessionCollectionStore(request).item_ids("guests")
    assert response.status_code == 302
    assert response["Location"].startswith(f"/party-guest/{item_id}/")


def test_an_unanswered_question_re_renders_the_page(rf):
    request = _view_request(rf, "post", session=_seed(items=[(ITEM_A, "Ada")]))

    response = GuestCollectionView.as_view()(request)

    assert response.status_code == 200
    assert response.context_data["form"].errors["add_another"] == [
        "Select yes if you want to add another"
    ]


def test_answering_no_records_it_and_moves_the_user_on(rf):
    request = _view_request(
        rf, "post", data={"add_another": "no"}, session=_seed(items=[(ITEM_A, "Ada")])
    )

    response = GuestCollectionView.as_view()(request)

    assert response["Location"] == "/party/"
    assert SessionCollectionStore(request).is_declared_done("guests") is True


def test_the_item_route_enters_the_item_it_names(rf):
    request = _view_request(
        rf, path=f"/party-guests/{ITEM_A}/", session=_seed(items=[(ITEM_A, "Ada")])
    )

    response = GuestCollectionView.as_view()(request, item=ITEM_A)

    assert response.status_code == 302
    assert response["Location"].startswith(f"/party-guest/{ITEM_A}/")


def test_the_remove_route_asks_before_it_destroys_anything(rf):
    request = _resolved(
        _view_request(
            rf,
            path=f"/party-guests/{ITEM_A}/remove/",
            session=_seed(items=[(ITEM_A, "Ada")]),
        ),
        "party-guests-remove",
    )

    response = GuestCollectionView.as_view()(request, item=ITEM_A)

    assert response.status_code == 200
    assert response.template_name == ["testapp/collection_remove.html"]
    assert response.context_data["row"].title == "Ada"
    assert SessionCollectionStore(request).item_ids("guests") == [ITEM_A]


def test_posting_to_the_remove_route_destroys_the_item(rf):
    request = _view_request(
        rf,
        "post",
        path=f"/party-guests/{ITEM_A}/remove/",
        session=_seed(items=[(ITEM_A, "Ada")]),
    )

    response = GuestCollectionView.as_view()(request, item=ITEM_A)

    assert response["Location"] == "/party-guests/"
    assert SessionCollectionStore(request).item_ids("guests") == []


def test_removing_an_item_reclaims_whatever_its_run_was_holding(rf):
    """The run is obliterated — state and uploaded bytes — before the
    pointers to it go."""
    request = _view_request(
        rf,
        "post",
        path=f"/party-guests/{ITEM_A}/remove/",
        session=_seed(items=[(ITEM_A, None)])
        | {
            "gandalf_section_runs": {f"guests:{ITEM_A}": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        },
    )

    GuestCollectionView.as_view()(request, item=ITEM_A)

    assert "run-1" not in request.session["gandalf_runs"]


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_route_naming_an_unlisted_item_is_sent_back_to_the_page(rf, method):
    request = _view_request(rf, method, path=f"/party-guests/{ITEM_B}/")

    response = GuestCollectionView.as_view()(request, item=ITEM_B)

    assert response.status_code == 302
    assert response["Location"] == "/party-guests/"


def test_a_collection_publishes_a_page_an_item_and_a_remove_pattern():
    patterns = GuestCollectionView.urls()

    assert [pattern.name for pattern in patterns] == [
        "party-guests",
        "party-guests-item",
        "party-guests-remove",
    ]
    assert [str(pattern.pattern) for pattern in patterns] == [
        "",
        "<uuid:item>/",
        "<uuid:item>/remove/",
    ]


def test_a_collection_reports_its_status_to_a_parent_task_list(rf):
    """`as_section()` hands the hub a row that links past its own door and
    answers for itself."""
    request = _view_request(
        rf,
        path="/party/",
        session=_seed(items=[(ITEM_A, "Ada")], declared_done=True)
        | {"gandalf_stashes": {f"guests:{ITEM_A}": {}}},
    )
    section = GuestCollectionView.as_section("guests", title="Guests")

    assert section.viewset is None
    assert section.url_name == "party-guests"
    assert section.status(request) == COMPLETE


def test_an_item_wizard_serves_a_request_for_an_item_the_registry_lists(rf):
    request = _view_request(
        rf,
        path=f"/party-guest/{ITEM_A}/",
        session=_seed(items=[(ITEM_A, None)]),
    )

    response = GuestItemViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 302
    assert f"/party-guest/{ITEM_A}/" in response["Location"]
