"""Unit coverage for the task list layer.

A task list is a page of sections the user finishes in any order. The
display half answers "how far has each got" without walking anything; the
dispatch half turns one click into a step URL, walking only the section
the user chose. The declaration half — a `TaskList` class body — is what
both are built from, and `TaskListViewSet` is what mounts it.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.views import View

from gandalf.context import WizardContext
from gandalf.runtime import STASH_VERSION
from gandalf.storage import SessionJourneyStore, SessionStorage
from gandalf.tasklists import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnother,
    Entry,
    EntryNotFound,
    EntryUnavailable,
    Group,
    Link,
    Row,
    Section,
    SectionViewSet,
    TaskList,
    TaskListPage,
    TaskListViewSet,
    class_name_for,
)
from gandalf.viewsets import DoorRefused, WizardViewSet
from gandalf.wizard import Wizard

from tests.testapp.forms import FirstStepForm, SecondStepForm


class _Session(dict):
    modified = False


#: The parts of a journey's record a test seeds, lifted under the journey
#: key the store reads them from. Everything else (`gandalf_runs`) passes
#: through untouched.
_JOURNEY_PARTS = ("runs", "stashes", "lists", "data", "completed")


def _session(seed=None, journey="default"):
    seed = dict(seed or {})
    record = {part: seed.pop(part) for part in _JOURNEY_PARTS if part in seed}
    if record:
        seed["gandalf_journeys"] = {journey: record}
    return _Session(seed)


CONTACT = Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second")


def _list(**entries):
    """A task list declared inline: keyword names are the keys."""
    return type("_List", (TaskList,), entries)


class _Contact(TaskList):
    contact = Section(CONTACT, title="Contact details")


class _Page(TaskListViewSet):
    """Named after this project's real task list, so every URL it builds
    reverses through the URLconf rather than being faked."""

    template_name = "testapp/task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-task-list"
    task_list = _Contact


class _JourneyPage(_Page):
    """The same, under the README's journey mount: `apply/<journey>/`."""

    url_name = "readme-apply"


def _view(task_list, **attributes):
    """A page over an inline list, with the test app's templates."""
    return type(
        "_ViewSet",
        (TaskListViewSet,),
        {
            "template_name": "testapp/task_list.html",
            "section_template_name": "testapp/linear_wizard.html",
            "url_name": "readme-task-list",
            # Each throwaway page gets its own list: one list, one page.
            "task_list": (
                task_list
                if task_list is None or task_list.viewset is None
                else type(task_list.__name__, (task_list,), {})
            ),
            **attributes,
        },
    )


def _page(cls, rf, session=None, path="/readme/task-list/", method="get", **kwargs):
    request = getattr(rf, method)(path)
    request.session = _session(session or {})
    view = cls()
    view.setup(request, **kwargs)
    return view


@pytest.fixture
def page(rf):
    def build(session=None):
        return _page(_Page, rf, session)

    return build


#: A real uuid, because a section's run routes match `<uuid:run_id>`.
RUN = "11111111-1111-1111-1111-111111111111"


def _stash(state, label="contact"):
    return {"version": STASH_VERSION, "label": label, "state": state}


class _Pair(TaskList):
    """Two sections, so the counts have something to count."""

    contact = Section(CONTACT, title="Contact details")
    address = Section(CONTACT, title="Address")


class _PairPage(_Page):
    task_list = _Pair


@pytest.fixture
def pair_page(rf):
    def build(session=None):
        return _page(_PairPage, rf, session)

    return build


class _GatedPage(_PairPage):
    """Address waits on contact — the shape of every task list that unlocks,
    answered by the page's own hook."""

    def entry_blocked(self, entry, store):
        return entry.key == "address" and not store.has_stash("contact")


@pytest.fixture
def gated_page(rf):
    def build(session=None):
        return _page(_GatedPage, rf, session)

    return build


def _section_view(
    cls, rf, session=None, path="/readme/task-list/contact/run-1/", **kwargs
):
    request = rf.get(path)
    request.session = _session(session or {})
    view = cls()
    view.setup(request, **kwargs)
    return view


def _retrieved(view, run_id="run-1"):
    context = WizardContext.from_request(view.request)
    from gandalf.runtime import Run

    run = Run(context, SessionStorage(context))
    run.retrieve(run_id)
    return run


# --- the declaration --------------------------------------------------------


def test_the_entries_become_the_pages_entries_in_body_order():
    entries = {entry.key: entry for entry in _PairPage.entries}

    assert list(entries) == ["contact", "address"]
    assert list(_Pair.entries) == ["contact", "address"]
    assert entries["contact"].title == "Contact details"
    assert issubclass(entries["contact"].viewset, SectionViewSet)
    assert entries["contact"].viewset.key == "contact"
    assert entries["contact"].viewset.task_list_url_name == "readme-task-list"
    assert entries["contact"].viewset.url_name == "readme-task-list-contact"
    assert entries["contact"].viewset.template_name == "testapp/linear_wizard.html"


def test_an_entry_stays_readable_on_the_declaration():
    """A value, not a view: nothing for a name like `setup` to shadow."""

    class _Named(TaskList):
        setup = Section(CONTACT, title="Applying as")

    assert isinstance(_Named.setup, Section)
    assert _Named.setup.title == "Applying as"
    assert _Named.setup.key == ""
    assert View.setup is not _Named.setup


def test_an_explicit_key_names_the_entry_and_its_url():
    """An attribute name cannot carry a hyphen; the key can."""

    class _Hyphenated(TaskList):
        match_funding = Section(CONTACT, title="Match funding", key="match-funding")

    class _HyphenatedPage(_Page):
        url_name = "readme-hyphen"
        task_list = _Hyphenated

    assert list(_Hyphenated.entries) == ["match-funding"]
    (entry,) = _HyphenatedPage.entries
    assert entry.key == "match-funding"
    assert entry.viewset.key == "match-funding"
    assert entry.viewset.url_name == "readme-hyphen-match-funding"
    assert isinstance(_Hyphenated.match_funding, Section)


def test_a_reopen_at_naming_no_declared_step_is_refused():
    class _Typo(TaskList):
        contact = Section(CONTACT, reopen_at="secnod")

    with pytest.raises(ImproperlyConfigured, match="re-opens at 'secnod'"):

        class _TypoPage(_Page):
            url_name = "readme-typo"
            task_list = _Typo


def test_a_reopen_at_on_a_per_request_wizard_cannot_be_checked():
    """A section viewset that builds its wizard in get_wizard() has no
    declaration to check against, so the name is taken on trust."""

    class _PerRequest(SectionViewSet):
        def get_wizard(self, run):
            return CONTACT

    class _Trusted(TaskList):
        contact = Section(_PerRequest, reopen_at="anything")

    class _TrustedPage(_Page):
        url_name = "readme-trusted"
        task_list = _Trusted

    (entry,) = _TrustedPage.entries
    assert entry.reopen_at == "anything"


def test_two_entries_under_one_key_are_refused():
    with pytest.raises(ImproperlyConfigured, match="two entries under the key 'pay'"):

        class _Clash(TaskList):
            pay = Section(CONTACT)
            pay_again = Section(CONTACT, key="pay")


def test_a_declaration_is_inherited_and_extended_by_a_subclass():
    class _More(_Pair):
        extra = Section(CONTACT)

    assert list(_More.entries) == ["contact", "address", "extra"]
    assert list(_Pair.entries) == ["contact", "address"]


def test_binding_an_entry_keeps_its_facts_and_adds_its_key_and_viewset():
    entry = Section(CONTACT, title="Contact", reopen_at="second", label="v2")

    bound = entry.bound("contact", _Page)

    assert (bound.key, bound.viewset) == ("contact", _Page)
    assert (bound.title, bound.reopen_at, bound.label) == ("Contact", "second", "v2")
    assert bound.wizard is CONTACT
    assert entry.key == ""


def test_entries_with_the_same_facts_compare_equal():
    """The viewset and `url_kwargs` are excluded from comparison so an entry
    stays hashable with a mutable default."""
    first = Section(CONTACT, url_kwargs={"org": "acme"}, viewset=_Page)
    second = Section(CONTACT, url_kwargs={"org": "other"})

    assert first == second
    assert hash(first) == hash(second)


def test_a_bare_entry_is_neither_a_link_nor_reopenable():
    entry = Entry(title="Bare").bound("bare")

    assert (entry.reopen_at, entry.url_name, entry.status) == (None, None, None)


def test_a_link_must_say_how_far_it_has_got():
    """Without a status the page would derive one from a stash key nothing
    writes."""
    with pytest.raises(ImproperlyConfigured, match="status"):
        Link("pay")


def test_a_link_binds_to_a_key_and_keeps_where_it_points():
    status = lambda request, kwargs: COMPLETE  # noqa: E731
    link = Link("readme-task-list", title="Pay", status=status).bound("payment")

    assert (link.key, link.url_name, link.status, link.title) == (
        "payment",
        "readme-task-list",
        status,
        "Pay",
    )
    assert link.viewset is None


def test_an_entry_of_no_known_kind_is_refused():
    class _Odd(Entry):
        pass

    with pytest.raises(ImproperlyConfigured, match="kind of entry"):
        _view(_list(odd=_Odd()))


def test_a_declared_wizard_viewset_is_used_as_the_sections_base():
    """A section that needs a hook is declared by its viewset class rather
    than its wizard — a plain `WizardViewSet` is wrapped, as a wizard is."""

    class _Custom(WizardViewSet):
        wizard = CONTACT
        template_name = "testapp/linear_wizard.html"

    viewset = _view(_list(contact=Section(_Custom))).viewset_for("contact")

    assert issubclass(viewset, _Custom)
    assert issubclass(viewset, SectionViewSet)
    assert viewset.template_name == "testapp/linear_wizard.html"


def test_a_declared_section_viewset_is_used_as_is():
    """A class that is already a `SectionViewSet` — one with behaviour, or a
    generated one re-listed — is not wrapped a second time."""
    already = _Page.viewset_for("contact")

    viewset = _view(_list(contact=Section(already))).viewset_for("contact")

    assert viewset.__bases__ == (already,)
    assert viewset.wizard is CONTACT


def test_viewset_for_rejects_an_unknown_key():
    with pytest.raises(EntryNotFound):
        _Page.viewset_for("nope")


def test_a_subclass_that_swaps_its_stores_rebuilds_its_sections_on_them():
    class _Storage(SessionStorage):
        pass

    class _Store(SessionJourneyStore):
        pass

    class _Durable(_Page):
        storage_class = _Storage
        journey_store_class = _Store

    viewset = _Durable.viewset_for("contact")
    assert viewset.storage_class is _Storage
    assert viewset.journey_store_class is _Store
    assert viewset is not _Page.viewset_for("contact")


def test_a_generated_class_is_named_for_its_key():
    assert (
        class_name_for("home_address", "SectionViewSet") == "HomeAddressSectionViewSet"
    )
    assert _Page.viewset_for("contact").__name__ == "ContactSectionViewSet"


# --- mounting ---------------------------------------------------------------


def test_mounting_a_list_registers_the_way_into_it():
    """The first root to mount a list is its way in."""
    solo = _list(contact=Section(CONTACT))
    first = _view(solo)

    assert solo.viewset is first


def test_a_list_begins_a_journey_through_the_page_that_mounts_it(rf):
    solo = _list(contact=Section(CONTACT))
    _view(solo, url_name="readme-apply")
    request = rf.get("/")
    request.session = _session()

    journey = solo.begin(request, journey="app-1")

    assert journey.url == "/readme/apply/app-1/"


def test_a_list_begins_a_journey_with_no_request_at_all():
    """The list's half of `begin_for()`. Everything a journey is — an id, a
    record under it, a URL — is reachable from a context, so a caller with
    no browser goes through the same page as one with."""
    solo = _list(contact=Section(CONTACT))
    _view(solo, url_name="readme-apply")

    journey = solo.begin_for(WizardContext(session=_session()), journey="app-1")

    assert journey.url == "/readme/apply/app-1/"
    assert journey.store.keys() == []


def test_an_unmounted_list_cannot_begin_a_journey(rf):
    class _Loose(TaskList):
        only = Section(CONTACT)

    with pytest.raises(ImproperlyConfigured, match="not mounted"):
        _Loose.begin(rf.get("/"))


# --- status derivation -----------------------------------------------------


def test_a_section_with_no_run_and_no_stash_has_not_started(page):
    (row,) = page().get_rows()

    assert row.status == NOT_STARTED
    assert row.is_not_started


def test_a_section_whose_run_holds_an_answer_is_incomplete(page):
    view = page(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    (row,) = view.get_rows()

    assert row.status == INCOMPLETE
    assert row.is_incomplete


def test_a_section_the_user_opened_but_never_answered_has_not_started(page):
    """A run exists, but there is nothing in it to pick up."""
    view = page({"runs": {"contact": "run-1"}, "gandalf_runs": {"run-1": {}}})

    (row,) = view.get_rows()

    assert row.status == NOT_STARTED


def test_a_section_whose_run_the_storage_has_forgotten_has_not_started(page):
    """An expired session or an obliterated run leaves nothing to resume, so
    the honest thing to say is that it has not begun."""
    view = page({"runs": {"contact": "gone"}})

    (row,) = view.get_rows()

    assert row.status == NOT_STARTED


def test_a_section_holding_a_stash_is_complete(page):
    view = page({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    (row,) = view.get_rows()

    assert row.status == COMPLETE
    assert row.is_complete


def test_a_completed_sections_stash_outranks_its_tombstoned_run(page):
    """The recorded run may be stale — tombstoned, pruned, or replaced by a
    resurrection — and status never consults it once a stash exists."""
    view = page(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"completed": True}},
            "stashes": {"contact": _stash([{"step": {"name": "Ada"}}])},
        }
    )

    (row,) = view.get_rows()

    assert row.status == COMPLETE


def test_a_tombstoned_run_without_a_stash_has_not_started(page):
    view = page(
        {"runs": {"contact": "run-1"}, "gandalf_runs": {"run-1": {"completed": True}}}
    )

    (row,) = view.get_rows()

    assert row.status == NOT_STARTED


def test_building_the_rows_never_walks_a_section(page, monkeypatch):
    """The claim the whole design rests on: a row costs storage reads, not a
    form validation per answered step."""
    from gandalf.runtime import CursorWalker

    def _forbidden(*args, **kwargs):
        raise AssertionError("a task list row must not walk a wizard")

    monkeypatch.setattr(CursorWalker, "walk", _forbidden)
    view = page(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    assert view.get_rows()[0].status == INCOMPLETE


# --- rows ------------------------------------------------------------------


def test_a_row_carries_its_title_status_label_and_url(page):
    (row,) = page().get_rows()

    assert isinstance(row, Row)
    assert row.title == "Contact details"
    assert row.status_label == "Not started"
    assert row.url == "/readme/task-list/contact/"
    assert row.key == "contact"


def test_a_section_without_a_title_is_named_from_its_key(rf):
    (row,) = _page(_view(_list(home_address=Section(CONTACT))), rf).get_rows()

    assert row.title == "Home address"


def test_the_rows_land_in_the_template_context(page):
    context = page().get_context_data()

    assert [row.key for row in context["task_list"].rows] == ["contact"]


# --- a section the user cannot start yet ------------------------------------


def test_a_section_waiting_on_another_cannot_start_yet(gated_page):
    contact, address = gated_page().get_rows()

    assert contact.status == NOT_STARTED
    assert address.status == BLOCKED
    assert address.is_blocked


def test_a_section_unblocks_once_its_prerequisite_is_answered(gated_page):
    view = gated_page({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    contact, address = view.get_rows()

    assert (contact.status, address.status) == (COMPLETE, NOT_STARTED)
    assert not address.is_blocked


def test_being_blocked_outranks_a_section_already_finished(gated_page):
    """The prerequisite was withdrawn after the section was answered. The
    row reports what the user can do, not what they once did — a
    **Complete** row over a link the door refuses is the worse of the two
    lies."""
    view = gated_page(
        {"stashes": {"address": _stash([{"step": {"x": 1}}], label="address")}}
    )

    _, address = view.get_rows()

    assert address.status == BLOCKED


def test_a_blocked_section_is_labelled_cannot_start_yet(gated_page):
    _, address = gated_page().get_rows()

    assert str(address.status_label) == "Cannot start yet"


def test_a_blocked_section_is_refused_at_the_door(gated_page):
    """The row rendered a link the user may not follow, and a stale link or
    a typed URL reaches the door regardless."""
    view = gated_page()

    assert view.enter(view.get_entry("address")) is None
    assert SessionJourneyStore(view.request, "default").get_run("address") is None


def test_a_link_reporting_blocked_under_its_own_steam_is_refused_too(rf):
    """A link's `status` answers for itself, so the door asks the status
    rather than the hook — otherwise the two could disagree."""
    gated = _list(
        contact=Link("readme-task-list", status=lambda request, url_kwargs: BLOCKED)
    )
    view = _page(_view(gated), rf)

    assert view.get_rows()[0].status == BLOCKED
    assert view.enter(view.get_entry("contact")) is None


def test_a_link_reporting_a_status_the_page_cannot_label_says_so(rf):
    """A link's status is arbitrary code, and the page renders a label for
    every row — so a status outside the four is refused by name rather than
    taking the whole page down with a KeyError."""
    odd = _list(
        contact=Link("readme-task-list", status=lambda request, kwargs: "half-done")
    )
    view = _page(_view(odd), rf)

    with pytest.raises(ImproperlyConfigured, match="half-done"):
        view.get_rows()


def test_a_link_pointing_at_a_url_that_does_not_reverse_names_the_entry(rf):
    """Otherwise every row on the page dies of one entry's NoReverseMatch,
    with nothing to say which declaration is wrong."""
    broken = _list(
        contact=Link("no-such-url-name", status=lambda request, kwargs: COMPLETE)
    )
    view = _page(_view(broken), rf)

    with pytest.raises(ImproperlyConfigured, match="no-such-url-name"):
        view.get_rows()


def test_an_unblocked_section_still_enters(gated_page):
    view = gated_page({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    assert view.enter(view.get_entry("address")) is not None


# --- a section that gates itself --------------------------------------------


class _Employed(SectionViewSet):
    """The rule lives on the section it gates, and reads the store alone."""

    wizard = CONTACT

    @classmethod
    def blocked(cls, store):
        return not store.data.get("employed", False)


class _SelfGated(TaskList):
    address = Section(_Employed, title="Address")


@pytest.fixture
def self_gated_page(rf):
    def build(session=None):
        return _page(_view(_SelfGated), rf, session)

    return build


def test_a_section_can_say_it_is_not_open_yet_itself(self_gated_page):
    (address,) = self_gated_page().get_rows()

    assert address.status == BLOCKED
    assert str(address.status_label) == "Cannot start yet"


def test_a_section_that_opens_says_so_too(self_gated_page):
    (address,) = self_gated_page({"data": {"journey": {"employed": True}}}).get_rows()

    assert address.status == NOT_STARTED


def test_a_section_gating_itself_is_refused_at_its_pages_door(self_gated_page):
    """The page asks the rule, so display and dispatch cannot disagree."""
    view = self_gated_page()

    assert view.enter(view.get_entry("address")) is None
    assert SessionJourneyStore(view.request, "default").get_run("address") is None


def test_a_rule_is_handed_the_store_and_nothing_else(rf):
    """One read of the journey's record is all a row can afford, and all a
    rule is given."""
    seen = []

    class _Recording(SectionViewSet):
        wizard = CONTACT

        @classmethod
        def blocked(cls, store):
            seen.append(store)
            return False

    _page(_view(_list(address=Section(_Recording))), rf).get_rows()

    (store,) = seen
    assert store.journey == "default"


def test_a_page_override_answers_instead_of_the_section(self_gated_page):
    """`entry_blocked()` is the question, not a vote joined to the
    section's: an override that does not call `super()` replaces it."""
    view = self_gated_page()
    view.entry_blocked = lambda entry, store: False

    (address,) = view.get_rows()

    assert address.status == NOT_STARTED


def test_a_section_answers_open_by_default(page):
    view = page()
    store = view.get_journey_store()

    assert view.entry_blocked(view.get_entry("contact"), store) is False
    assert view.entry_hidden(view.get_entry("contact"), store) is False


def test_a_link_is_never_asked(rf):
    """A link has no rule. It supplies its own `status` instead, which the
    door reads — and which may itself be `BLOCKED`."""
    linked = _list(
        payment=Link(
            "readme-task-list",
            title="Payment",
            status=lambda request, url_kwargs: NOT_STARTED,
        )
    )
    view = _page(_view(linked), rf)

    store = view.get_journey_store()
    assert view.entry_blocked(view.get_entry("payment"), store) is False
    assert view.entry_hidden(view.get_entry("payment"), store) is False


# --- the page as a whole ----------------------------------------------------


def test_a_page_counts_how_many_of_its_sections_are_complete(pair_page):
    """The task list heading, without the view counting rows by hand."""
    view = pair_page({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    result = view.get_page()

    assert result.count == 2
    assert result.completed == 1
    assert result.remaining == 1


def test_a_page_with_every_section_complete_is_complete(pair_page):
    view = pair_page(
        {
            "stashes": {
                "contact": _stash([{"step": {"name": "Ada"}}]),
                "address": _stash([{"step": {"name": "Ada"}}], label="address"),
            }
        }
    )

    result = view.get_page()

    assert result.status == COMPLETE
    assert result.is_complete
    assert result.remaining == 0


def test_a_page_nobody_has_touched_has_not_started(pair_page):
    result = pair_page().get_page()

    assert result.status == NOT_STARTED
    assert result.is_not_started
    assert result.completed == 0


def test_a_page_with_one_section_under_way_is_incomplete(pair_page):
    view = pair_page(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    result = view.get_page()

    assert result.status == INCOMPLETE
    assert result.is_incomplete


def test_a_page_listing_nothing_has_not_started(rf):
    """`all()` over an empty list is true, and "complete" would be a lie: no
    section has begun because there is no section."""
    assert _page(_view(_list()), rf).get_page().status == NOT_STARTED


def test_a_fresh_page_whose_later_section_is_locked_has_still_not_started(
    gated_page,
):
    """A locked section is not progress. Counting it as one would open every
    task list on **Incomplete** before the user had answered anything."""
    result = gated_page().get_page()

    assert result.status == NOT_STARTED
    assert result.blocked == 1
    assert result.remaining == 2


def test_a_page_cannot_be_complete_while_a_section_is_locked(rf):
    """Which is why a section that will never unlock is one for `hidden`
    rather than locked forever inside the list."""

    class _Locked(_PairPage):
        def entry_blocked(self, entry, store):
            return entry.key == "address"

    view = _page(
        _Locked, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    result = view.get_page()

    assert result.status == INCOMPLETE
    assert (result.completed, result.blocked, result.remaining) == (1, 1, 1)


def test_a_pages_status_carries_its_own_label(pair_page):
    assert str(pair_page().get_page().status_label) == "Not started"


def test_the_page_lands_in_the_template_context(page):
    context = page().get_context_data()

    assert isinstance(context["task_list"], TaskListPage)


def test_a_page_publishing_no_context_name_publishes_nothing(page):
    view = page()
    view.page_context_name = None

    assert "task_list" not in view.get_context_data()


def test_the_rows_are_built_once_per_request(page):
    """Asking twice is what the counts used to cost. A row is two storage
    reads and a `reverse()`, and a whole `AddAnotherPage` for an entry that
    is one."""
    view = page()
    builds = []

    def build_rows():
        builds.append(1)
        return TaskListViewSet.build_rows(view)

    view.build_rows = build_rows

    view.get_context_data()
    view.get_rows()
    view.get_page()

    assert len(builds) == 1


def test_the_entries_are_chosen_once_per_request(rf):
    """Both halves of the page ask for the entries — the rows and the door —
    and `get_entries()` is a per-request choice, so it is asked once."""
    calls = []

    class _Counting(_Page):
        def get_entries(self):
            calls.append(1)
            return super().get_entries()

    view = _page(_Counting, rf)

    view.get_rows()
    view.get_entry("contact")

    assert len(calls) == 1


# --- declaration vetting ---------------------------------------------------


def test_a_page_without_a_task_list_is_misconfigured(rf):
    class _Bare(TaskListViewSet):
        template_name = "testapp/task_list.html"
        url_name = "readme-task-list"

    with pytest.raises(ImproperlyConfigured, match="task_list"):
        _page(_Bare, rf).get_rows()


def test_get_entries_can_choose_among_the_declared_entries_per_request(rf):
    class _Choosy(_PairPage):
        def get_entries(self):
            return [e for e in super().get_entries() if e.key != "address"]

    assert [row.key for row in _page(_Choosy, rf).get_rows()] == ["contact"]


def test_get_entry_finds_an_entry_by_key_and_rejects_an_unknown_one(page):
    view = page()

    assert view.get_entry("contact").viewset is _Page.viewset_for("contact")
    with pytest.raises(EntryNotFound):
        view.get_entry("nope")


# --- entering a section ----------------------------------------------------


def _entered(view):
    return view.enter(view.get_entry("contact"))


def test_entering_a_not_started_section_begins_a_run_and_records_it(page):
    view = page()

    url = _entered(view)

    run_id = SessionJourneyStore(view.request, "default").get_run("contact")
    assert run_id is not None
    assert url == f"/readme/task-list/contact/{run_id}/first/"


def test_entering_an_incomplete_section_resumes_its_own_run(page):
    view = page(
        {
            "runs": {"contact": RUN},
            "gandalf_runs": {RUN: {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    url = _entered(view)

    assert url == f"/readme/task-list/contact/{RUN}/second/"
    assert SessionJourneyStore(view.request, "default").get_run("contact") == RUN


def test_entering_a_completed_section_reopens_its_stash_at_the_first_step(page):
    """Never the bare run URL: every answer in a resurrected run validates,
    so a GET there would fire `done()` before the user edited anything."""
    view = page(
        {
            "stashes": {
                "contact": _stash(
                    [{"step": {"name": "Ada"}}, {"step": {"email": "ada@example.com"}}]
                )
            }
        }
    )

    url = _entered(view)

    run_id = SessionJourneyStore(view.request, "default").get_run("contact")
    assert url == f"/readme/task-list/contact/{run_id}/first/"
    assert view.request.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_reopening_a_section_leaves_its_stash_in_place(page):
    """Read, never popped: re-opening keeps working, and re-completing
    overwrites the stash with the newer answers."""
    view = page({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    _entered(view)

    assert SessionJourneyStore(view.request, "default").has_stash("contact")


def test_a_completed_section_already_being_edited_resumes_that_edit(page):
    """Resume before reopen, so at most one live run per section exists —
    otherwise every click would resurrect a run beside the in-flight edit
    and the user's changes would become unreachable."""
    view = page(
        {
            "runs": {"contact": RUN},
            "gandalf_runs": {RUN: {"state": [{"step": {"name": "Grace"}}]}},
            "stashes": {"contact": _stash([{"step": {"name": "Ada"}}])},
        }
    )

    url = _entered(view)

    assert url == f"/readme/task-list/contact/{RUN}/second/"


def test_a_section_whose_recorded_run_was_tombstoned_starts_again(page):
    """A completed run is *found*, not missing, so resuming has to ask
    `is_complete` as well — a run every request bounces off is worse than
    no run at all."""
    view = page(
        {"runs": {"contact": "run-1"}, "gandalf_runs": {"run-1": {"completed": True}}}
    )

    url = _entered(view)

    run_id = SessionJourneyStore(view.request, "default").get_run("contact")
    assert run_id != "run-1"
    assert url == f"/readme/task-list/contact/{run_id}/first/"


def test_a_section_whose_recorded_run_is_gone_starts_again(page):
    view = page({"runs": {"contact": "gone"}})

    url = _entered(view)

    run_id = SessionJourneyStore(view.request, "default").get_run("contact")
    assert run_id != "gone"
    assert url == f"/readme/task-list/contact/{run_id}/first/"


def test_a_section_can_name_the_step_a_reopened_stash_lands_on(rf):
    landing = _view(_list(contact=Section(CONTACT, reopen_at="second")))
    view = _page(
        landing, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    url = view.enter(view.get_entry("contact"))

    run_id = SessionJourneyStore(view.request, "default").get_run("contact")
    assert url == f"/readme/task-list/contact/{run_id}/second/"


def test_a_stash_whose_label_no_longer_matches_is_refused_loudly(rf):
    """A deploy reshaped the section and bumped its label. Starting over
    silently would look to the user exactly like their answers vanishing."""
    from gandalf.runtime import InvalidStash

    reshaped = _view(_list(contact=Section(CONTACT, label="contact-v2")))
    view = _page(
        reshaped, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    with pytest.raises(InvalidStash):
        view.enter(view.get_entry("contact"))


def test_stash_unusable_can_be_overridden_to_start_over(rf):
    class _Forgiving(_view(_list(contact=Section(CONTACT, label="contact-v2")))):
        def stash_unusable(self, entry, error):
            store = self.get_journey_store()
            store.delete_stash(entry.key)
            return self.enter(entry)

    view = _page(
        _Forgiving, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    url = view.enter(view.get_entry("contact"))

    run_id = SessionJourneyStore(view.request, "default").get_run("contact")
    assert url == f"/readme/task-list/contact/{run_id}/first/"


# --- SectionViewSet ---------------------------------------------------------


def _contact_view(rf, session=None, cls=None):
    return _section_view(cls or _Page.viewset_for("contact"), rf, session)


def test_finishing_a_section_stashes_its_answers_and_clears_its_run(rf):
    view = _contact_view(
        rf,
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        },
    )

    view.done(_retrieved(view))

    store = SessionJourneyStore(WizardContext.from_request(view.request), "default")
    assert store.get_stash("contact") == {
        "version": STASH_VERSION,
        "label": "contact",
        "state": [{"step": {"name": "Ada"}}],
    }
    assert store.get_run("contact") is None


def test_a_finished_section_sends_the_user_back_to_its_page(rf):
    """The default `run_done` — a task list expects a finished task to
    deposit the user back on the list."""
    view = _contact_view(
        rf, {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )

    response = view.done(_retrieved(view))

    assert response.status_code == 302
    assert response["Location"] == "/readme/task-list/"


def test_run_done_runs_between_the_stash_and_the_redirect(rf):
    """A section's own `run_done()` sees the store already holding the
    stash, and the run still readable."""
    events = []

    class _Deciding(SectionViewSet):
        wizard = CONTACT

        def run_done(self, run):
            store = self.get_journey_store()
            events.append((store.get_stash("contact")["state"], run.get_state()))
            return super().run_done(run)

    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=_view(_list(contact=Section(_Deciding))).viewset_for("contact"),
    )

    response = view.done(_retrieved(view))

    assert events == [([{"step": {"name": "Ada"}}], [{"step": {"name": "Ada"}}])]
    assert response["Location"] == "/readme/task-list/"


def test_a_run_done_that_raises_leaves_the_section_resumable(rf):
    """Mirrors `_finish`'s own ordering — the run id is cleared only after
    the application's work has succeeded."""

    class _Failing(SectionViewSet):
        wizard = CONTACT

        def run_done(self, run):
            raise RuntimeError("nope")

    view = _contact_view(
        rf,
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        },
        cls=_view(_list(contact=Section(_Failing))).viewset_for("contact"),
    )

    with pytest.raises(RuntimeError):
        view.done(_retrieved(view))

    store = SessionJourneyStore(WizardContext.from_request(view.request), "default")
    assert store.get_run("contact") == "run-1"


def test_bookkeeping_recorded_at_completion_runs_between_the_stash_and_run_done(
    rf,
):
    """`run_recorded()` sits above `run_done()` and below the stash, so
    it can read what was just recorded and cannot be pre-empted by an
    application hook that obliterates, escapes or raises."""
    events = []

    class _Recording(_Page.viewset_for("contact")):
        def run_recorded(self, run, store, key):
            events.append(("recorded", key, store.get_stash(key)["state"]))

        def run_done(self, run):
            events.append(("done", self.get_key(), None))
            return super().run_done(run)

    view = _contact_view(
        rf,
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        },
        cls=_Recording,
    )

    view.done(_retrieved(view))

    assert events == [
        ("recorded", "contact", [{"step": {"name": "Ada"}}]),
        ("done", "contact", None),
    ]


def test_bookkeeping_recorded_at_completion_can_still_read_the_runs_answers(rf):
    """The window closes when `finish()` tombstones the run, which is why
    anything that has to read the finished answers belongs here."""
    seen = []

    class _Recording(_Page.viewset_for("contact")):
        def run_recorded(self, run, store, key):
            seen.append(run.get_state())

    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=_Recording,
    )
    run = _Recording.inspect(view.request, "run-1")

    view.finish(run)

    assert seen == [[{"step": {"name": "Ada"}}]]
    assert run.is_complete
    assert SessionStorage(run.context).get_state("run-1") == []


def test_a_sections_stash_label_can_be_bumped_independently_of_its_key(rf):
    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=_view(_list(contact=Section(CONTACT, label="contact-v2"))).viewset_for(
            "contact"
        ),
    )

    view.done(_retrieved(view))

    store = SessionJourneyStore(WizardContext.from_request(view.request), "default")
    assert store.get_stash("contact")["label"] == "contact-v2"


def test_a_sections_stash_label_defaults_to_its_full_key(page):
    """What the page expects a stash to carry: the declared label, else the
    key as the store sees it — prefixed under a group, since that is what
    the section's own viewset stamps by default."""
    view = page()

    class _Nested(_Page):
        key = "about"

    assert view.stash_label(Section(CONTACT).bound("contact")) == "contact"
    assert view.stash_label(Section(CONTACT, label="v2").bound("contact")) == "v2"
    assert _Nested().stash_label(Section(CONTACT).bound("contact")) == "about:contact"


def test_a_section_without_a_key_is_misconfigured(rf):
    class _Keyless(_Page.viewset_for("contact")):
        key = None

    view = _contact_view(rf, {"gandalf_runs": {"run-1": {"state": []}}}, cls=_Keyless)

    with pytest.raises(ImproperlyConfigured, match="key"):
        view.done(_retrieved(view))


def test_a_section_without_a_page_to_return_to_is_misconfigured(rf):
    class _Homeless(_Page.viewset_for("contact")):
        task_list_url_name = None

    view = _contact_view(rf, cls=_Homeless)

    with pytest.raises(ImproperlyConfigured, match="task_list_url_name"):
        view.get_task_list_url()


# --- URLs ------------------------------------------------------------------


def test_a_row_links_to_the_pages_own_door_not_the_wizards_urls(page):
    url = page().get_entry_url(Section(CONTACT).bound("contact"))

    assert url == "/readme/task-list/contact/"


def test_a_page_forwards_its_mount_prefix_and_drops_the_entry_kwarg(rf):
    view = _page(
        _Page, rf, path="/org/acme/task-list/details/", org="acme", entry="details"
    )

    assert view.get_page_url_kwargs() == {"org": "acme"}
    assert view.entry_url_kwargs(
        Section(CONTACT, url_kwargs={"item": "x"}).bound("details")
    ) == {"org": "acme", "item": "x"}


def test_the_page_url_is_reversed_from_its_own_url_name(page):
    assert page().get_page_url() == "/readme/task-list/"


def test_an_unknown_entry_is_sent_back_to_the_page(rf):
    view = _page(_Page, rf, path="/readme/task-list/nope/")

    response = view.entry_unavailable("nope")

    assert response.status_code == 302
    assert response["Location"] == "/readme/task-list/"


def test_a_row_can_point_at_something_that_is_not_a_wizard(rf):
    """A payment redirect, a page in another app. The door exists to walk a
    run and pick a step; something with no run to walk has nothing for it to
    do, so the row addresses it directly."""
    linked = _list(guests=Link("readme-task-list", status=lambda r, k: COMPLETE))

    (row,) = _page(_view(linked), rf).get_rows()

    assert row.status == COMPLETE
    assert row.status_label == "Complete"
    assert row.url == "/readme/task-list/"


def test_the_door_refuses_an_entry_it_cannot_walk(rf):
    """Rows never point there, so arriving is a hand-typed or stale URL."""
    linked = _list(guests=Link("readme-task-list", status=lambda r, k: COMPLETE))
    view = _page(_view(linked), rf, path="/readme/task-list/guests/")

    assert view.enter(view.get_entry("guests")) is None


def test_a_page_without_an_entry_url_name_is_misconfigured(page):
    view = page()
    view.entry_url_name = None

    with pytest.raises(ImproperlyConfigured, match="entry_url_name"):
        view.get_entry_url(Section(CONTACT).bound("contact"))


def test_a_page_without_a_url_name_is_misconfigured(page):
    view = page()
    view.url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        view.get_page_url()
    with pytest.raises(ImproperlyConfigured, match="url_name"):

        class _Nameless(TaskListViewSet):
            task_list = type("_Contact", (_Contact,), {})

        _Nameless.urls()


def test_a_page_publishes_itself_its_entries_and_then_its_door():
    """The door comes last so an entry's own segment — a group's page, an
    add-another page — is reached directly."""
    root, contact, address, door = _PairPage.urls()

    assert root.name == "readme-task-list"
    assert str(contact.pattern) == "contact/"
    assert str(address.pattern) == "address/"
    assert door.name == "readme-task-list-entry"
    assert str(door.pattern) == "<slug:entry>/"


def test_a_sections_bare_url_is_the_pages_door():
    """A run whose every answer validates completes on a GET, so the one URL
    a `WizardViewSet` publishes first is replaced by the door for it, under
    the wizard's own URL name."""
    _root, contact, *_ = _PairPage.urls()
    start, run, step = contact.url_patterns

    assert start.name == "readme-task-list-contact"
    assert str(start.pattern) == ""
    assert start.default_args == {"entry": "contact"}
    assert start.callback.view_class is _PairPage
    assert (run.name, step.name) == (
        "readme-task-list-contact-run",
        "readme-task-list-contact-step",
    )
    assert step.callback.view_class is _PairPage.viewset_for("contact")


def test_a_link_publishes_no_routes():
    linked = _view(_list(pay=Link("readme-task-list", status=lambda r, k: COMPLETE)))

    root, door = linked.urls()

    assert (root.name, door.name) == ("readme-task-list", "readme-task-list-entry")


def _readme_page(rf, path, **kwargs):
    """The README's task list, dispatched directly — one view over two
    routes."""
    from tests.testapp.readme.ch12_task_list import GrantApplicationViewSet

    request = rf.get(path)
    request.session = _session()
    return GrantApplicationViewSet.as_view()(request, **kwargs)


def test_the_page_renders_the_rows(rf):
    response = _readme_page(rf, "/readme/task-list/")

    assert response.status_code == 200
    assert [row.key for row in response.context_data["task_list"].rows] == [
        "contact",
        "address",
    ]


def test_the_door_redirects_into_the_section_it_names(rf):
    response = _readme_page(rf, "/readme/task-list/contact/", entry="contact")

    assert response.status_code == 302
    assert response["Location"].startswith("/readme/task-list/contact/")
    assert response["Location"].endswith("/name/")


def test_the_door_sends_an_entry_it_cannot_walk_back_to_the_page(rf):
    """A link links past the door anyway — so arriving here is a hand-typed
    or stale URL."""
    linked = _view(
        _list(elsewhere=Link("readme-task-list", status=lambda r, k: COMPLETE))
    )
    request = rf.get("/readme/task-list/elsewhere/")
    request.session = _session()

    response = linked.as_view()(request, entry="elsewhere")

    assert response.status_code == 302
    assert response["Location"] == "/readme/task-list/"


def test_the_door_sends_an_unknown_entry_back_to_the_page(rf):
    response = _readme_page(rf, "/readme/task-list/nope/", entry="nope")

    assert response.status_code == 302
    assert response["Location"] == "/readme/task-list/"


# --- a section that is hidden -----------------------------------------------


class _Partner(SectionViewSet):
    """A section that only exists once an answer elsewhere says so."""

    wizard = CONTACT

    @classmethod
    def hidden(cls, store):
        return not store.data.get("has_partner", False)


class _WithPartner(TaskList):
    contact = Section(CONTACT, title="Contact details")
    address = Section(_Partner, title="Partner")


@pytest.fixture
def partner_page(rf):
    def build(session=None):
        return _page(_view(_WithPartner), rf, session)

    return build


def test_a_hidden_section_is_not_listed(partner_page):
    rows = partner_page().get_rows()

    assert [row.key for row in rows] == ["contact"]


def test_a_hidden_section_is_not_counted(partner_page):
    """Hidden is gone, not locked: a fresh page with one hidden row is a page
    of one section, and finishing that one completes it."""
    view = partner_page({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    result = view.get_page()

    assert (result.count, result.completed, result.blocked) == (1, 1, 0)
    assert result.status == COMPLETE


def test_a_section_appears_once_the_answer_that_reveals_it_is_given(partner_page):
    view = partner_page({"data": {"journey": {"has_partner": True}}})

    rows = view.get_rows()

    assert [row.key for row in rows] == ["contact", "address"]
    assert rows[1].status == NOT_STARTED


def test_a_hidden_section_is_unknown_at_the_door(partner_page):
    """A stale link to a section that no longer applies is refused the way a
    key the page never declared is, so no run is minted for it."""
    view = partner_page()

    with pytest.raises(EntryNotFound):
        view.get_entry("address")
    assert SessionJourneyStore(view.request, "default").get_run("address") is None


def test_the_driven_door_refuses_a_section_that_is_not_there(partner_page):
    """`get_entry()` refuses a hidden entry at the page's door. A caller
    with no request never reaches that door, so the section asks the same
    question of itself."""
    view = partner_page()
    section = type(view).viewset_for("address")()
    section.setup(view.request)

    with pytest.raises(DoorRefused) as refusal:
        section.check_door()

    assert refusal.value.reason == EntryUnavailable.HIDDEN


def test_the_driven_door_opens_when_the_page_would(partner_page):
    """The gate is the page's rules, not a rule against callers."""
    view = partner_page({"data": {"journey": {"has_partner": True}}})
    section = type(view).viewset_for("address")()
    section.setup(view.request)

    assert section.check_door() is None


def test_hidden_outranks_blocked(rf):
    """A section that does not exist cannot also be waiting."""

    class _Both(SectionViewSet):
        wizard = CONTACT

        @classmethod
        def blocked(cls, store):
            return True

        @classmethod
        def hidden(cls, store):
            return True

    result = _page(_view(_list(address=Section(_Both))), rf).get_page()

    assert result.count == 0
    assert result.blocked == 0


def test_a_page_override_can_hide_on_the_sections_behalf(partner_page):
    """`entry_hidden()` mirrors `entry_blocked()`: the page's hook for what
    one section cannot answer alone, replacing the question."""
    view = partner_page()
    view.entry_hidden = lambda entry, store: entry.key == "contact"

    # Contact is hidden by the page; Partner, which its own rule would have
    # hidden, is listed — the override replaced the question.
    assert [row.key for row in view.get_rows()] == ["address"]


# --- the journey ------------------------------------------------------------


def test_a_page_reads_its_journey_off_the_url_when_mounted_under_one(rf):
    view = _page(_Page, rf, path="/apply/app-1/", journey="app-1")

    assert view.get_journey() == "app-1"
    assert view.get_page_url_kwargs() == {"journey": "app-1"}


def test_a_page_mounted_under_no_journey_uses_the_one_it_declares(page):
    view = page()

    assert view.get_journey() == "default"
    assert view.get_page_url_kwargs() == {}


def test_a_page_keeps_its_bookkeeping_under_its_journey(rf):
    """Two journeys in one session are two task lists."""
    request = rf.get("/apply/app-2/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}, journey="app-1"
    )
    view = _JourneyPage()
    view.setup(request, journey="app-2")

    (row,) = view.get_rows()

    assert row.status == NOT_STARTED


def test_the_door_hands_every_section_view_the_journey(rf):
    """A section is mounted beneath its page, so every kwarg the page came
    in with — the journey, a mount prefix — reaches the run it starts."""
    seen = []

    class _Recording(_Page.viewset_for("contact")):
        @classmethod
        def begin(cls, request, **url_kwargs):
            seen.append(url_kwargs)
            return super().begin(request)

    view = _page(_Page, rf, path="/apply/app-1/task-list/", journey="app-1", org="acme")
    view.entries = [view.get_entry("contact").bound("contact", _Recording)]
    del view._entries_cache

    view.enter(view.get_entry("contact"))

    assert seen == [{"journey": "app-1", "org": "acme"}]
    assert SessionJourneyStore(view.request, "app-1").get_run("contact") is not None


def test_a_status_callable_is_handed_the_journey_too(rf):
    seen = []
    linked = _view(
        _list(
            guests=Link(
                "readme-apply",
                title="Guests",
                status=lambda request, url_kwargs: seen.append(url_kwargs) or COMPLETE,
            )
        ),
        url_name="readme-apply",
    )
    view = _page(linked, rf, path="/apply/app-1/task-list/", journey="app-1")

    view.get_rows()

    assert seen == [{"journey": "app-1"}]


def test_a_pages_sections_share_its_journey_by_construction():
    class _Profiled(_Page):
        journey = "profile"
        journey_url_kwarg = "application"

    viewset = _Profiled.viewset_for("contact")

    assert (viewset.journey, viewset.journey_url_kwarg) == ("profile", "application")


def test_a_section_reads_its_journey_off_the_url_when_mounted_under_one(rf):
    view = _Page.viewset_for("contact")()
    view.setup(rf.get("/apply/app-1/contact/"), journey="app-1")

    assert view.get_journey() == "app-1"
    assert view.get_journey_store().journey == "app-1"


def test_finishing_a_section_writes_what_it_decided_where_the_page_reads_it(rf):
    """The whole point of `store.data`: one walk at completion, and every
    later render reads a string."""

    class _Deciding(SectionViewSet):
        wizard = CONTACT

        def run_done(self, run):
            step = run.path.find_step(name="first")
            self.get_journey_store().data["name"] = step.form.cleaned_data["name"]
            return super().run_done(run)

    viewset = _view(_list(contact=Section(_Deciding))).viewset_for("contact")
    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=viewset,
    )

    view.done(viewset.inspect(view.request, "run-1"))

    context = WizardContext.from_request(view.request)
    assert SessionJourneyStore(context, "default").data["name"] == "Ada"


# --- beginning a journey ------------------------------------------------------


def test_beginning_a_journey_hands_back_its_id_store_and_page(rf):
    journey = _JourneyPage.begin(_page(_Page, rf).request)

    assert journey.url == f"/readme/apply/{journey.id}/"
    assert journey.store.keys() == []


def test_beginning_can_be_given_the_journey(rf):
    assert _JourneyPage.begin(_page(_Page, rf).request, journey="app-9").url == (
        "/readme/apply/app-9/"
    )


def test_beginning_a_journey_for_a_page_not_under_one_lands_on_its_one_page(rf):
    """One journey per session: there is no segment to put the id in."""
    assert _Page.begin(_page(_Page, rf).request).url == "/readme/task-list/"


def test_finishing_a_section_records_the_run_as_the_page_would(rf):
    """Stashed under the section's key, its run cleared — exactly what
    finishing it from the page's own door does, under the new journey."""
    view = _contact_view(
        rf, {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    journey = _JourneyPage.begin(view.request)

    journey.finish("contact", _retrieved(view))

    assert journey.store.get_stash("contact")["state"] == [{"step": {"name": "Ada"}}]
    assert journey.store.get_run("contact") is None


def test_finishing_an_unknown_section_is_refused(rf):
    with pytest.raises(EntryNotFound):
        _JourneyPage.begin(_page(_Page, rf).request).finish("nope", None)


# --- submitting the journey ---------------------------------------------------


class _Submittable(_PairPage):
    def journey_done(self, page, store):
        store.data["reference"] = f"REF-{page.completed}"
        from django.http import HttpResponse

        return HttpResponse(b"submitted")


def _complete_pair():
    return {
        "stashes": {
            "contact": _stash([{"step": {"name": "Ada"}}]),
            "address": _stash([{"step": {"name": "Ada"}}], label="address"),
        }
    }


def test_submitting_a_complete_journey_does_the_work_then_tombstones_it(rf):
    view = _page(_Submittable, rf, _complete_pair(), method="post")

    response = view.submit()

    store = SessionJourneyStore(view.request, "default")
    assert response.content == b"submitted"
    assert store.is_complete() is True
    assert store.keys() == []
    assert store.data["reference"] == "REF-2"


def test_submitting_an_incomplete_journey_is_refused(rf):
    """A stale button or a hand-made POST cannot submit half a journey."""
    view = _page(
        _Submittable,
        rf,
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}},
        method="post",
    )

    response = view.submit()

    assert response.status_code == 302
    assert response["Location"] == "/readme/task-list/"
    assert SessionJourneyStore(view.request, "default").is_complete() is False


def test_a_journey_done_that_raises_leaves_the_journey_resumable(rf):
    """`done()`'s ordering, one level up: the work first, the tombstone only
    once it has succeeded."""

    class _Failing(_Submittable):
        def journey_done(self, page, store):
            raise RuntimeError("nope")

    view = _page(_Failing, rf, _complete_pair(), method="post")

    with pytest.raises(RuntimeError):
        view.submit()

    store = SessionJourneyStore(view.request, "default")
    assert store.is_complete() is False
    assert store.keys() == ["contact", "address"]


def test_a_page_with_nothing_to_do_at_submit_is_misconfigured(rf):
    view = _page(_PairPage, rf, _complete_pair(), method="post")

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        view.submit()


def test_a_page_says_a_submitted_journey_is_gone_by_default(rf):
    from django.http import Http404

    view = _page(_Page, rf, {"completed": True})

    with pytest.raises(Http404):
        view.submitted(view.get_journey_store())


def _apply(rf, method, path, session=None, **kwargs):
    """The README's application, dispatched directly under a journey."""
    from tests.testapp.readme.ch15_journey import GrantApplicationViewSet

    request = getattr(rf, method)(path)
    request.session = _session(session, journey="app-1")
    return GrantApplicationViewSet.as_view()(request, journey="app-1", **kwargs)


@pytest.mark.django_db
def test_a_post_to_the_page_submits_the_journey(rf):
    line = "11111111-1111-1111-1111-111111111111"
    response = _apply(
        rf,
        "post",
        "/readme/apply/app-1/",
        {
            "stashes": {
                "setup": _stash([{"step": {"applying_as": "individual"}}], "setup"),
                "contact": _stash(
                    [{"step": {"full_name": "Ada"}}, {"step": {"email": "a@b.c"}}],
                    "contact",
                ),
                "project": _stash([{"step": {}}], "project"),
                "supporting:referees": _stash([{"step": {}}], "supporting:referees"),
                f"budget:{line}": _stash([{"step": {}}], "budget"),
            },
            "lists": {
                "budget": {
                    "items": [{"id": line, "title": "Paint"}],
                    "declared_done": True,
                }
            },
            "data": {"journey": {"email": "a@b.c"}},
        },
    )

    assert response.status_code == 302
    assert response["Location"] == "/readme/apply/app-1/"
    # The refusal redirects to the same page, so prove the work happened.
    from tests.testapp.models import Application

    assert Application.objects.get().email == "a@b.c"


def test_a_post_to_the_door_submits_nothing(rf):
    """The route that opens a section never finishes anything."""
    response = _apply(rf, "post", "/readme/apply/app-1/contact/", entry="contact")

    assert response.status_code == 405


def test_a_submitted_journeys_page_renders_what_the_tombstone_kept(rf):
    response = _apply(
        rf,
        "get",
        "/readme/apply/app-1/",
        {"completed": True, "data": {"journey": {"reference": "APP-1"}}},
    )

    assert response.status_code == 200
    assert b"Application submitted" in response.content
    assert b"APP-1" in response.content


def test_a_submitted_journeys_door_is_refused(rf):
    response = _apply(
        rf,
        "get",
        "/readme/apply/app-1/contact/",
        {"completed": True, "data": {"journey": {"reference": "APP-1"}}},
        entry="contact",
    )

    assert b"Application submitted" in response.content


def test_a_submitted_journeys_section_wizard_refuses_a_bookmarked_url(rf):
    """A stale run URL must not re-open a section into a tombstone."""
    from tests.testapp.readme.ch15_journey import GrantApplicationViewSet

    request = rf.get("/readme/apply/app-1/contact/run-1/")
    request.session = _session({"completed": True}, journey="app-1")

    response = GrantApplicationViewSet.viewset_for("contact").as_view()(
        request, journey="app-1", run_id="run-1"
    )

    assert response.status_code == 302
    assert response["Location"] == "/readme/apply/app-1/"


def test_an_add_another_entry_is_a_page_beneath_the_list():
    """Declared as an entry, an add-another is built beneath the page with
    its key and its return composed — as any entry is."""
    from gandalf.add_another import AddAnotherViewSet

    guests = AddAnother(CONTACT, item_name="Guest", item_title="name")
    viewset = _view(_list(guests=guests), url_name="party-task-list").viewset_for(
        "guests"
    )

    assert issubclass(viewset, AddAnotherViewSet)
    assert viewset.key == "guests"
    assert viewset.url_name == "party-task-list-guests"
    assert viewset.task_list_url_name == "party-task-list"
    assert viewset.item_viewset.list_key == "guests"


def test_a_group_entry_is_a_page_beneath_the_list():
    class _Inner(TaskList):
        x = Section(CONTACT)

    viewset = _view(
        _list(inner=Group(_Inner, template_name="testapp/nested_task_list.html"))
    ).viewset_for("inner")

    assert issubclass(viewset, TaskListViewSet)
    assert viewset.task_list is _Inner
    assert viewset.key == "inner"
    assert viewset.template_name == "testapp/nested_task_list.html"


# --- an entry as a value ---------------------------------------------------------


def test_entries_compare_by_their_facts_and_key():
    """The same declaration bound twice is two entries; a different kind
    with the same facts is not the same entry."""
    assert Section(CONTACT, title="A") == Section(CONTACT, title="A")
    assert Section(CONTACT).bound("a") != Section(CONTACT).bound("b")
    assert Section(CONTACT) != Link("readme-task-list", status=lambda r, k: COMPLETE)
    assert (Section(CONTACT) == "not an entry") is False
    assert len({Section(CONTACT).bound("a"), Section(CONTACT).bound("a")}) == 1
    assert repr(Section(CONTACT, title="A").bound("a")).startswith("Section(title='A'")


def test_a_link_replaced_keeps_its_target():
    link = Link("readme-task-list", title="Pay", status=lambda r, k: COMPLETE)

    assert link.replace(title="Pay now").url_name == "readme-task-list"
    assert link.bound("pay").status is link.status


def test_a_list_mounted_twice_by_unrelated_pages_is_refused():
    class _Twice(TaskList):
        only = Section(CONTACT)

    class _First(TaskListViewSet):
        url_name = "readme-task-list"
        template_name = "testapp/task_list.html"
        task_list = _Twice

    with pytest.raises(ImproperlyConfigured, match="already mounted by _First"):

        class _Second(TaskListViewSet):
            url_name = "readme-apply"
            template_name = "testapp/task_list.html"
            task_list = _Twice


def test_a_subclass_of_the_mounting_page_is_the_same_page():
    """A store-swapping refinement, a test's subclass: the same page, so the
    first mount stands."""

    class _Once(TaskList):
        only = Section(CONTACT)

    class _Page(TaskListViewSet):
        url_name = "readme-task-list"
        template_name = "testapp/task_list.html"
        task_list = _Once

    class _Refined(_Page):
        url_name = "readme-apply"

    assert _Once.viewset is _Page
    assert issubclass(_Refined, _Page)
