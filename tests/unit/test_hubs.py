"""Unit coverage for the hub and spoke layer.

A hub lists parallel wizards the user drops in and out of. The display half
answers "how far has each got" without walking anything; the dispatch half
turns one click into a step URL, walking only the member the user chose.
The declaration half — `Hub()` — is what both are built from.
"""

from dataclasses import replace

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf.context import WizardContext
from gandalf.runtime import STASH_VERSION
from gandalf.hubs import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    Hub,
    HubPage,
    HubViewSet,
    Member,
    MemberNotFound,
    MemberRow,
    MemberViewSet,
)
from gandalf.storage import SessionJourneyStore, SessionStorage
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from tests.testapp.forms import FirstStepForm, SecondStepForm


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


CONTACT = Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second")


class _Hub(HubViewSet):
    """Named after this project's real hub, so every URL it builds reverses
    through the URLconf rather than being faked."""

    template_name = "testapp/hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-hub"
    hub = Hub().member("contact", CONTACT, title="Contact details")


class _JourneyHub(_Hub):
    """The same, under the README's journey mount: `apply/<journey>/`."""

    url_name = "readme-apply"


def _page(cls, rf, session=None, path="/readme/hub/", method="get", **kwargs):
    request = getattr(rf, method)(path)
    request.session = _session(session or {})
    view = cls()
    view.setup(request, **kwargs)
    return view


@pytest.fixture
def hub(rf):
    def build(session=None):
        return _page(_Hub, rf, session)

    return build


#: A real uuid, because a member's run routes match `<uuid:run_id>`.
RUN = "11111111-1111-1111-1111-111111111111"


def _stash(state, label="contact"):
    return {"version": STASH_VERSION, "label": label, "state": state}


class _PairHub(_Hub):
    """Two members, so the counts have something to count."""

    hub = (
        Hub()
        .member("contact", CONTACT, title="Contact details")
        .member("address", CONTACT, title="Address")
    )


@pytest.fixture
def pair_hub(rf):
    def build(session=None):
        return _page(_PairHub, rf, session)

    return build


class _GatedHub(_PairHub):
    """Address waits on contact — the shape of every task list that unlocks,
    answered by the hub's own hook."""

    def member_blocked(self, member, store):
        return member.key == "address" and not store.has_stash("contact")


@pytest.fixture
def gated_hub(rf):
    def build(session=None):
        return _page(_GatedHub, rf, session)

    return build


def _member_view(cls, rf, session=None, path="/readme/hub/contact/run-1/", **kwargs):
    request = rf.get(path)
    request.session = _session(session or {})
    view = cls()
    view.setup(request, **kwargs)
    return view


def _retrieved(view, run_id="run-1"):
    context = WizardContext.from_request(view.request)
    from gandalf.runtime import BoundWizard

    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve(run_id)
    return bound_wizard


# --- the declaration --------------------------------------------------------


def test_a_hub_declaration_is_immutable():
    """Every method returns a new `Hub`, so a declaration can be shared and
    extended without side effects."""
    base = Hub().member("contact", CONTACT)

    extended = base.member("address", CONTACT)
    configured = base.configure(template_name="x.html")

    assert [m.key for m in base.members] == ["contact"]
    assert [m.key for m in extended.members] == ["contact", "address"]
    assert base.configuration == {}
    assert configured.configuration == {"template_name": "x.html"}
    assert configured is not base


def test_duplicate_member_keys_are_rejected_at_declaration():
    with pytest.raises(ImproperlyConfigured, match="unique"):
        Hub().member("contact", CONTACT).member("contact", CONTACT)


def test_a_link_must_say_how_far_it_has_got():
    """Without a status the hub would derive one from a stash key nothing
    writes."""
    with pytest.raises(ImproperlyConfigured, match="status"):
        Hub().link("payment", "pay")


def test_a_collection_is_declared_once_not_twice():
    from gandalf.collections import Collection

    collection = Collection(CONTACT)

    with pytest.raises(ImproperlyConfigured, match="not both"):
        Hub().collection("guests", collection, min_items=1)


def test_a_hub_materialises_its_declaration_into_members():
    members = {member.key: member for member in _PairHub.members}

    assert list(members) == ["contact", "address"]
    assert members["contact"].title == "Contact details"
    assert issubclass(members["contact"].viewset, MemberViewSet)
    assert members["contact"].viewset.member_key == "contact"
    assert members["contact"].viewset.hub_url_name == "readme-hub"
    assert members["contact"].viewset.url_name == "readme-hub-contact"
    assert members["contact"].viewset.template_name == "testapp/linear_wizard.html"


def test_a_members_stash_label_defaults_to_its_full_key(hub):
    """What the hub expects a stash to carry: the declared label, else the
    key as the store sees it — prefixed under a nested hub, since that is
    what the member's own viewset stamps by default."""
    page = hub()

    class _Nested(_Hub):
        member_key = "about"

    assert page.stash_label(Member("contact")) == "contact"
    assert page.stash_label(Member("contact", label="contact-v2")) == "contact-v2"
    assert _Nested().stash_label(Member("contact")) == "about:contact"


def test_members_with_the_same_declaration_compare_equal():
    """`url_kwargs` and the rules are excluded from comparison so a member
    stays hashable with a mutable default."""
    first = Member("contact", url_kwargs={"org": "acme"}, blocked=lambda s: True)
    second = Member("contact", url_kwargs={"org": "other"})

    assert first == second
    assert hash(first) == hash(second)


def test_a_declared_wizard_viewset_is_used_as_the_members_base():
    """A member that needs a hook a declaration cannot carry is declared by
    its viewset class rather than its wizard."""

    class _Custom(WizardViewSet):
        wizard = CONTACT
        template_name = "testapp/linear_wizard.html"
        started = []

        def run_started(self, bound_wizard):
            self.started.append(bound_wizard.run_id)

    class _CustomHub(_Hub):
        hub = Hub().member("contact", _Custom)

    viewset = _CustomHub.viewset_for("contact")
    assert issubclass(viewset, _Custom)
    assert issubclass(viewset, MemberViewSet)
    assert viewset.template_name == "testapp/linear_wizard.html"


def test_a_declared_member_viewset_is_used_as_is():
    """A class that is already a `MemberViewSet` — a generated one, re-listed
    — is not wrapped a second time."""
    already = _Hub.viewset_for("contact")

    class _Relisted(_Hub):
        hub = Hub().member("contact", already)

    viewset = _Relisted.viewset_for("contact")
    assert viewset.__bases__ == (already,)
    assert viewset.wizard is CONTACT


def test_viewset_for_rejects_an_unknown_key():
    with pytest.raises(MemberNotFound):
        _Hub.viewset_for("nope")


def test_a_subclass_that_swaps_its_stores_rebuilds_its_members_on_them():
    class _Storage(SessionStorage):
        pass

    class _Store(SessionJourneyStore):
        pass

    class _Durable(_Hub):
        storage_class = _Storage
        journey_store_class = _Store

    viewset = _Durable.viewset_for("contact")
    assert viewset.storage_class is _Storage
    assert viewset.journey_store_class is _Store
    assert viewset is not _Hub.viewset_for("contact")


# --- status derivation -----------------------------------------------------


def test_a_member_with_no_run_and_no_stash_has_not_started(hub):
    (row,) = hub().get_member_rows()

    assert row.status == NOT_STARTED
    assert row.is_not_started


def test_a_member_whose_run_holds_an_answer_is_incomplete(hub):
    page = hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    (row,) = page.get_member_rows()

    assert row.status == INCOMPLETE
    assert row.is_incomplete


def test_a_member_the_user_opened_but_never_answered_has_not_started(hub):
    """A run exists, but there is nothing in it to pick up."""
    page = hub({"runs": {"contact": "run-1"}, "gandalf_runs": {"run-1": {}}})

    (row,) = page.get_member_rows()

    assert row.status == NOT_STARTED


def test_a_member_whose_run_the_storage_has_forgotten_has_not_started(hub):
    """An expired session or an obliterated run leaves nothing to resume, so
    the honest thing to say is that it has not begun."""
    page = hub({"runs": {"contact": "gone"}})

    (row,) = page.get_member_rows()

    assert row.status == NOT_STARTED


def test_a_member_holding_a_stash_is_complete(hub):
    page = hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    (row,) = page.get_member_rows()

    assert row.status == COMPLETE
    assert row.is_complete


def test_a_completed_members_stash_outranks_its_tombstoned_run(hub):
    """The recorded run may be stale — tombstoned, pruned, or replaced by a
    resurrection — and status never consults it once a stash exists."""
    page = hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"completed": True}},
            "stashes": {"contact": _stash([{"step": {"name": "Ada"}}])},
        }
    )

    (row,) = page.get_member_rows()

    assert row.status == COMPLETE


def test_a_tombstoned_run_without_a_stash_has_not_started(hub):
    page = hub(
        {"runs": {"contact": "run-1"}, "gandalf_runs": {"run-1": {"completed": True}}}
    )

    (row,) = page.get_member_rows()

    assert row.status == NOT_STARTED


def test_building_the_rows_never_walks_a_member(hub, monkeypatch):
    """The claim the whole design rests on: a row costs storage reads, not a
    form validation per answered step."""
    from gandalf.runtime import CursorWalker

    def _forbidden(*args, **kwargs):
        raise AssertionError("a hub row must not walk a wizard")

    monkeypatch.setattr(CursorWalker, "walk", _forbidden)
    page = hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    assert page.get_member_rows()[0].status == INCOMPLETE


# --- rows ------------------------------------------------------------------


def test_a_row_carries_its_title_status_label_and_url(hub):
    (row,) = hub().get_member_rows()

    assert isinstance(row, MemberRow)
    assert row.title == "Contact details"
    assert row.status_label == "Not started"
    assert row.url == "/readme/hub/contact/"
    assert row.key == "contact"


def test_a_member_without_a_title_is_named_from_its_key(rf):
    class _UntitledHub(_Hub):
        hub = Hub().member("home_address", CONTACT)

    (row,) = _page(_UntitledHub, rf).get_member_rows()

    assert row.title == "Home address"


def test_the_rows_land_in_the_template_context(hub):
    context = hub().get_context_data()

    assert [row.key for row in context["hub"].rows] == ["contact"]


# --- a member the user cannot start yet ------------------------------------


def test_a_member_waiting_on_another_cannot_start_yet(gated_hub):
    contact, address = gated_hub().get_member_rows()

    assert contact.status == NOT_STARTED
    assert address.status == BLOCKED
    assert address.is_blocked


def test_a_member_unblocks_once_its_prerequisite_is_answered(gated_hub):
    page = gated_hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    contact, address = page.get_member_rows()

    assert (contact.status, address.status) == (COMPLETE, NOT_STARTED)
    assert not address.is_blocked


def test_being_blocked_outranks_a_member_already_finished(gated_hub):
    """The prerequisite was withdrawn after the member was answered. The row
    reports what the user can do, not what they once did — a **Complete** row
    over a link the door refuses is the worse of the two lies."""
    page = gated_hub(
        {"stashes": {"address": _stash([{"step": {"x": 1}}], label="address")}}
    )

    _, address = page.get_member_rows()

    assert address.status == BLOCKED


def test_a_blocked_member_is_labelled_cannot_start_yet(gated_hub):
    _, address = gated_hub().get_member_rows()

    assert str(address.status_label) == "Cannot start yet"


def test_a_blocked_member_is_refused_at_the_door(gated_hub):
    """The row rendered a link the user may not follow, and a stale link or a
    typed URL reaches the door regardless."""
    page = gated_hub()

    assert page.enter(page.get_member("address")) is None
    assert SessionJourneyStore(page.request, "default").get_run("address") is None


def test_a_member_reporting_blocked_under_its_own_steam_is_refused_too(rf):
    """A link's `status` answers for itself, so the door asks the status
    rather than the hook — otherwise the two could disagree."""

    class _Gated(_Hub):
        hub = Hub().link(
            "contact", "readme-hub", status=lambda request, url_kwargs: BLOCKED
        )

    page = _page(_Gated, rf)

    assert page.get_member_rows()[0].status == BLOCKED
    assert page.enter(page.get_member("contact")) is None


def test_an_unblocked_member_still_enters(gated_hub):
    page = gated_hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    assert page.enter(page.get_member("address")) is not None


# --- a member that gates itself --------------------------------------------


class _SelfGatedHub(_Hub):
    """The rule lives on the row it gates, and reads the store alone."""

    hub = Hub().member(
        "address",
        CONTACT,
        title="Address",
        blocked=lambda store: not store.data.get("employed", False),
    )


@pytest.fixture
def self_gated_hub(rf):
    def build(session=None):
        return _page(_SelfGatedHub, rf, session)

    return build


def test_a_member_can_say_it_is_not_open_yet_itself(self_gated_hub):
    (address,) = self_gated_hub().get_member_rows()

    assert address.status == BLOCKED
    assert str(address.status_label) == "Cannot start yet"


def test_a_member_that_opens_says_so_too(self_gated_hub):
    (address,) = self_gated_hub(
        {"data": {"journey": {"employed": True}}}
    ).get_member_rows()

    assert address.status == NOT_STARTED


def test_a_member_gating_itself_is_refused_at_its_hubs_door(self_gated_hub):
    """The hub asks the rule, so display and dispatch cannot disagree."""
    page = self_gated_hub()

    assert page.enter(page.get_member("address")) is None
    assert SessionJourneyStore(page.request, "default").get_run("address") is None


def test_a_rule_is_handed_the_store_and_nothing_else(rf):
    """One read of the journey's record is all a row can afford, and all a
    rule is given."""
    seen = []

    class _Recording(_Hub):
        hub = Hub().member(
            "address", CONTACT, blocked=lambda store: seen.append(store) or False
        )

    _page(_Recording, rf).get_member_rows()

    (store,) = seen
    assert store.journey == "default"


def test_a_hub_override_answers_instead_of_the_member(self_gated_hub):
    """`member_blocked()` is the question, not a vote joined to the
    member's: an override that does not call `super()` replaces it."""
    page = self_gated_hub()
    page.member_blocked = lambda member, store: False

    (address,) = page.get_member_rows()

    assert address.status == NOT_STARTED


def test_a_member_that_is_not_a_wizard_is_never_asked(rf):
    """A link has no rule. It supplies its own `status` instead, which the
    door reads — and which may itself be `BLOCKED`."""

    class _Linked(_Hub):
        hub = Hub().link(
            "payment",
            "readme-hub",
            title="Payment",
            status=lambda request, url_kwargs: NOT_STARTED,
        )

    page = _page(_Linked, rf)

    store = page.get_journey_store()
    assert page.member_blocked(page.get_member("payment"), store) is False


# --- the hub as a whole ----------------------------------------------------


def test_a_hub_counts_how_many_of_its_members_are_complete(pair_hub):
    """The task list heading, without the view counting rows by hand."""
    page = pair_hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    hub = page.get_hub()

    assert hub.count == 2
    assert hub.completed == 1
    assert hub.remaining == 1


def test_a_hub_with_every_member_complete_is_complete(pair_hub):
    page = pair_hub(
        {
            "stashes": {
                "contact": _stash([{"step": {"name": "Ada"}}]),
                "address": _stash([{"step": {"name": "Ada"}}], label="address"),
            }
        }
    )

    hub = page.get_hub()

    assert hub.status == COMPLETE
    assert hub.is_complete
    assert hub.remaining == 0


def test_a_hub_nobody_has_touched_has_not_started(pair_hub):
    hub = pair_hub().get_hub()

    assert hub.status == NOT_STARTED
    assert hub.is_not_started
    assert hub.completed == 0


def test_a_hub_with_one_member_under_way_is_incomplete(pair_hub):
    page = pair_hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    hub = page.get_hub()

    assert hub.status == INCOMPLETE
    assert hub.is_incomplete


def test_a_hub_listing_nothing_has_not_started(rf):
    """`all()` over an empty list is true, and "complete" would be a lie: no
    member has begun because there is no member."""

    class _Empty(_Hub):
        hub = Hub()

    assert _page(_Empty, rf).get_hub().status == NOT_STARTED


def test_a_fresh_hub_whose_later_member_is_locked_has_still_not_started(gated_hub):
    """A locked member is not progress. Counting it as one would open every
    task list on **Incomplete** before the user had answered anything."""
    hub = gated_hub().get_hub()

    assert hub.status == NOT_STARTED
    assert hub.blocked == 1
    assert hub.remaining == 2


def test_a_hub_cannot_be_complete_while_a_member_is_locked(rf):
    """Which is why a member that will never unlock is one for `hidden`
    rather than locked forever inside the list."""

    class _Locked(_PairHub):
        def member_blocked(self, member, store):
            return member.key == "address"

    page = _page(
        _Locked, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    hub = page.get_hub()

    assert hub.status == INCOMPLETE
    assert (hub.completed, hub.blocked, hub.remaining) == (1, 1, 1)


def test_a_hubs_status_carries_its_own_label(pair_hub):
    assert str(pair_hub().get_hub().status_label) == "Not started"


def test_the_hub_lands_in_the_template_context(hub):
    context = hub().get_context_data()

    assert isinstance(context["hub"], HubPage)


def test_a_hub_publishing_no_context_name_publishes_nothing(hub):
    page = hub()
    page.hub_context_name = None

    assert "hub" not in page.get_context_data()


def test_the_rows_are_built_once_per_request(hub):
    """Asking twice is what the counts used to cost. A row is two storage
    reads and a `reverse()`, and a whole `CollectionPage` for a member that
    is one."""
    page = hub()
    builds = []

    def build_member_rows():
        builds.append(1)
        return HubViewSet.build_member_rows(page)

    page.build_member_rows = build_member_rows

    page.get_context_data()
    page.get_member_rows()
    page.get_hub()

    assert len(builds) == 1


def test_the_members_are_chosen_once_per_request(rf):
    """Both halves of the hub ask for the members — the rows and the door —
    and `get_members()` is a per-request choice, so it is asked once."""
    calls = []

    class _Counting(_Hub):
        def get_members(self):
            calls.append(1)
            return super().get_members()

    page = _page(_Counting, rf)

    page.get_member_rows()
    page.get_member("contact")

    assert len(calls) == 1


# --- declaration vetting ---------------------------------------------------


def test_a_hub_without_a_declaration_is_misconfigured(rf):
    class _Bare(HubViewSet):
        template_name = "testapp/hub.html"
        url_name = "readme-hub"

    with pytest.raises(ImproperlyConfigured, match="hub"):
        _page(_Bare, rf).get_member_rows()


def test_get_members_can_choose_among_the_declared_members_per_request(rf):
    class _Choosy(_PairHub):
        def get_members(self):
            return [m for m in super().get_members() if m.key != "address"]

    assert [row.key for row in _page(_Choosy, rf).get_member_rows()] == ["contact"]


def test_get_member_finds_a_member_by_key_and_rejects_an_unknown_one(hub):
    page = hub()

    assert page.get_member("contact").viewset is _Hub.viewset_for("contact")
    with pytest.raises(MemberNotFound):
        page.get_member("nope")


# --- entering a member ----------------------------------------------------


def _entered(page):
    member = page.get_member("contact")
    return page.enter(member)


def test_entering_a_not_started_member_begins_a_run_and_records_it(hub):
    page = hub()

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert run_id is not None
    assert url == f"/readme/hub/contact/{run_id}/first/"


def test_entering_an_incomplete_member_resumes_its_own_run(hub):
    page = hub(
        {
            "runs": {"contact": RUN},
            "gandalf_runs": {RUN: {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    url = _entered(page)

    assert url == f"/readme/hub/contact/{RUN}/second/"
    assert SessionJourneyStore(page.request, "default").get_run("contact") == RUN


def test_entering_a_completed_member_reopens_its_stash_at_the_first_step(hub):
    """Never the bare run URL: every answer in a resurrected run validates,
    so a GET there would fire `done()` before the user edited anything."""
    page = hub(
        {
            "stashes": {
                "contact": _stash(
                    [{"step": {"name": "Ada"}}, {"step": {"email": "ada@example.com"}}]
                )
            }
        }
    )

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert url == f"/readme/hub/contact/{run_id}/first/"
    assert page.request.session["gandalf_runs"][run_id]["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_reopening_a_member_leaves_its_stash_in_place(hub):
    """Read, never popped: re-opening keeps working, and re-completing
    overwrites the stash with the newer answers."""
    page = hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    _entered(page)

    assert SessionJourneyStore(page.request, "default").has_stash("contact")


def test_a_completed_member_already_being_edited_resumes_that_edit(hub):
    """Resume before reopen, so at most one live run per member exists —
    otherwise every click would resurrect a run beside the in-flight edit
    and the user's changes would become unreachable."""
    page = hub(
        {
            "runs": {"contact": RUN},
            "gandalf_runs": {RUN: {"state": [{"step": {"name": "Grace"}}]}},
            "stashes": {"contact": _stash([{"step": {"name": "Ada"}}])},
        }
    )

    url = _entered(page)

    assert url == f"/readme/hub/contact/{RUN}/second/"


def test_a_member_whose_recorded_run_was_tombstoned_starts_again(hub):
    """A completed run is *found*, not missing, so resuming has to ask
    `is_complete` as well — a run every request bounces off is worse than
    no run at all."""
    page = hub(
        {"runs": {"contact": "run-1"}, "gandalf_runs": {"run-1": {"completed": True}}}
    )

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert run_id != "run-1"
    assert url == f"/readme/hub/contact/{run_id}/first/"


def test_a_member_whose_recorded_run_is_gone_starts_again(hub):
    page = hub({"runs": {"contact": "gone"}})

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert run_id != "gone"
    assert url == f"/readme/hub/contact/{run_id}/first/"


def test_a_member_can_name_the_step_a_reopened_stash_lands_on(rf):
    class _LandingHub(_Hub):
        hub = Hub().member("contact", CONTACT, reopen="second")

    page = _page(
        _LandingHub, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    url = page.enter(page.get_member("contact"))

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert url == f"/readme/hub/contact/{run_id}/second/"


def test_a_stash_whose_label_no_longer_matches_is_refused_loudly(rf):
    """A deploy reshaped the member and bumped its label. Starting over
    silently would look to the user exactly like their answers vanishing."""
    from gandalf.runtime import InvalidStash

    class _Reshaped(_Hub):
        hub = Hub().member("contact", CONTACT, label="contact-v2")

    page = _page(
        _Reshaped, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    with pytest.raises(InvalidStash):
        page.enter(page.get_member("contact"))


def test_stash_unusable_can_be_overridden_to_start_over(rf):
    class _Forgiving(_Hub):
        hub = Hub().member("contact", CONTACT, label="contact-v2")

        def stash_unusable(self, member, error):
            store = self.get_journey_store()
            store.delete_stash(member.key)
            return self.enter(member)

    page = _page(
        _Forgiving, rf, {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    url = page.enter(page.get_member("contact"))

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert url == f"/readme/hub/contact/{run_id}/first/"


# --- MemberViewSet -----------------------------------------------------------


def _contact_view(rf, session=None, cls=None):
    return _member_view(cls or _Hub.viewset_for("contact"), rf, session)


def test_finishing_a_member_stashes_its_answers_and_clears_its_run(rf):
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


def test_a_finished_member_sends_the_user_back_to_its_hub(rf):
    """The default `run_done` — a task list expects a finished task to
    deposit the user back on the list."""
    view = _contact_view(
        rf, {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )

    response = view.done(_retrieved(view))

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


def test_the_declared_done_runs_between_the_stash_and_the_redirect(rf):
    """`done=` is handed the store and the finished run — the store already
    holding the stash, the run still readable."""
    events = []

    def record(store, bound_wizard):
        events.append((store.get_stash("contact")["state"], bound_wizard.get_state()))

    class _Deciding(_Hub):
        hub = Hub().member("contact", CONTACT, done=record)

    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=_Deciding.viewset_for("contact"),
    )

    response = view.done(_retrieved(view))

    assert events == [([{"step": {"name": "Ada"}}], [{"step": {"name": "Ada"}}])]
    assert response["Location"] == "/readme/hub/"


def test_a_member_done_that_raises_leaves_the_member_resumable(rf):
    """Mirrors `_finish`'s own ordering — the run id is cleared only after
    the application's work has succeeded."""

    def fail(store, bound_wizard):
        raise RuntimeError("nope")

    class _Failing(_Hub):
        hub = Hub().member("contact", CONTACT, done=fail)

    view = _contact_view(
        rf,
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        },
        cls=_Failing.viewset_for("contact"),
    )

    with pytest.raises(RuntimeError):
        view.done(_retrieved(view))

    store = SessionJourneyStore(WizardContext.from_request(view.request), "default")
    assert store.get_run("contact") == "run-1"


def test_bookkeeping_recorded_at_completion_runs_between_the_stash_and_member_done(
    rf,
):
    """`run_recorded()` sits above `run_done()` and below the stash, so
    it can read what was just recorded and cannot be pre-empted by an
    application hook that obliterates, escapes or raises."""
    events = []

    class _Recording(_Hub.viewset_for("contact")):
        def run_recorded(self, bound_wizard, store, key):
            events.append(("recorded", key, store.get_stash(key)["state"]))

        def run_done(self, bound_wizard):
            events.append(("done", self.get_member_key(), None))
            return super().run_done(bound_wizard)

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

    class _Recording(_Hub.viewset_for("contact")):
        def run_recorded(self, bound_wizard, store, key):
            seen.append(bound_wizard.get_state())

    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=_Recording,
    )
    bound_wizard = _Recording.inspect(view.request, "run-1")

    view.finish(bound_wizard)

    assert seen == [[{"step": {"name": "Ada"}}]]
    assert bound_wizard.is_complete
    assert SessionStorage(bound_wizard.context).get_state("run-1") == []


def test_a_members_stash_label_can_be_bumped_independently_of_its_key(rf):
    class _Reshaped(_Hub):
        hub = Hub().member("contact", CONTACT, label="contact-v2")

    view = _contact_view(
        rf,
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}},
        cls=_Reshaped.viewset_for("contact"),
    )

    view.done(_retrieved(view))

    store = SessionJourneyStore(WizardContext.from_request(view.request), "default")
    assert store.get_stash("contact")["label"] == "contact-v2"


def test_a_member_without_a_key_is_misconfigured(rf):
    class _Keyless(_Hub.viewset_for("contact")):
        member_key = None

    view = _contact_view(rf, {"gandalf_runs": {"run-1": {"state": []}}}, cls=_Keyless)

    with pytest.raises(ImproperlyConfigured, match="member_key"):
        view.done(_retrieved(view))


def test_a_member_without_a_hub_url_name_is_misconfigured(rf):
    class _Homeless(_Hub.viewset_for("contact")):
        hub_url_name = None

    view = _contact_view(rf, cls=_Homeless)

    with pytest.raises(ImproperlyConfigured, match="hub_url_name"):
        view.get_hub_url()


def test_a_member_under_a_submitted_journey_sends_the_user_up(rf):
    view = _contact_view(rf, {"completed": True})

    response = view.journey_completed(view.get_journey_store())

    assert response["Location"] == "/readme/hub/"


# --- URLs ------------------------------------------------------------------


def test_a_row_links_to_the_hubs_own_door_not_the_wizards_urls(hub):
    url = hub().get_member_url(Member("contact"))

    assert url == "/readme/hub/contact/"


def test_a_hub_forwards_its_mount_prefix_and_drops_the_member_kwarg(rf):
    page = _page(_Hub, rf, path="/org/acme/hub/details/", org="acme", member="details")

    assert page.get_page_url_kwargs() == {"org": "acme"}
    assert page.member_url_kwargs(Member("details", url_kwargs={"item": "x"})) == {
        "org": "acme",
        "item": "x",
    }


def test_the_hub_url_is_reversed_from_its_own_url_name(hub):
    assert hub().get_page_url() == "/readme/hub/"


def test_an_unknown_member_is_sent_back_to_the_hub(rf):
    page = _page(_Hub, rf, path="/readme/hub/nope/")

    response = page.member_unavailable("nope")

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


def test_a_row_can_point_at_something_that_is_not_a_wizard(rf):
    """A payment redirect, a page in another app. The door exists to walk a
    run and pick a step; something with no run to walk has nothing for it to
    do, so the row addresses it directly."""

    class _Linked(_Hub):
        hub = Hub().link(
            "guests", "readme-hub", status=lambda request, url_kwargs: COMPLETE
        )

    (row,) = _page(_Linked, rf).get_member_rows()

    assert row.status == COMPLETE
    assert row.status_label == "Complete"
    assert row.url == "/readme/hub/"


def test_the_door_refuses_a_member_it_cannot_walk(rf):
    """Rows never point there, so arriving is a hand-typed or stale URL."""

    class _Linked(_Hub):
        hub = Hub().link(
            "guests", "readme-hub", status=lambda request, url_kwargs: COMPLETE
        )

    page = _page(_Linked, rf, path="/readme/hub/guests/")

    assert page.enter(page.get_member("guests")) is None


def test_a_hub_without_a_member_url_name_is_misconfigured(hub):
    page = hub()
    page.member_url_name = None

    with pytest.raises(ImproperlyConfigured, match="member_url_name"):
        page.get_member_url(Member("contact"))


def test_a_hub_without_a_url_name_is_misconfigured(hub):
    page = hub()
    page.url_name = None

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        page.get_page_url()
    with pytest.raises(ImproperlyConfigured, match="url_name"):

        class _NamelessView(HubViewSet):
            hub = Hub()

        _NamelessView.urls()


def test_a_hub_publishes_its_page_its_members_and_then_its_door():
    """The door comes last so a member's own segment — a nested hub's page,
    a collection's — is reached directly."""
    page, contact, address, door = _PairHub.urls()

    assert page.name == "readme-hub"
    assert str(contact.pattern) == "contact/"
    assert str(address.pattern) == "address/"
    assert door.name == "readme-hub-member"
    assert str(door.pattern) == "<slug:member>/"


def test_a_wizard_members_bare_url_is_the_hubs_door():
    """A run whose every answer validates completes on a GET, so the one URL
    a `WizardViewSet` publishes first is replaced by the door for it, under
    the wizard's own URL name."""
    _page_pattern, contact, *_ = _PairHub.urls()
    start, run, step = contact.url_patterns

    assert start.name == "readme-hub-contact"
    assert str(start.pattern) == ""
    assert start.default_args == {"member": "contact"}
    assert start.callback.view_class is _PairHub
    assert (run.name, step.name) == (
        "readme-hub-contact-run",
        "readme-hub-contact-step",
    )
    assert step.callback.view_class is _PairHub.viewset_for("contact")


def test_a_link_publishes_no_routes():
    class _Linked(_Hub):
        hub = Hub().link("pay", "readme-hub", status=lambda r, k: COMPLETE)

    page, door = _Linked.urls()

    assert (page.name, door.name) == ("readme-hub", "readme-hub-member")


def _profile_hub(rf, path, **kwargs):
    """The README's hub, dispatched directly — one view over two routes."""
    from tests.testapp.readme.ch11_hub import GrantHubViewSet

    request = rf.get(path)
    request.session = _session()
    return GrantHubViewSet.as_view()(request, **kwargs)


def test_the_hub_page_renders_the_member_rows(rf):
    response = _profile_hub(rf, "/readme/hub/")

    assert response.status_code == 200
    assert [row.key for row in response.context_data["hub"].rows] == [
        "contact",
        "address",
    ]


def test_the_door_redirects_into_the_member_it_names(rf):
    response = _profile_hub(rf, "/readme/hub/contact/", member="contact")

    assert response.status_code == 302
    assert response["Location"].startswith("/readme/hub/contact/")
    assert response["Location"].endswith("/name/")


def test_the_door_sends_a_member_it_cannot_walk_back_to_the_hub(rf):
    """A link row links past the door anyway — so arriving here is a
    hand-typed or stale URL."""

    class _Linked(_Hub):
        hub = Hub().link("elsewhere", "readme-hub", status=lambda r, k: COMPLETE)

    request = rf.get("/readme/hub/elsewhere/")
    request.session = _session()

    response = _Linked.as_view()(request, member="elsewhere")

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


def test_the_door_sends_an_unknown_member_back_to_the_hub(rf):
    response = _profile_hub(rf, "/readme/hub/nope/", member="nope")

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


# --- a member that is hidden -----------------------------------------------


class _PartnerHub(_Hub):
    """A member that only exists once an answer elsewhere says so."""

    hub = (
        Hub()
        .member("contact", CONTACT, title="Contact details")
        .member(
            "address",
            CONTACT,
            title="Partner",
            hidden=lambda store: not store.data.get("has_partner", False),
        )
    )


@pytest.fixture
def partner_hub(rf):
    def build(session=None):
        return _page(_PartnerHub, rf, session)

    return build


def test_a_hidden_member_is_not_listed(partner_hub):
    rows = partner_hub().get_member_rows()

    assert [row.key for row in rows] == ["contact"]


def test_a_hidden_member_is_not_counted(partner_hub):
    """Hidden is gone, not locked: a fresh hub with one hidden row is a hub
    of one member, and finishing that one completes it."""
    page = partner_hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    hub = page.get_hub()

    assert (hub.count, hub.completed, hub.blocked) == (1, 1, 0)
    assert hub.status == COMPLETE


def test_a_member_appears_once_the_answer_that_reveals_it_is_given(partner_hub):
    page = partner_hub({"data": {"journey": {"has_partner": True}}})

    rows = page.get_member_rows()

    assert [row.key for row in rows] == ["contact", "address"]
    assert rows[1].status == NOT_STARTED


def test_a_hidden_member_is_unknown_at_the_door(partner_hub):
    """A stale link to a member that no longer applies is refused the way a
    key the hub never declared is, so no run is minted for it."""
    page = partner_hub()

    with pytest.raises(MemberNotFound):
        page.get_member("address")
    assert SessionJourneyStore(page.request, "default").get_run("address") is None


def test_hidden_outranks_blocked(rf):
    """A member that does not exist cannot also be waiting."""

    class _BothHub(_Hub):
        hub = Hub().member(
            "address",
            CONTACT,
            blocked=lambda store: True,
            hidden=lambda store: True,
        )

    hub = _page(_BothHub, rf).get_hub()

    assert hub.count == 0
    assert hub.blocked == 0


def test_a_hub_override_can_hide_on_the_members_behalf(partner_hub):
    """`member_hidden()` mirrors `member_blocked()`: the hub's hook for
    what one member cannot answer alone, replacing the question."""
    page = partner_hub()
    page.member_hidden = lambda member, store: member.key == "contact"

    # Contact is hidden by the hub; Partner, which its own rule would have
    # hidden, is listed — the override replaced the question.
    assert [row.key for row in page.get_member_rows()] == ["address"]


def test_a_member_that_is_not_a_wizard_is_never_asked_whether_it_is_hidden(rf):
    class _Linked(_Hub):
        hub = Hub().link(
            "payment",
            "readme-hub",
            title="Payment",
            status=lambda request, url_kwargs: NOT_STARTED,
        )

    page = _page(_Linked, rf)

    store = page.get_journey_store()
    assert page.member_hidden(page.get_member("payment"), store) is False


# --- the journey ------------------------------------------------------------


def test_a_hub_reads_its_journey_off_the_url_when_mounted_under_one(rf):
    page = _page(_Hub, rf, path="/apply/app-1/", journey="app-1")

    assert page.get_journey() == "app-1"
    assert page.get_page_url_kwargs() == {"journey": "app-1"}


def test_a_hub_mounted_under_no_journey_uses_the_one_it_declares(hub):
    page = hub()

    assert page.get_journey() == "default"
    assert page.get_page_url_kwargs() == {}


def test_a_hub_keeps_its_bookkeeping_under_its_journey(rf):
    """Two journeys in one session are two task lists."""
    request = rf.get("/apply/app-2/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}, journey="app-1"
    )
    page = _JourneyHub()
    page.setup(request, journey="app-2")

    (row,) = page.get_member_rows()

    assert row.status == NOT_STARTED


def test_the_door_hands_every_member_view_the_journey(rf):
    """A member is mounted beneath its hub, so every kwarg the page came in
    with — the journey, a mount prefix — reaches the run it starts."""
    seen = []

    class _Recording(_Hub.viewset_for("contact")):
        @classmethod
        def begin(cls, request, **url_kwargs):
            seen.append(url_kwargs)
            return super().begin(request)

    page = _page(_Hub, rf, path="/apply/app-1/hub/", journey="app-1", org="acme")
    page.members = [replace(page.get_member("contact"), viewset=_Recording)]
    del page._members_cache

    page.enter(page.get_member("contact"))

    assert seen == [{"journey": "app-1", "org": "acme"}]
    assert SessionJourneyStore(page.request, "app-1").get_run("contact") is not None


def test_a_status_callable_is_handed_the_journey_too(rf):
    seen = []

    class _Linked(_JourneyHub):
        hub = Hub().link(
            "guests",
            "readme-apply",
            title="Guests",
            status=lambda request, url_kwargs: seen.append(url_kwargs) or COMPLETE,
        )

    page = _page(_Linked, rf, path="/apply/app-1/hub/", journey="app-1")

    page.get_member_rows()

    assert seen == [{"journey": "app-1"}]


def test_a_hubs_members_share_its_journey_by_construction():
    class _Profiled(_Hub):
        journey = "profile"
        journey_url_kwarg = "application"

    viewset = _Profiled.viewset_for("contact")

    assert (viewset.journey, viewset.journey_url_kwarg) == ("profile", "application")


def test_a_member_reads_its_journey_off_the_url_when_mounted_under_one(rf):
    view = _Hub.viewset_for("contact")()
    view.setup(rf.get("/apply/app-1/contact/"), journey="app-1")

    assert view.get_journey() == "app-1"
    assert view.get_journey_store().journey == "app-1"


def test_finishing_a_member_writes_what_it_decided_where_the_hub_reads_it(rf):
    """The whole point of `store.data`: one walk at completion, and every
    later render reads a string."""

    def record_name(store, bound_wizard):
        step = bound_wizard.path.find_step(name="first")
        store.data["name"] = step.form.cleaned_data["name"]

    class _Deciding(_Hub):
        hub = Hub().member("contact", CONTACT, done=record_name)

    viewset = _Deciding.viewset_for("contact")
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
    journey = _JourneyHub.begin(_page(_Hub, rf).request)

    assert journey.url == f"/readme/apply/{journey.id}/"
    assert journey.store.keys() == []


def test_beginning_can_be_given_the_journey(rf):
    assert _JourneyHub.begin(_page(_Hub, rf).request, journey="app-9").url == (
        "/readme/apply/app-9/"
    )


def test_beginning_a_journey_for_a_hub_not_under_one_lands_on_its_one_page(rf):
    """One journey per session: there is no segment to put the id in."""
    assert _Hub.begin(_page(_Hub, rf).request).url == "/readme/hub/"


def test_finishing_a_section_records_the_run_as_the_page_would(rf):
    """Stashed under the section's key, its run cleared — exactly what
    finishing it from the hub's own door does, under the new journey."""
    view = _contact_view(
        rf, {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    journey = _JourneyHub.begin(view.request)

    journey.finish("contact", _retrieved(view))

    assert journey.store.get_stash("contact")["state"] == [{"step": {"name": "Ada"}}]
    assert journey.store.get_run("contact") is None


def test_finishing_an_unknown_section_is_refused(rf):
    with pytest.raises(MemberNotFound):
        _JourneyHub.begin(_page(_Hub, rf).request).finish("nope", None)


# --- submitting the journey ---------------------------------------------------


class _SubmittableHub(_PairHub):
    def journey_done(self, hub, store):
        store.data["reference"] = f"REF-{hub.completed}"
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
    page = _page(_SubmittableHub, rf, _complete_pair(), method="post")

    response = page.submit()

    store = SessionJourneyStore(page.request, "default")
    assert response.content == b"submitted"
    assert store.is_complete() is True
    assert store.keys() == []
    assert store.data["reference"] == "REF-2"


def test_submitting_an_incomplete_journey_is_refused(rf):
    """A stale button or a hand-made POST cannot submit half a journey."""
    page = _page(
        _SubmittableHub,
        rf,
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}},
        method="post",
    )

    response = page.submit()

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"
    assert SessionJourneyStore(page.request, "default").is_complete() is False


def test_a_journey_done_that_raises_leaves_the_journey_resumable(rf):
    """`done()`'s ordering, one level up: the work first, the tombstone only
    once it has succeeded."""

    class _Failing(_SubmittableHub):
        def journey_done(self, hub, store):
            raise RuntimeError("nope")

    page = _page(_Failing, rf, _complete_pair(), method="post")

    with pytest.raises(RuntimeError):
        page.submit()

    store = SessionJourneyStore(page.request, "default")
    assert store.is_complete() is False
    assert store.keys() == ["contact", "address"]


def test_a_hub_with_nothing_to_do_at_submit_is_misconfigured(rf):
    page = _page(_PairHub, rf, _complete_pair(), method="post")

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        page.submit()


def test_a_hub_says_a_submitted_journey_is_gone_by_default(rf):
    from django.http import Http404

    page = _page(_Hub, rf, {"completed": True})

    with pytest.raises(Http404):
        page.journey_completed(page.get_journey_store())


def _apply(rf, method, path, session=None, **kwargs):
    """The README's journey hub, dispatched directly under a journey."""
    from tests.testapp.readme.ch14_journey import GrantApplicationViewSet

    request = getattr(rf, method)(path)
    request.session = _session(session, journey="app-1")
    return GrantApplicationViewSet.as_view()(request, journey="app-1", **kwargs)


@pytest.mark.django_db
def test_a_post_to_the_hub_page_submits_the_journey(rf):
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
            "collections": {
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
    """The route that opens a member never finishes anything."""
    response = _apply(rf, "post", "/readme/apply/app-1/contact/", member="contact")

    assert response.status_code == 405


def test_a_submitted_journeys_hub_renders_what_the_tombstone_kept(rf):
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
        member="contact",
    )

    assert b"Application submitted" in response.content


def test_a_submitted_journeys_member_wizard_refuses_a_bookmarked_url(rf):
    """A stale run URL must not re-open a member into a tombstone."""
    from tests.testapp.readme.ch14_journey import GrantApplicationViewSet

    request = rf.get("/readme/apply/app-1/contact/run-1/")
    request.session = _session({"completed": True}, journey="app-1")

    response = GrantApplicationViewSet.viewset_for("contact").as_view()(
        request, journey="app-1", run_id="run-1"
    )

    assert response.status_code == 302
    assert response["Location"] == "/readme/apply/app-1/"
