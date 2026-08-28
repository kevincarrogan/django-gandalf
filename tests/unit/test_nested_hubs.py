"""A hub as a section of a hub.

Nesting is a key namespace over one journey record: a nested hub prefixes its
`section_key` onto every section it lists, its row on the parent reads its own
rows, and its submit returns to the parent without tombstoning anything. The
load-bearing claims are the ones that keep a nested hub honest — the same
three drift checks a wizard section gets, and the same door and ending shape.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf.runtime import STASH_VERSION
from gandalf.sections import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    HubMixin,
    Section,
)
from tests.testapp.readme.ch14_journey import (
    ContactSectionViewSet,
    GrantApplicationHubView,
    RefereesSectionViewSet,
    SupportingHubView,
)


class _Session(dict):
    modified = False


JOURNEY = "app-1"


def _session(record=None):
    return _Session({"gandalf_journeys": {JOURNEY: dict(record or {})}})


def _stash(label):
    return {"version": STASH_VERSION, "label": label, "state": [{"step": {}}]}


#: Referees is `blocked()` until contact details are stashed, so a record
#: that wants the supporting hub to be startable carries them.
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


def test_a_root_hub_keys_its_sections_as_declared(rf):
    hub = _view(GrantApplicationHubView, _request(rf))

    assert hub.get_section_key() is None
    assert hub.full_key(Section("contact", ContactSectionViewSet)) == "contact"


def test_a_nested_hub_prefixes_its_own_key(rf):
    hub = _view(SupportingHubView, _request(rf))

    assert hub.get_section_key() == "supporting"
    assert hub.full_key(Section("referees", RefereesSectionViewSet)) == (
        "supporting:referees"
    )


def test_nesting_composes_to_any_depth(rf):
    class _Deeper(SupportingHubView):
        section_key = "supporting:more"

    assert _view(_Deeper, _request(rf)).full_key(Section("x")) == "supporting:more:x"


def test_a_hub_knows_a_section_that_is_a_hub():
    assert HubMixin.is_hub(Section("supporting", SupportingHubView))
    assert not HubMixin.is_hub(Section("contact", ContactSectionViewSet))
    assert not HubMixin.is_hub(
        Section("elsewhere", url_name="x", status=lambda r, k: 1)
    )


# --- the drift checks, one level up ------------------------------------------


def _validate(rf, **attributes):
    hub = _view(type("_Hub", (GrantApplicationHubView,), attributes), _request(rf))
    return hub._validate_sections(hub.get_sections())


def test_a_nested_hub_must_key_itself_as_its_parent_lists_it(rf):
    class _Elsewhere(SupportingHubView):
        section_key = "extras"

    with pytest.raises(ImproperlyConfigured, match="expected 'supporting'.*'extras'"):
        _validate(rf, sections=[Section("supporting", _Elsewhere)])


def test_a_nested_hub_may_not_leave_its_key_unset(rf):
    """A wizard section declaring no key does its own bookkeeping; a hub
    declaring none would file its sections at the root beside the parent's."""

    class _Unkeyed(SupportingHubView):
        section_key = None

    with pytest.raises(ImproperlyConfigured, match="must match"):
        _validate(rf, sections=[Section("supporting", _Unkeyed)])


def test_a_nested_hub_must_return_to_the_hub_that_lists_it(rf):
    class _Astray(SupportingHubView):
        hub_url_name = "readme-hub"

    with pytest.raises(ImproperlyConfigured, match="must return to the hub"):
        _validate(rf, sections=[Section("supporting", _Astray)])

    class _Rootless(SupportingHubView):
        hub_url_name = None

    with pytest.raises(ImproperlyConfigured, match="must return to the hub"):
        _validate(rf, sections=[Section("supporting", _Rootless)])


def test_a_nested_hub_must_be_mounted(rf):
    class _Unmounted(SupportingHubView):
        url_name = None

    with pytest.raises(ImproperlyConfigured, match="Unmounted: supporting"):
        _validate(rf, sections=[Section("supporting", _Unmounted)])


def test_a_nested_hub_must_share_its_parents_journey(rf):
    class _Other(SupportingHubView):
        journey_url_kwarg = "application"

    with pytest.raises(ImproperlyConfigured, match="Astray: supporting"):
        _validate(rf, sections=[Section("supporting", _Other)])


# --- the row -------------------------------------------------------------------


def _statuses(rf, record):
    hub = _view(GrantApplicationHubView, _request(rf, record=record))
    return {row.key: row.status for row in hub.get_hub().rows}


def test_a_nested_hubs_status_is_its_own_rows(rf):
    """No stash is ever read for a hub: its completion is derived exactly as
    its own page derives it, from the sections under its prefix."""
    assert _statuses(rf, {})["supporting"] == NOT_STARTED
    assert (
        _statuses(rf, {"runs": {"supporting:referees": "run-1"}})["supporting"]
        == NOT_STARTED
    )
    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    assert _statuses(rf, {"stashes": stashes})["supporting"] == COMPLETE


def test_a_nested_hub_answers_blocked_and_hidden_for_itself(rf):
    class _Locked(SupportingHubView):
        @classmethod
        def blocked(cls, request, section, store):
            return True

    class _Gone(SupportingHubView):
        @classmethod
        def hidden(cls, request, section, store):
            return True

    class _LockedParent(GrantApplicationHubView):
        sections = [Section("supporting", _Locked)]

    class _GoneParent(GrantApplicationHubView):
        sections = [Section("supporting", _Gone)]

    locked = _view(_LockedParent, _request(rf)).get_hub()
    gone = _view(_GoneParent, _request(rf)).get_hub()

    assert [row.status for row in locked.rows] == [BLOCKED]
    assert gone.rows == ()


def test_a_nested_hubs_sections_read_the_journeys_own_data(rf):
    """`hidden()` on the governing document reads `applying_as`, which the
    setup section wrote at the root — one record, whatever the depth."""
    individual = _view(SupportingHubView, _request(rf, record={}))
    organisation = _view(
        SupportingHubView,
        _request(rf, record={"data": {"journey": {"applying_as": "organisation"}}}),
    )

    assert [row.key for row in individual.get_hub().rows] == ["referees"]
    assert [row.key for row in organisation.get_hub().rows] == [
        "referees",
        "documents",
    ]


def test_a_nested_hubs_row_links_at_its_page_and_so_does_the_door(rf):
    hub = _view(GrantApplicationHubView, _request(rf))
    section = hub.get_section("supporting")

    assert hub.get_section_url(section) == "/readme/apply-supporting/app-1/"
    assert hub.enter(section) == "/readme/apply-supporting/app-1/"


def test_the_door_refuses_a_nested_hub_the_user_cannot_start_yet(rf):
    class _Locked(SupportingHubView):
        @classmethod
        def blocked(cls, request, section, store):
            return True

    class _Parent(GrantApplicationHubView):
        sections = [Section("supporting", _Locked)]

    hub = _view(_Parent, _request(rf))

    assert hub.enter(hub.get_section("supporting")) is None


# --- the ending ------------------------------------------------------------------


def test_a_nested_hub_is_nested_and_a_root_hub_is_not(rf):
    assert _view(SupportingHubView, _request(rf)).is_nested is True
    assert _view(GrantApplicationHubView, _request(rf)).is_nested is False


def test_a_nested_hubs_submit_returns_to_its_parent_and_keeps_the_record(rf):
    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    request = _request(
        rf, "/readme/apply-supporting/app-1/", "post", {"stashes": stashes}
    )
    hub = _view(SupportingHubView, request)

    response = hub.submit()

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/readme/apply/app-1/"
    assert hub.get_section_store().is_complete() is False
    assert hub.get_section_store().keys() == ["contact", "supporting:referees"]


def test_a_nested_hubs_submit_is_refused_while_incomplete(rf):
    request = _request(rf, "/readme/apply-supporting/app-1/", "post")

    response = _view(SupportingHubView, request).submit()

    assert response["Location"] == "/readme/apply-supporting/app-1/"


def test_hub_done_is_the_nested_hubs_hook(rf):
    class _Recording(SupportingHubView):
        def hub_done(self, hub, store):
            store.data["supporting_done"] = hub.completed
            return super().hub_done(hub, store)

    stashes = CONTACT | {"supporting:referees": _stash("supporting:referees")}
    hub = _view(
        _Recording,
        _request(rf, "/readme/apply-supporting/app-1/", "post", {"stashes": stashes}),
    )

    hub.submit()

    assert hub.get_section_store().data["supporting_done"] == 1


def test_a_nested_hub_under_a_submitted_journey_sends_the_user_up(rf):
    hub = _view(SupportingHubView, _request(rf, record={"completed": True}))

    response = hub.journey_completed(hub.get_section_store())

    assert response["Location"] == "/readme/apply/app-1/"


def test_a_nested_hub_reports_incomplete_between(rf):
    record = {
        "stashes": CONTACT | {"supporting:referees": _stash("supporting:referees")},
        "data": {"journey": {"applying_as": "organisation"}},
    }

    assert _statuses(rf, record)["supporting"] == INCOMPLETE
