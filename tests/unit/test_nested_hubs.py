"""A hub as a member of a hub.

Nesting is a key namespace over one journey record: a nested hub prefixes its
`member_key` onto every member it lists, its row on the parent reads its own
rows, and its submit returns to the parent without tombstoning anything. The
load-bearing claims are the ones that keep a nested hub honest — its keys
and its return are composed by the parent rather than typed, it is a
subclass of its root so the root's hooks reach it, and it has the same door
and ending shape as any member.
"""

from http import HTTPStatus

from gandalf.runtime import STASH_VERSION
from gandalf.hubs import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    Hub,
    HubViewSet,
    Member,
)
from tests.testapp.readme.ch14_journey import GrantApplicationViewSet, supporting


SupportingHubViewSet = GrantApplicationViewSet.viewset_for("supporting")
ContactMemberViewSet = GrantApplicationViewSet.viewset_for("contact")
RefereesMemberViewSet = SupportingHubViewSet.viewset_for("referees")


class _Session(dict):
    modified = False


JOURNEY = "app-1"


def _session(record=None):
    return _Session({"gandalf_journeys": {JOURNEY: dict(record or {})}})


def _stash(label):
    return {"version": STASH_VERSION, "label": label, "state": [{"step": {}}]}


#: Referees is blocked until contact details are stashed, so a record that
#: wants the supporting hub to be startable carries them.
CONTACT = {"contact": _stash("contact")}


def _request(rf, path="/readme/apply/app-1/", method="get", record=None):
    request = getattr(rf, method)(path)
    request.session = _session(record)
    return request


def _view(cls, request, **kwargs):
    view = cls()
    view.setup(request, journey=JOURNEY, **kwargs)
    return view


def _parent(**attributes):
    """The README's root, re-declared."""
    return type("_Parent", (GrantApplicationViewSet,), attributes)


# --- keys --------------------------------------------------------------------


def test_a_root_hub_keys_its_members_as_declared(rf):
    hub = _view(GrantApplicationViewSet, _request(rf))

    assert hub.get_member_key() is None
    assert hub.full_key(Member("contact")) == "contact"
    assert ContactMemberViewSet.member_key == "contact"


def test_a_nested_hub_prefixes_its_own_key_without_anyone_typing_it(rf):
    hub = _view(SupportingHubViewSet, _request(rf))

    assert hub.get_member_key() == "supporting"
    assert hub.full_key(Member("referees")) == "supporting:referees"
    assert RefereesMemberViewSet.member_key == "supporting:referees"


def test_nesting_composes_to_any_depth():
    class _Root(HubViewSet):
        url_name = "readme-apply"
        hub = Hub().hub(
            "supporting",
            Hub().hub("more", Hub().member("x", supporting.members[0].wizard)),
        )

    more = _Root.viewset_for("supporting").viewset_for("more")

    assert more.member_key == "supporting:more"
    assert more.viewset_for("x").member_key == "supporting:more:x"
    assert more.url_name == "readme-apply-supporting-more"
    assert more.hub_url_name == "readme-apply-supporting"


def test_a_hub_knows_a_member_that_is_a_hub():
    assert HubViewSet.is_hub(Member("supporting", SupportingHubViewSet))
    assert not HubViewSet.is_hub(Member("contact", ContactMemberViewSet))
    assert not HubViewSet.is_hub(
        Member("elsewhere", url_name="x", status=lambda r, k: 1)
    )


# --- what the parent composes ----------------------------------------------------


def test_a_nested_hub_returns_to_the_hub_that_lists_it():
    assert SupportingHubViewSet.hub_url_name == "readme-apply"
    assert SupportingHubViewSet.url_name == "readme-apply-supporting"
    assert RefereesMemberViewSet.hub_url_name == "readme-apply-supporting"


def test_a_nested_hub_shares_its_parents_journey_and_stores():
    class _Profiled(GrantApplicationViewSet):
        journey = "profile"
        journey_url_kwarg = "application"

    nested = _Profiled.viewset_for("supporting")

    assert (nested.journey, nested.journey_url_kwarg) == ("profile", "application")
    assert nested.journey_store_class is _Profiled.journey_store_class
    assert nested.viewset_for("referees").journey == "profile"


def test_a_nested_hub_takes_its_page_from_its_declaration():
    assert SupportingHubViewSet.template_name == "testapp/nested_hub.html"
    assert GrantApplicationViewSet.template_name == "testapp/journey_hub.html"


def test_a_nested_hub_inherits_its_parents_member_template():
    assert RefereesMemberViewSet.template_name == "testapp/linear_wizard.html"


def test_a_nested_hub_is_a_subclass_of_its_root_so_the_roots_hooks_reach_it(rf):
    class _Worded(GrantApplicationViewSet):
        def get_status_label(self, status):
            return f"[{status}]"

    nested = _Worded.viewset_for("supporting")
    assert issubclass(nested, _Worded)

    hub = _view(nested, _request(rf)).get_hub()
    assert [str(row.status_label) for row in hub.rows] == ["[blocked]"]


# --- the row -------------------------------------------------------------------


def _statuses(rf, record):
    hub = _view(GrantApplicationViewSet, _request(rf, record=record))
    return {row.key: row.status for row in hub.get_hub().rows}


def test_a_nested_hubs_status_is_its_own_rows(rf):
    """No stash is ever read for a hub: its completion is derived exactly as
    its own page derives it, from the members under its prefix."""
    assert _statuses(rf, {})["supporting"] == NOT_STARTED
    assert (
        _statuses(rf, {"runs": {"supporting:referees": "run-1"}})["supporting"]
        == NOT_STARTED
    )
    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    assert _statuses(rf, {"stashes": stashes})["supporting"] == COMPLETE


def test_a_nested_hub_can_be_blocked_and_hidden_by_its_row(rf):
    locked = _parent(hub=Hub().hub("supporting", supporting, blocked=lambda s: True))
    gone = _parent(hub=Hub().hub("supporting", supporting, hidden=lambda s: True))

    assert [row.status for row in _view(locked, _request(rf)).get_hub().rows] == [
        BLOCKED
    ]
    assert _view(gone, _request(rf)).get_hub().rows == ()


def test_a_nested_hubs_members_read_the_journeys_own_data(rf):
    """`hidden` on the governing document reads `applying_as`, which the
    setup member wrote at the root — one record, whatever the depth."""
    individual = _view(SupportingHubViewSet, _request(rf, record={}))
    organisation = _view(
        SupportingHubViewSet,
        _request(rf, record={"data": {"journey": {"applying_as": "organisation"}}}),
    )

    assert [row.key for row in individual.get_hub().rows] == ["referees"]
    assert [row.key for row in organisation.get_hub().rows] == [
        "referees",
        "documents",
    ]


def test_a_nested_hubs_row_links_at_its_page_and_so_does_the_door(rf):
    hub = _view(GrantApplicationViewSet, _request(rf))
    member = hub.get_member("supporting")

    assert hub.get_member_url(member) == "/readme/apply/app-1/supporting/"
    assert hub.enter(member) == "/readme/apply/app-1/supporting/"


def test_the_door_refuses_a_nested_hub_the_user_cannot_start_yet(rf):
    locked = _parent(hub=Hub().hub("supporting", supporting, blocked=lambda s: True))

    hub = _view(locked, _request(rf))

    assert hub.enter(hub.get_member("supporting")) is None


def test_a_nested_hub_is_mounted_beneath_its_parent_before_the_door():
    patterns = GrantApplicationViewSet.urls()
    segments = [str(pattern.pattern) for pattern in patterns]

    assert segments[0] == ""
    assert "supporting/" in segments
    assert segments.index("supporting/") < segments.index("<slug:member>/")
    nested = patterns[segments.index("supporting/")].url_patterns
    assert [str(p.pattern) for p in nested][0] == ""
    assert [str(p.pattern) for p in nested][-1] == "<slug:member>/"


# --- the ending ------------------------------------------------------------------


def test_a_nested_hub_is_nested_and_a_root_hub_is_not(rf):
    assert _view(SupportingHubViewSet, _request(rf)).is_nested is True
    assert _view(GrantApplicationViewSet, _request(rf)).is_nested is False


def test_a_nested_hubs_submit_returns_to_its_parent_and_keeps_the_record(rf):
    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    request = _request(
        rf, "/readme/apply/app-1/supporting/", "post", {"stashes": stashes}
    )
    hub = _view(SupportingHubViewSet, request)

    response = hub.submit()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/readme/apply/app-1/"
    assert hub.get_journey_store().is_complete() is False
    assert hub.get_journey_store().keys() == ["contact", "supporting:referees"]


def test_a_nested_hubs_submit_is_refused_while_incomplete(rf):
    request = _request(rf, "/readme/apply/app-1/supporting/", "post")

    response = _view(SupportingHubViewSet, request).submit()

    assert response["Location"] == "/readme/apply/app-1/supporting/"


def test_hub_done_is_the_nested_hubs_hook(rf):
    class _Recording(SupportingHubViewSet):
        def hub_done(self, hub, store):
            store.data["supporting_done"] = hub.completed
            return super().hub_done(hub, store)

    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    hub = _view(
        _Recording,
        _request(rf, "/readme/apply/app-1/supporting/", "post", {"stashes": stashes}),
    )

    hub.submit()

    assert hub.get_journey_store().data["supporting_done"] == 1


def test_a_nested_hub_under_a_submitted_journey_sends_the_user_up(rf):
    """The root's `journey_completed()` renders the done page; a nested hub
    inherits that method but never fires it — dispatch sends the user up
    to the root, which is the page that can say what submitted looks like."""
    request = _request(
        rf, "/readme/apply/app-1/supporting/", record={"completed": True}
    )

    response = SupportingHubViewSet.as_view()(request, journey=JOURNEY)

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/readme/apply/app-1/"


def test_a_nested_hub_reports_incomplete_between(rf):
    record = {
        "stashes": CONTACT | {"supporting:referees": _stash("supporting:referees")},
        "data": {"journey": {"applying_as": "organisation"}},
    }

    assert _statuses(rf, record)["supporting"] == INCOMPLETE
