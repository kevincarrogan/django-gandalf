"""Unit coverage for the add-another layer.

An add-another page is a task list whose entries are built from an ordered
registry rather than declared, so most of its behaviour is
`TaskListViewSet`'s and is covered there. What is genuinely its own: how
far the whole thing has got, what an item is called, what the four actions
do in what order, and what it refuses to be configured as.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf.add_another import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnotherForm,
    AddAnotherPage,
    AddAnotherViewSet,
    ItemNotFound,
    ItemRow,
    ItemViewSet,
)
from gandalf.context import WizardContext
from gandalf.form_views import StepFormView
from gandalf.storage import SessionCollectionStore
from gandalf.tasklists import (
    AddAnother,
    Group,
    Section,
    TaskList,
    TaskListPage,
    TaskListViewSet,
)
from gandalf.wizard import Wizard, condition

from tests.testapp.forms import GuestForm, NewsletterForm
from tests.testapp.views import GuestsViewSet, LockedGuestsViewSet


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


GUEST = Wizard().step(GuestForm, name="guest")

GUESTS = AddAnother(GUEST, item_name="Guest", item_title="name")


class _Guests(AddAnotherViewSet):
    """Named after the test app's standalone page, so every URL it builds
    reverses through the URLconf rather than being faked."""

    template_name = "testapp/items.html"
    remove_template_name = "testapp/items_remove.html"

    url_name = "standalone-guests"
    key = "guests"
    section_template_name = "testapp/linear_wizard.html"
    add_another = GUESTS
    task_list_url_name = "party-task-list"


_ItemViewSet = _Guests.item_viewset

PAGE = "/standalone-guests/"


def _page(cls, rf, session=None, path=PAGE, method="get", **kwargs):
    request = getattr(rf, method)(path)
    request.session = _session(session or {})
    view = cls()
    view.setup(request, **kwargs)
    return view


@pytest.fixture
def guests(rf):
    def build(session=None):
        return _page(_Guests, rf, session)

    return build


#: Real uuids, because the page's routes match `<uuid:item>` and a row has
#: to be able to reverse its own links.
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


def _list(**entries):
    return type("_List", (TaskList,), entries)


def _view(task_list, **attributes):
    return type(
        "_ViewSet",
        (TaskListViewSet,),
        {"url_name": "party-task-list", "task_list": task_list, **attributes},
    )


# --- the declaration --------------------------------------------------------


def test_an_add_another_builds_its_item_viewset():
    assert issubclass(_ItemViewSet, ItemViewSet)
    assert _ItemViewSet.list_key == "guests"
    assert _ItemViewSet.url_name == "standalone-guests-item"
    assert _ItemViewSet.task_list_url_name == "standalone-guests"
    assert _ItemViewSet.item_title == "name"
    assert _ItemViewSet.template_name == "testapp/linear_wizard.html"
    assert _Guests.template_name == "testapp/items.html"
    assert _Guests.remove_template_name == "testapp/items_remove.html"


def test_a_task_list_hands_its_add_another_pages_to_the_lists_it_builds():
    viewset = _view(
        _list(guests=GUESTS.replace(title="Guests")),
        add_another_template_name="testapp/items.html",
        remove_template_name="testapp/items_remove.html",
    ).viewset_for("guests")

    assert viewset.template_name == "testapp/items.html"
    assert viewset.remove_template_name == "testapp/items_remove.html"


def test_an_add_another_base_that_names_its_own_pages_keeps_them():
    class _Themed(AddAnotherViewSet):
        template_name = "testapp/task_list.html"
        remove_template_name = "testapp/items_remove.html"

    viewset = _view(
        _list(guests=GUESTS.replace(title="Guests")),
        add_another_viewset_class=_Themed,
        add_another_template_name="testapp/items.html",
    ).viewset_for("guests")

    assert viewset.template_name == "testapp/task_list.html"


def test_an_item_name_defaults_to_the_first_steps_label(rf):
    class _Labelled(_Guests):
        add_another = GUESTS.replace(
            wizard=Wizard().step(GuestForm, name="guest", label="Party guest"),
            item_name=None,
        )

    assert _page(_Labelled, rf).get_item_name() == "Party guest"


def test_an_item_title_field_no_step_declares_is_refused():
    with pytest.raises(ImproperlyConfigured, match="'nickname', a field no step"):

        class _Nameless(_Guests):
            add_another = GUESTS.replace(item_title="nickname")


def test_an_item_title_field_two_steps_declare_is_refused():
    with pytest.raises(ImproperlyConfigured, match="steps guest, plus_one all declare"):

        class _Ambiguous(_Guests):
            add_another = GUESTS.replace(
                wizard=Wizard()
                .step(GuestForm, name="guest")
                .step(GuestForm, name="plus_one")
            )


def test_an_item_title_on_a_per_request_item_wizard_is_taken_on_trust(rf):
    class _PerRequest(ItemViewSet):
        def get_wizard(self, run):
            return GUEST

    class _Trusted(_Guests):
        add_another = GUESTS.replace(
            wizard=_PerRequest, item_title="anything", item_name=None
        )

    assert _Trusted.item_viewset.item_title == "anything"
    # And with no declaration to read a label off, the key names an item.
    assert _page(_Trusted, rf).get_item_name() == "Guest"


def test_an_item_title_on_an_expanding_item_wizard_is_taken_on_trust():
    class _Growing(_Guests):
        add_another = GUESTS.replace(
            wizard=GUEST.expand(lambda context: Wizard()), item_title="anything"
        )

    assert _Growing.item_viewset.item_title == "anything"


def test_an_item_title_on_a_step_that_picks_its_form_per_request_is_trusted():
    """What such a step asks cannot be read off the declaration, so the
    field name is taken on trust rather than refused for not being there."""

    class _Undecided(StepFormView):
        template_name = "testapp/linear_wizard.html"

        def get_form_class(self):
            return GuestForm

    class _Trusted(_Guests):
        add_another = GUESTS.replace(
            wizard=Wizard().step(_Undecided, name="guest"), item_title="name"
        )

    assert _Trusted.item_viewset.item_title == "name"


def test_a_task_list_builds_an_add_another_beneath_itself():
    viewset = _view(_list(guests=GUESTS.replace(title="Guests"))).viewset_for("guests")

    assert issubclass(viewset, AddAnotherViewSet)
    assert viewset.key == "guests"
    assert viewset.url_name == "party-task-list-guests"
    assert viewset.task_list_url_name == "party-task-list"
    assert viewset.item_viewset.list_key == "guests"


def test_a_task_list_names_the_base_its_add_anothers_are_built_on():
    class _Base(AddAnotherViewSet):
        pass

    viewset = _view(_list(guests=GUESTS), add_another_viewset_class=_Base).viewset_for(
        "guests"
    )

    assert issubclass(viewset, _Base)


def test_an_add_another_in_a_group_is_keyed_under_the_groups_prefix():
    class _Supporting(TaskList):
        guests = GUESTS

    viewset = (
        _view(_list(supporting=Group(_Supporting)), url_name="readme-apply")
        .viewset_for("supporting")
        .viewset_for("guests")
    )

    assert viewset.key == "supporting:guests"
    assert viewset.item_viewset.list_key == "supporting:guests"


def test_an_item_viewset_in_the_slot_carries_the_items_behaviour():
    class _Saved(ItemViewSet):
        wizard = GUEST

    class _Behaved(_Guests):
        add_another = GUESTS.replace(wizard=_Saved)

    assert issubclass(_Behaved.item_viewset, _Saved)
    assert _Behaved.item_viewset.wizard is GUEST


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


def test_a_page_nobody_has_added_to_has_not_started(guests):
    assert guests().get_items().status == NOT_STARTED


def test_a_page_with_items_the_user_has_not_signed_off_is_incomplete(guests):
    """Every item can be finished and the list still not be — only the user
    can say there are no more."""
    view = guests(
        _seed(items=[(ITEM_A, "Ada")]) | {"stashes": {f"guests:{ITEM_A}": {}}}
    )

    assert view.get_items().status == INCOMPLETE


def test_a_declared_page_whose_items_are_all_finished_is_complete(guests):
    view = guests(
        _seed(items=[(ITEM_A, "Ada")], declared_done=True)
        | {"stashes": {f"guests:{ITEM_A}": {}}}
    )

    assert view.get_items().status == COMPLETE


def test_a_declared_page_with_an_unfinished_item_is_incomplete(guests):
    view = guests(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    assert view.get_items().status == INCOMPLETE


def test_an_empty_declared_page_is_complete_when_none_are_required(guests):
    """Which is right for "any other income?" — the honest answer is none."""
    view = guests(_seed(declared_done=True))

    assert view.get_items().status == COMPLETE


def test_an_empty_declared_page_is_incomplete_when_one_is_required(rf):
    class _AtLeastOne(_Guests):
        add_another = GUESTS.replace(min_items=1)

    view = _page(_AtLeastOne, rf, _seed(declared_done=True))

    assert view.get_items().status == INCOMPLETE


def test_the_page_reports_its_own_shape_to_a_template(guests):
    view = guests(_seed(items=[(ITEM_A, "Ada"), (ITEM_B, None)]))

    result = view.get_items()

    assert isinstance(result, AddAnotherPage)
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


def test_an_empty_page_says_so(guests):
    result = guests().get_items()

    assert result.is_empty is True
    assert result.count == 0
    assert result.is_not_started is True


def test_the_page_counts_its_items_the_way_a_task_list_counts_its_sections(
    guests,
):
    """ "2 of 3 guests finished" is the page's own heading, and deriving it in
    the template means the loop the `TaskListPage` counts exist to remove."""
    view = guests(
        _seed(items=[(ITEM_A, "Ada"), (ITEM_B, "Grace"), (ITEM_C, None)])
        | {"stashes": {f"guests:{ITEM_A}": {}, f"guests:{ITEM_B}": {}}}
    )

    result = view.get_items()

    assert isinstance(result, TaskListPage)
    assert (result.count, result.completed, result.remaining) == (3, 2, 1)
    assert result.blocked == 0


def test_an_item_the_user_cannot_start_yet_is_counted_as_blocked(rf):
    """The hook is the task list's, and an add-another page inherits it —
    so the counts have to answer for it too. Every item shares one
    declaration, so the entry is what tells them apart."""

    class _Locked(_Guests):
        def entry_blocked(self, entry, store):
            return entry.key == ITEM_B

    view = _page(
        _Locked,
        rf,
        _seed(items=[(ITEM_A, "Ada"), (ITEM_B, "Grace")])
        | {"stashes": {f"guests:{ITEM_A}": {}, f"guests:{ITEM_B}": {}}},
    )

    result = view.get_items()

    assert (result.count, result.completed, result.blocked) == (2, 1, 1)
    assert result.remaining == 1
    assert view.enter(view.get_item(ITEM_B)) is None


def test_a_locked_item_is_refused_at_the_door_and_an_open_one_is_not(rf):
    class _Locked(_Guests):
        def entry_blocked(self, entry, store):
            return entry.key == ITEM_B

    view = _page(_Locked, rf, _seed(items=[(ITEM_A, None), (ITEM_B, None)]))

    assert view.enter(view.get_item(ITEM_B)) is None
    assert view.enter(view.get_item(ITEM_A)).startswith(f"{PAGE}{ITEM_A}/")


def test_a_page_can_hide_its_items_one_by_one(rf):
    """`entry_hidden()` reaches an add-another page through the same seam
    `entry_blocked()` does."""

    class _Hiding(_Guests):
        def entry_hidden(self, entry, store):
            return entry.key == ITEM_B

    view = _page(_Hiding, rf, _seed(items=[(ITEM_A, "Ada"), (ITEM_B, "Grace")]))

    assert [row.item_id for row in view.get_items().rows] == [ITEM_A]


def test_the_page_says_how_many_items_it_needs(rf):
    """A page that asks for at least one has to be able to say so."""

    class _AtLeastTwo(_Guests):
        add_another = GUESTS.replace(min_items=2)

    assert _page(_AtLeastTwo, rf).get_items().min_items == 2
    assert _page(_Guests, rf).get_items().min_items == 0


# --- what an item is called -------------------------------------------------


def test_an_item_is_named_by_the_title_its_own_run_cached(guests):
    view = guests(_seed(items=[(ITEM_A, "Ada Lovelace")]))

    (row,) = view.get_items().rows

    assert row.title == "Ada Lovelace"
    assert row.item_id == ITEM_A
    assert row.position == 0


def test_an_item_that_has_never_finished_is_named_by_its_position(guests):
    view = guests(_seed(items=[(ITEM_A, None), (ITEM_B, None)]))

    rows = view.get_items().rows

    assert [str(row.title) for row in rows] == ["Guest 1", "Guest 2"]


def test_an_item_name_is_derived_from_the_key_by_default(rf):
    class _Unnamed(_Guests):
        add_another = GUESTS.replace(item_name=None)

    class _Nested(_Unnamed):
        key = "party:guests"

    for cls, key in ((_Unnamed, "guests"), (_Nested, "party:guests")):
        view = _page(cls, rf, _seed(items=[(ITEM_A, None)], key=key))
        assert str(view.get_items().rows[0].title) == "Guest 1"


def test_a_row_carries_both_links_a_crud_list_needs(guests):
    view = guests(_seed(items=[(ITEM_A, "Ada")]))

    (row,) = view.get_items().rows

    assert row.url == f"{PAGE}{ITEM_A}/"
    assert row.remove_url == f"{PAGE}{ITEM_A}/remove/"


def test_the_pages_rows_are_also_its_task_list_rows(guests):
    """So a template written for a task list reads the page unchanged."""
    view = guests(_seed(items=[(ITEM_A, "Ada")]))

    context = view.get_context_data()

    assert list(view.get_rows()) == list(context["items"].rows)
    assert isinstance(context["items"].rows[0], ItemRow)
    assert isinstance(context["form"], AddAnotherForm)


def test_the_page_publishes_no_task_list_beside_its_items(guests):
    """Two statuses derived two ways would be on the one page: the list is
    complete when the user says there are no more, which no count of rows
    can tell you."""
    view = guests(_seed(items=[(ITEM_A, "Ada")]))

    assert "task_list" not in view.get_context_data()


# --- the actions ------------------------------------------------------------


def test_adding_an_item_registers_it_before_entering_its_wizard(guests):
    """Write the durable fact, then do the thing that can fail — so a failure
    leaves a listed, removable row rather than an orphan run."""
    view = guests()

    view.add_item()

    store = SessionCollectionStore(view.request, "default")
    (item_id,) = store.item_ids("guests")
    assert store.get_run(f"guests:{item_id}") is not None


def test_adding_an_item_withdraws_the_users_answer(guests):
    view = guests(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    view.add_item()

    assert (
        SessionCollectionStore(view.request, "default").is_declared_done("guests")
        is False
    )


def test_declaring_no_more_records_the_answer_and_moves_the_user_on(guests):
    view = guests(
        _seed(items=[(ITEM_A, "Ada")]) | {"stashes": {f"guests:{ITEM_A}": {}}}
    )

    response = view.declare_done()

    assert (
        SessionCollectionStore(view.request, "default").is_declared_done("guests")
        is True
    )
    assert response.status_code == 302
    assert response["Location"] == "/party/"


def test_removing_an_item_destroys_the_pointer_last(guests):
    """The mirror of `SectionViewSet.done()`: an `item_removed()` that
    raises leaves the item still listed and still removable."""
    events = []

    class _FailingItem(ItemViewSet):
        wizard = GUEST

        def item_removed(self, store):
            item_id = self.get_item_id()
            events.append(
                (
                    store.get_item_title("guests", item_id),
                    store.has_item("guests", item_id),
                )
            )
            raise RuntimeError("nope")

    class _Failing(_Guests):
        add_another = GUESTS.replace(wizard=_FailingItem)

    view = _Failing()
    view.setup(guests(_seed(items=[(ITEM_A, "Ada")])).request)

    with pytest.raises(RuntimeError):
        view.remove_item(ITEM_A)

    store = SessionCollectionStore(view.request, "default")
    assert events == [(None, True)]
    assert store.item_ids("guests") == [ITEM_A]


def test_an_item_does_nothing_on_removal_by_default(rf):
    view = _item_view(rf)

    assert view.item_removed(view.get_journey_store()) is None


def test_removing_an_item_leaves_the_users_answer_alone(guests):
    """Removal answers no question — three guests minus one is still "and no
    more"."""
    view = guests(_seed(items=[(ITEM_A, "Ada")], declared_done=True))

    view.remove_item(ITEM_A)

    assert (
        SessionCollectionStore(view.request, "default").is_declared_done("guests")
        is True
    )


def test_discarding_a_run_the_storage_has_forgotten_is_not_an_error(guests):
    view = guests(
        _seed(items=[(ITEM_A, "Ada")]) | {"runs": {f"guests:{ITEM_A}": "gone"}}
    )

    view.remove_item(ITEM_A)

    assert SessionCollectionStore(view.request, "default").item_ids("guests") == []


def test_an_item_id_the_registry_does_not_list_is_refused(guests):
    view = guests(_seed(items=[(ITEM_A, "Ada")]))

    assert view.get_item(ITEM_A).key == ITEM_A
    assert view.full_key(view.get_item(ITEM_A)) == f"guests:{ITEM_A}"
    with pytest.raises(ItemNotFound):
        view.get_item(ITEM_B)


def test_an_unavailable_item_is_sent_back_to_the_page(guests):
    response = guests().entry_unavailable("nope")

    assert response.status_code == 302
    assert response["Location"] == PAGE


def test_item_ids_are_opaque_and_unique(guests):
    view = guests()

    assert view.new_item_id() != view.new_item_id()


# --- an item's own viewset --------------------------------------------------


def test_an_item_keys_itself_from_the_url(rf):
    view = _item_view(rf)

    assert view.get_key() == "guests:7"


def test_every_item_stamps_one_label(rf):
    """One shape, one label, however many items wear it — a per-item uuid in
    the stash would make the deploy guard match nothing."""
    view = _item_view(rf)

    assert view.get_label() == "guests"


def test_the_item_label_moves_with_its_items(rf):
    """One declaration carries the label, so the stamp and the check cannot
    drift apart."""

    class _Reshaped(_Guests):
        add_another = GUESTS.replace(label="guests-v2")

    view = _page(_Reshaped, rf, _seed(items=[(ITEM_A, "Ada")]))
    item = _item_view(rf, cls=_Reshaped.item_viewset)

    assert view.get_item_label() == "guests-v2"
    assert view.stash_label(view.get_item_entry(ITEM_A)) == "guests-v2"
    assert item.get_label() == "guests-v2"


def test_a_finished_item_returns_to_its_page_without_its_own_id(rf):
    view = _item_view(rf)

    assert view.get_task_list_url() == PAGE


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
    class _Callable(_Guests):
        add_another = GUESTS.replace(
            item_title=lambda run: run.get_state()[0]["step"]["name"].upper(),
        )

    view = _item_view(
        rf,
        cls=_Callable.item_viewset,
        session={"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        run_id="run-1",
    )

    run = _Callable.item_viewset.inspect(view.request, "run-1", item="7")

    assert view.get_item_title(run) == "ADA"


def test_an_items_run_done_knows_which_item_it_is(rf):
    seen = []

    class _Deciding(ItemViewSet):
        wizard = GUEST

        def run_done(self, run):
            seen.append(self.get_item_id())
            return super().run_done(run)

    class _Page(_Guests):
        add_another = GUESTS.replace(wizard=_Deciding)

    view = _item_view(
        rf,
        cls=_Page.item_viewset,
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

    response = view.done(_Page.item_viewset.inspect(view.request, "run-1", item="7"))

    assert seen == ["7"]
    assert response["Location"] == PAGE


def test_an_item_whose_naming_step_is_off_the_route_falls_back(rf):
    """A branch the user did not take names nothing, so the row is honest and
    numbers itself instead."""

    class _Elsewhere(_Guests):
        add_another = GUESTS.replace(
            wizard=GUEST.branch(
                condition(
                    lambda context: False,
                    Wizard().step(NewsletterForm, name="newsletter"),
                )
            ),
            item_title="email",
        )

    view = _item_view(
        rf,
        cls=_Elsewhere.item_viewset,
        session={"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        run_id="run-1",
    )

    run = _Elsewhere.item_viewset.inspect(view.request, "run-1", item="7")
    assert view.get_item_title(run) == ""


def test_a_removed_items_wizard_sends_the_user_back_to_the_page(rf):
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


def test_a_page_without_a_key_is_misconfigured():
    with pytest.raises(ImproperlyConfigured, match="key"):
        type("_Keyless", (_Guests,), {"key": None})


def test_a_page_without_a_declaration_is_misconfigured(rf):
    class _Undeclared(AddAnotherViewSet):
        url_name = "standalone-guests"
        key = "guests"

    with pytest.raises(ImproperlyConfigured, match="add_another"):
        _page(_Undeclared, rf).get_items()


def test_a_page_listed_by_nothing_is_a_root_and_needs_a_journey_done(rf):
    """No `task_list_url_name` means nothing above: Continue is then the
    journey's submit, and a root with nothing to do at submit is
    misconfigured — the same refusal a root task list gives."""

    class _Endless(_Guests):
        task_list_url_name = None

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        _page(_Endless, rf).declare_done()


def test_a_page_without_a_url_name_is_misconfigured(guests):
    view = guests()
    view.url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        view.get_page_url()
    with pytest.raises(ImproperlyConfigured, match="url_name"):
        view.get_item_url(ITEM_A)
    with pytest.raises(ImproperlyConfigured, match="url_name"):

        class _NamelessView(AddAnotherViewSet):
            url_name = None

        _NamelessView.urls()


def test_an_item_wizard_without_a_list_key_is_misconfigured(rf):
    class _Homeless(_ItemViewSet):
        list_key = None

    view = _item_view(rf, cls=_Homeless)

    with pytest.raises(ImproperlyConfigured, match="no list"):
        view.get_key()


def test_an_item_wizard_not_mounted_under_an_item_segment_is_misconfigured(rf):
    view = _ItemViewSet()
    view.setup(rf.get(PAGE))

    with pytest.raises(ImproperlyConfigured, match="item segment"):
        view.get_item_id()


def test_an_item_wizard_without_a_page_to_return_to_is_misconfigured(rf):
    class _Adrift(_ItemViewSet):
        task_list_url_name = None

    view = _item_view(rf, cls=_Adrift)

    with pytest.raises(ImproperlyConfigured, match="task_list_url_name"):
        view.get_task_list_url()


def test_an_item_wizard_that_cannot_name_its_items_is_misconfigured(rf):
    class _Anonymous(_Guests):
        add_another = GUESTS.replace(item_title=None)

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


def test_the_page_needs_a_remove_template_to_confirm_with(rf):
    class _Blunt(_Guests):
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


def test_the_page_route_renders_the_items(rf):
    request = _view_request(rf, session=_seed(items=[(ITEM_A, "Ada")], key=KEY))

    response = GuestsViewSet.as_view()(request)

    assert response.status_code == 200
    assert response.context_data["items"].count == 1
    assert response.template_name == ["testapp/items.html"]


def test_the_page_route_registers_an_item_and_redirects_into_its_wizard(rf):
    request = _view_request(rf, "post", data={"add_another": "yes"})

    response = GuestsViewSet.as_view()(request)

    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    (item_id,) = store.item_ids(KEY)
    assert response.status_code == 302
    assert response["Location"].startswith(f"{PAGE}{item_id}/")
    assert response["Location"].endswith("/guest/")


def test_an_unanswered_question_re_renders_the_page(rf):
    request = _view_request(rf, "post", session=_seed(items=[(ITEM_A, "Ada")], key=KEY))

    response = GuestsViewSet.as_view()(request)

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

    response = GuestsViewSet.as_view()(request)

    assert response["Location"] == "/party/"
    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.is_declared_done(KEY) is True


def test_the_item_route_enters_the_item_it_names(rf):
    request = _view_request(
        rf, path=f"{PAGE}{ITEM_A}/", session=_seed(items=[(ITEM_A, "Ada")], key=KEY)
    )

    response = GuestsViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 302
    assert response["Location"].startswith(f"{PAGE}{ITEM_A}/")


def test_the_item_route_declines_an_item_the_page_has_locked(rf):
    """An app may gate its items too. The door then has nothing to hand back,
    and sends the user to the page rather than redirecting to `None`."""
    request = _view_request(
        rf,
        path=f"/locked-guests/{ITEM_A}/",
        session=_seed(items=[(ITEM_A, "Ada")], key="locked-guests"),
    )

    response = LockedGuestsViewSet.as_view()(request, item=ITEM_A)

    assert response["Location"] == "/locked-guests/"


def test_adding_to_a_locked_page_still_registers_the_item(rf):
    """`add_item()` writes the durable fact before it enters, so the user is
    left with a listed, removable row and the page they pressed Add on."""
    request = _view_request(
        rf, "post", path="/locked-guests/", data={"add_another": "yes"}
    )

    response = LockedGuestsViewSet.as_view()(request)

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

    response = GuestsViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 200
    assert response.template_name == ["testapp/items_remove.html"]
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

    response = GuestsViewSet.as_view()(request, item=ITEM_A)

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

    GuestsViewSet.as_view()(request, item=ITEM_A)

    assert "run-1" not in request.session["gandalf_runs"]


def test_a_door_naming_an_unlisted_item_is_sent_back_to_the_page(rf):
    request = _resolved(
        _view_request(rf, path=f"{PAGE}{ITEM_B}/"), "standalone-guests-item"
    )

    response = GuestsViewSet.as_view()(request, item=ITEM_B)

    assert response.status_code == 302
    assert response["Location"] == PAGE


def test_removing_an_unlisted_item_is_sent_back_to_the_page(rf):
    request = _resolved(
        _view_request(rf, "post", path=f"{PAGE}{ITEM_B}/remove/"),
        "standalone-guests-remove",
    )

    response = GuestsViewSet.as_view()(request, item=ITEM_B)

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

    response = GuestsViewSet.as_view()(request, item=ITEM_A)

    assert response.status_code == 405
    store = SessionCollectionStore(WizardContext.from_request(request), "default")
    assert store.item_ids(KEY) == [ITEM_A]


def test_the_page_publishes_itself_an_item_a_remove_and_the_item_wizard():
    """The item wizard is mounted beneath the door for its item, minus the
    bare start URL the door already stands in for."""
    page, door, remove, wizard = GuestsViewSet.urls()

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


def test_the_page_reports_its_status_to_a_parent_task_list(rf):
    """An add-another page is a task list, so a parent lists it as an entry
    like any other, and asks `status_for()` — the page's own status, which
    no stash key could express."""
    request = _view_request(
        rf,
        path="/party/",
        session=_seed(items=[(ITEM_A, "Ada")], declared_done=True, key=KEY)
        | {"stashes": {f"{KEY}:{ITEM_A}": {}}},
    )

    assert TaskListViewSet.is_group(GUESTS.bound("guests", GuestsViewSet))
    assert GuestsViewSet.status_for(request, {}) == COMPLETE


def test_an_item_wizard_serves_a_request_for_an_item_the_registry_lists(rf):
    request = _view_request(
        rf,
        path=f"{PAGE}{ITEM_A}/{RUN}/",
        session=_seed(items=[(ITEM_A, None)], key=KEY),
    )

    response = GuestsViewSet.item_viewset.as_view()(request, item=ITEM_A, run_id=RUN)

    # A run the storage has never seen: back to the page.
    assert response.status_code == 302
    assert response["Location"] == PAGE


# --- the journey -------------------------------------------------------------


def test_the_page_keeps_its_registry_under_its_journey(rf):
    class _Journeyed(_Guests):
        journey = "app-1"

    request = rf.get(PAGE)
    request.session = _session(_seed(items=[(ITEM_A, "Ada")]), journey="app-1")

    assert _Journeyed.item_viewset.journey == "app-1"
    assert _page(_Guests, rf).get_items().count == 0
    view = _Journeyed()
    view.setup(request)
    assert view.get_items().count == 1


def test_the_page_reports_its_status_under_its_own_journey(rf):
    """`status_for()` answers for the journey the page is on."""

    class _Journeyed(GuestsViewSet):
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
    assert GuestsViewSet.status_for(request, {}) == NOT_STARTED


def test_the_page_under_a_submitted_journey_sends_the_user_on(rf):
    """The task list above it is the page that can say what a submitted
    journey looks like; an add-another page has no page of its own for
    that."""
    request = _view_request(rf, session={"completed": True})

    response = GuestsViewSet.as_view()(request)

    assert response.status_code == 302
    assert response["Location"] == "/party/"


def test_a_section_entry_stands_in_for_an_item(guests):
    """An item is listed as a `Section` bound to its id, with the id as the
    kwarg its own URLs take."""
    view = guests(_seed(items=[(ITEM_A, "Ada")]))

    entry = view.get_item_entry(ITEM_A)

    assert isinstance(entry, Section)
    assert entry.key == ITEM_A
    assert entry.viewset is _ItemViewSet
    assert entry.url_kwargs == {"item": ITEM_A}
    assert view.item_id_for(entry) == ITEM_A
