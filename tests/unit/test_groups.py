"""A task list as an entry of a task list.

A group is a key namespace over one journey record: its page prefixes its
key onto every entry it lists, its row on the parent reads its own rows,
and its Continue returns to the parent without tombstoning anything. The
load-bearing claims are the ones that keep a group honest — its keys and
its return are composed by the parent rather than typed, its page is a
subclass of its root so the root's hooks reach it, and it has the same
door and ending shape as any entry.
"""

from http import HTTPStatus

from gandalf.runtime import STASH_VERSION
from gandalf.tasklists import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    Group,
    Link,
    Section,
    TaskList,
    TaskListViewSet,
)
from tests.testapp.forms import FirstStepForm
from tests.testapp.readme.ch14_journey import (
    GrantApplicationViewSet,
    SupportingInformation,
)
from gandalf.wizard import Wizard


SupportingViewSet = GrantApplicationViewSet.viewset_for("supporting")
ContactSectionViewSet = GrantApplicationViewSet.viewset_for("contact")
RefereesSectionViewSet = SupportingViewSet.viewset_for("referees")

FIRST = Wizard().step(FirstStepForm, name="first")


class _Session(dict):
    modified = False


JOURNEY = "app-1"


def _session(record=None):
    return _Session({"gandalf_journeys": {JOURNEY: dict(record or {})}})


def _stash(label):
    return {"version": STASH_VERSION, "label": label, "state": [{"step": {}}]}


#: Referees is blocked until contact details are stashed, so a record that
#: wants the supporting group to be startable carries them.
CONTACT = {"contact": _stash("contact")}


def _request(rf, path="/readme/apply/app-1/", method="get", record=None):
    request = getattr(rf, method)(path)
    request.session = _session(record)
    return request


def _view(cls, request, **kwargs):
    view = cls()
    view.setup(request, journey=JOURNEY, **kwargs)
    return view


# --- keys --------------------------------------------------------------------


def test_a_root_page_keys_its_entries_as_declared(rf):
    page = _view(GrantApplicationViewSet, _request(rf))

    assert page.get_key() is None
    assert page.full_key(Section(FIRST).bound("contact")) == "contact"
    assert ContactSectionViewSet.key == "contact"


def test_a_group_prefixes_its_own_key_without_anyone_typing_it(rf):
    page = _view(SupportingViewSet, _request(rf))

    assert page.get_key() == "supporting"
    assert page.full_key(Section(FIRST).bound("referees")) == "supporting:referees"
    assert RefereesSectionViewSet.key == "supporting:referees"


def test_nesting_composes_to_any_depth():
    class _X(TaskList):
        x = Section(FIRST)

    class _More(TaskList):
        more = Group(_X)

    class _Root(TaskList):
        supporting = Group(_More)

    class _RootViewSet(TaskListViewSet):
        url_name = "readme-apply"
        tasklist = _Root

    more = _RootViewSet.viewset_for("supporting").viewset_for("more")

    assert more.key == "supporting:more"
    assert more.viewset_for("x").key == "supporting:more:x"
    assert more.url_name == "readme-apply-supporting-more"
    assert more.tasklist_url_name == "readme-apply-supporting"


def test_a_page_knows_an_entry_that_is_a_group():
    assert TaskListViewSet.is_group(
        Group(TaskList).bound("supporting", SupportingViewSet)
    )
    assert not TaskListViewSet.is_group(
        Section(FIRST).bound("contact", ContactSectionViewSet)
    )
    assert not TaskListViewSet.is_group(
        Link("x", status=lambda r, k: 1).bound("elsewhere")
    )


# --- what the parent composes ----------------------------------------------------


def test_a_group_returns_to_the_page_that_lists_it():
    assert SupportingViewSet.tasklist_url_name == "readme-apply"
    assert SupportingViewSet.url_name == "readme-apply-supporting"
    assert RefereesSectionViewSet.tasklist_url_name == "readme-apply-supporting"


def test_a_group_shares_its_parents_journey_and_stores():
    class _Profiled(GrantApplicationViewSet):
        journey = "profile"
        journey_url_kwarg = "application"

    nested = _Profiled.viewset_for("supporting")

    assert (nested.journey, nested.journey_url_kwarg) == ("profile", "application")
    assert nested.journey_store_class is _Profiled.journey_store_class
    assert nested.viewset_for("referees").journey == "profile"


def test_a_group_takes_its_page_from_its_entry_and_its_entries_from_its_list():
    assert SupportingViewSet.tasklist is SupportingInformation
    assert SupportingViewSet.template_name == "testapp/nested_hub.html"
    assert GrantApplicationViewSet.template_name == "testapp/journey_hub.html"


def test_a_group_without_a_page_of_its_own_renders_with_its_roots():
    class _Inner(TaskList):
        x = Section(FIRST)

    class _Root(TaskList):
        inner = Group(_Inner)

    class _RootViewSet(TaskListViewSet):
        url_name = "readme-apply"
        template_name = "testapp/hub.html"
        tasklist = _Root

    assert _RootViewSet.viewset_for("inner").template_name == "testapp/hub.html"


def test_a_group_inherits_its_parents_section_template():
    assert RefereesSectionViewSet.template_name == "testapp/linear_wizard.html"


def test_a_group_is_a_subclass_of_its_root_so_the_roots_hooks_reach_it(rf):
    class _Worded(GrantApplicationViewSet):
        def get_status_label(self, status):
            return f"[{status}]"

    nested = _Worded.viewset_for("supporting")
    assert issubclass(nested, _Worded)

    page = _view(nested, _request(rf)).get_page()
    assert [str(row.status_label) for row in page.rows] == ["[blocked]"]


def test_a_groups_page_is_not_registered_as_the_lists_way_in():
    """A group is reached through its root, so beginning a journey on the
    group's list would have no page of its own to land on."""
    assert SupportingInformation.viewset is None


# --- the row -------------------------------------------------------------------


def _statuses(rf, record):
    page = _view(GrantApplicationViewSet, _request(rf, record=record))
    return {row.key: row.status for row in page.get_page().rows}


def test_a_groups_status_is_its_own_rows(rf):
    """No stash is ever read for a group: its completion is derived exactly
    as its own page derives it, from the sections under its prefix."""
    assert _statuses(rf, {})["supporting"] == NOT_STARTED
    assert (
        _statuses(rf, {"runs": {"supporting:referees": "run-1"}})["supporting"]
        == NOT_STARTED
    )
    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    assert _statuses(rf, {"stashes": stashes})["supporting"] == COMPLETE


def test_a_group_can_be_blocked_and_hidden_by_its_root(rf):
    class _Locked(GrantApplicationViewSet):
        def entry_blocked(self, entry, store):
            return entry.key == "supporting"

    class _Gone(GrantApplicationViewSet):
        def entry_hidden(self, entry, store):
            return entry.key == "supporting"

    locked = {
        row.key: row.status for row in _view(_Locked, _request(rf)).get_page().rows
    }
    gone = [row.key for row in _view(_Gone, _request(rf)).get_page().rows]

    assert locked["supporting"] == BLOCKED
    assert "supporting" not in gone


def test_a_groups_sections_read_the_journeys_own_data(rf):
    """`hidden` on the governing document reads `applying_as`, which the
    setup section wrote at the root — one record, whatever the depth."""
    individual = _view(SupportingViewSet, _request(rf, record={}))
    organisation = _view(
        SupportingViewSet,
        _request(rf, record={"data": {"journey": {"applying_as": "organisation"}}}),
    )

    assert [row.key for row in individual.get_page().rows] == ["referees"]
    assert [row.key for row in organisation.get_page().rows] == [
        "referees",
        "documents",
    ]


def test_a_groups_row_links_at_its_page_and_so_does_the_door(rf):
    page = _view(GrantApplicationViewSet, _request(rf))
    entry = page.get_entry("supporting")

    assert page.get_entry_url(entry) == "/readme/apply/app-1/supporting/"
    assert page.enter(entry) == "/readme/apply/app-1/supporting/"


def test_the_door_refuses_a_group_the_user_cannot_start_yet(rf):
    class _Locked(GrantApplicationViewSet):
        def entry_blocked(self, entry, store):
            return entry.key == "supporting"

    page = _view(_Locked, _request(rf))

    assert page.enter(page.get_entry("supporting")) is None


def test_a_group_is_mounted_beneath_its_parent_before_the_door():
    patterns = GrantApplicationViewSet.urls()
    segments = [str(pattern.pattern) for pattern in patterns]

    assert segments[0] == ""
    assert "supporting/" in segments
    assert segments.index("supporting/") < segments.index("<slug:entry>/")
    nested = patterns[segments.index("supporting/")].url_patterns
    assert [str(p.pattern) for p in nested][0] == ""
    assert [str(p.pattern) for p in nested][-1] == "<slug:entry>/"


# --- the ending ------------------------------------------------------------------


def test_a_group_is_nested_and_a_root_page_is_not(rf):
    assert _view(SupportingViewSet, _request(rf)).is_nested is True
    assert _view(GrantApplicationViewSet, _request(rf)).is_nested is False


def test_a_groups_submit_returns_to_its_parent_and_keeps_the_record(rf):
    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    request = _request(
        rf, "/readme/apply/app-1/supporting/", "post", {"stashes": stashes}
    )
    page = _view(SupportingViewSet, request)

    response = page.submit()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/readme/apply/app-1/"
    assert page.get_journey_store().is_complete() is False
    assert page.get_journey_store().keys() == ["contact", "supporting:referees"]


def test_a_groups_submit_is_refused_while_incomplete(rf):
    request = _request(rf, "/readme/apply/app-1/supporting/", "post")

    response = _view(SupportingViewSet, request).submit()

    assert response["Location"] == "/readme/apply/app-1/supporting/"


def test_group_done_is_the_groups_hook(rf):
    class _Recording(SupportingViewSet):
        def group_done(self, page, store):
            store.data["supporting_done"] = page.completed
            return super().group_done(page, store)

    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    page = _view(
        _Recording,
        _request(rf, "/readme/apply/app-1/supporting/", "post", {"stashes": stashes}),
    )

    page.submit()

    assert page.get_journey_store().data["supporting_done"] == 1


def test_a_group_under_a_submitted_journey_sends_the_user_up(rf):
    """The root's `submitted()` renders the done page; a group inherits
    that method but never fires it — dispatch sends the user up to the
    root, which is the page that can say what submitted looks like."""
    request = _request(
        rf, "/readme/apply/app-1/supporting/", record={"completed": True}
    )

    response = SupportingViewSet.as_view()(request, journey=JOURNEY)

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/readme/apply/app-1/"


def test_a_group_reports_incomplete_between(rf):
    record = {
        "stashes": CONTACT | {"supporting:referees": _stash("supporting:referees")},
        "data": {"journey": {"applying_as": "organisation"}},
    }

    assert _statuses(rf, record)["supporting"] == INCOMPLETE
