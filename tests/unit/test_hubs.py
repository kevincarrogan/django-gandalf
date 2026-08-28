"""Unit coverage for the hub and spoke layer.

A hub lists parallel wizards the user drops in and out of. The display half
answers "how far has each got" without walking anything; the dispatch half
turns one click into a step URL, walking only the member the user chose.
"""

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
    HubMixin,
    Member,
    RunMemberMixin,
    MemberNotFound,
    MemberRow,
)
from gandalf.storage import SessionJourneyStore
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


class _MemberViewSet(RunMemberMixin, WizardViewSet):
    member_key = "contact"
    hub_url_name = "hub"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(FirstStepForm, name="first").step(SecondStepForm, name="second")
    )

    def get_wizard_url(self, run_id):
        return f"/contact/{run_id}/"

    def get_step_url(self, run_id, step_segment):
        return f"/contact/{run_id}/{step_segment}/"

    def get_start_url(self):
        return "/contact/"

    def run_done(self, bound_wizard):
        # The default redirects to `hub_url_name`; reversing a real hub URL
        # is the functional suite's job.
        from django.http import HttpResponse

        return HttpResponse(b"member done")


class _TemplateView:
    """Stands in for the Django view a hub is mixed into."""

    def get_context_data(self, **kwargs):
        return dict(kwargs)


class _Hub(HubMixin, _TemplateView):
    members = [Member("contact", _MemberViewSet, title="Contact details")]

    def __init__(self, request):
        self.request = request
        self.kwargs = {}

    def get_member_url(self, member):
        return f"/hub/{member.key}/"


def _hub(session=None, rf=None):
    request = rf.get("/hub/")
    request.session = _session(session or {})
    return _Hub(request)


@pytest.fixture
def hub(rf):
    def build(session=None):
        return _hub(session, rf=rf)

    return build


def _stash(state, label="contact"):
    return {"version": STASH_VERSION, "label": label, "state": state}


class _AddressMemberViewSet(_MemberViewSet):
    member_key = "address"


class _PairHub(_Hub):
    """Two members, so the counts have something to count."""

    members = [
        Member("contact", _MemberViewSet, title="Contact details"),
        Member("address", _AddressMemberViewSet, title="Address"),
    ]


@pytest.fixture
def pair_hub(rf):
    def build(session=None):
        request = rf.get("/hub/")
        request.session = _session(session or {})
        return _PairHub(request)

    return build


class _GatedHub(_PairHub):
    """Address waits on contact — the shape of every task list that unlocks."""

    def member_blocked(self, member, store):
        return member.key == "address" and not store.has_stash("contact")


@pytest.fixture
def gated_hub(rf):
    def build(session=None):
        request = rf.get("/hub/")
        request.session = _session(session or {})
        return _GatedHub(request)

    return build


# --- Member ---------------------------------------------------------------


def test_a_members_stash_label_defaults_to_its_full_key(rf):
    """What the hub expects a stash to carry: the declared label, else the
    key as the store sees it — prefixed under a nested hub, since that is
    what the member's own viewset stamps by default."""
    request = rf.get("/readme/hub/")
    request.session = _session()
    hub = _ReversingHub(request)

    class _Nested(_ReversingHub):
        member_key = "about"

    assert hub.stash_label(Member("contact", _MemberViewSet)) == "contact"
    assert hub.stash_label(Member("contact", _MemberViewSet, label="contact-v2")) == (
        "contact-v2"
    )
    assert _Nested(request).stash_label(Member("contact", _MemberViewSet)) == (
        "about:contact"
    )


def test_members_with_the_same_declaration_compare_equal():
    """`url_kwargs` is excluded from comparison so a member stays hashable
    with a mutable default."""
    first = Member("contact", _MemberViewSet, url_kwargs={"org": "acme"})
    second = Member("contact", _MemberViewSet, url_kwargs={"org": "other"})

    assert first == second
    assert hash(first) == hash(second)


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
    page = hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {}},
        }
    )

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
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"completed": True}},
        }
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
    assert row.url == "/hub/contact/"
    assert row.key == "contact"


def test_a_member_without_a_title_is_named_from_its_key(rf):
    class _AddressViewSet(_MemberViewSet):
        member_key = "home_address"

    class _UntitledHub(_Hub):
        members = [Member("home_address", _AddressViewSet)]

    request = rf.get("/hub/")
    request.session = _session()

    (row,) = _UntitledHub(request).get_member_rows()

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
    """`Member.status` answers for itself, so the door asks the status rather
    than the hook — otherwise the two could disagree."""

    class _Gated(_Hub):
        members = [
            Member(
                "contact",
                _MemberViewSet,
                title="Contact details",
                status=lambda request, url_kwargs: BLOCKED,
            )
        ]

    request = rf.get("/hub/")
    request.session = _session()
    page = _Gated(request)

    assert page.get_member_rows()[0].status == BLOCKED
    assert page.enter(page.get_member("contact")) is None


def test_an_unblocked_member_still_enters(gated_hub):
    page = gated_hub({"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}})

    assert page.enter(page.get_member("address")) is not None


# --- a member that gates itself --------------------------------------------


class _EmploymentViewSet(_AddressMemberViewSet):
    """A member that answers for its own availability. The rule lives with
    the wizard it gates, so there is no key in scope to branch on."""

    @classmethod
    def blocked(cls, request, member, store):
        return not store.data.get("employed", False)


class _SelfGatedHub(_Hub):
    members = [Member("address", _EmploymentViewSet, title="Address")]


@pytest.fixture
def self_gated_hub(rf):
    def build(session=None):
        request = rf.get("/hub/")
        request.session = _session(session or {})
        return _SelfGatedHub(request)

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
    """The hub asks the member, so display and dispatch cannot disagree even
    though the hub declares nothing about the rule."""
    page = self_gated_hub()

    assert page.enter(page.get_member("address")) is None
    assert SessionJourneyStore(page.request, "default").get_run("address") is None


def test_the_member_is_handed_the_row_it_is_asked_about(self_gated_hub):
    """One viewset mounted per item of a collection needs to tell its items
    apart; a plain member ignores it."""
    seen = []

    class _Recording(_EmploymentViewSet):
        @classmethod
        def blocked(cls, request, member, store):
            seen.append(member)
            return False

    page = self_gated_hub()
    page.members = [Member("address", _Recording, title="Address")]

    page.get_member_rows()

    assert [member.key for member in seen] == ["address"]


def test_a_hub_override_answers_instead_of_the_member(self_gated_hub):
    """`member_blocked()` is the question, not a vote joined to the
    member's: an override that does not call `super()` replaces it."""
    page = self_gated_hub()
    page.member_blocked = lambda member, store: False

    (address,) = page.get_member_rows()

    assert address.status == NOT_STARTED


def test_a_member_that_is_not_a_wizard_is_never_asked(rf):
    """It has no viewset to ask. It supplies its own `status` instead, which
    the door reads — and which may itself be `BLOCKED`."""

    class _Linked(_Hub):
        members = [
            Member(
                "payment",
                title="Payment",
                url_name="pay",
                status=lambda request, url_kwargs: NOT_STARTED,
            )
        ]

    request = rf.get("/hub/")
    request.session = _session()
    page = _Linked(request)

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
        members = []

    request = rf.get("/hub/")
    request.session = _session()

    assert _Empty(request).get_hub().status == NOT_STARTED


def test_a_fresh_hub_whose_later_member_is_locked_has_still_not_started(gated_hub):
    """A locked member is not progress. Counting it as one would open every
    task list on **Incomplete** before the user had answered anything."""
    hub = gated_hub().get_hub()

    assert hub.status == NOT_STARTED
    assert hub.blocked == 1
    assert hub.remaining == 2


def test_a_hub_cannot_be_complete_while_a_member_is_locked(rf):
    """Which is why a member that will never unlock is one for `hidden()`
    rather than locked forever inside the list."""

    class _Locked(_PairHub):
        def member_blocked(self, member, store):
            return member.key == "address"

    request = rf.get("/hub/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )

    hub = _Locked(request).get_hub()

    assert hub.status == INCOMPLETE
    assert (hub.completed, hub.blocked, hub.remaining) == (1, 1, 1)


def test_a_hubs_status_carries_its_own_label(pair_hub):
    assert str(pair_hub().get_hub().status_label) == "Not started"


def test_the_hub_lands_in_the_template_context(hub):
    context = hub().get_context_data()

    assert isinstance(context["hub"], Hub)


def test_a_hub_publishing_no_context_name_publishes_nothing(hub):
    page = hub()
    page.hub_context_name = None

    assert page.get_context_data() == {}


def test_the_rows_are_built_once_per_request(hub):
    """Asking twice is what the counts used to cost. A row is two storage
    reads and a `reverse()`, and a whole `Collection` for a member that is
    one."""
    page = hub()
    builds = []

    def build_member_rows():
        builds.append(1)
        return HubMixin.build_member_rows(page)

    page.build_member_rows = build_member_rows

    page.get_context_data()
    page.get_member_rows()
    page.get_hub()

    assert len(builds) == 1


# --- declaration vetting ---------------------------------------------------


def test_a_hub_without_members_is_misconfigured(rf):
    class _Bare(_Hub):
        members = None

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="members"):
        _Bare(request).get_member_rows()


def test_duplicate_member_keys_are_rejected(rf):
    class _Duplicated(_Hub):
        members = [
            Member("contact", _MemberViewSet),
            Member("contact", _MemberViewSet),
        ]

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="unique"):
        _Duplicated(request).get_member_rows()


def test_a_key_that_drifts_from_the_members_own_member_key_is_rejected(rf):
    """The hub would read a stash key the member never writes, so the
    member could complete and still read as not started."""

    class _Drifted(_Hub):
        members = [Member("billing", _MemberViewSet)]

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="member_key"):
        _Drifted(request).get_member_rows()


def test_a_member_viewset_that_does_its_own_bookkeeping_is_not_key_checked(rf):
    """Only a `RunMemberMixin` declares a `member_key` to drift from."""

    class _Plain(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/linear_wizard.html"

    class _Mixed(_Hub):
        members = [Member("anything", _Plain)]

    request = rf.get("/hub/")
    request.session = _session()

    assert _Mixed(request).get_member_rows()[0].status == NOT_STARTED


def test_a_member_that_returns_to_another_hub_is_rejected(rf):
    """Finishing would work and simply deposit the user on a page that does
    not list the member they just finished."""

    class _Elsewhere(_MemberViewSet):
        hub_url_name = "some-other-hub"

    class _Named(_Hub):
        url_name = "hub"
        members = [Member("contact", _Elsewhere)]

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="Mispointed"):
        _Named(request).get_member_rows()


def test_a_member_that_returns_to_the_hub_listing_it_is_accepted(rf):
    class _Named(_Hub):
        url_name = "hub"

    request = rf.get("/hub/")
    request.session = _session()

    assert _Named(request).get_member_rows()[0].status == NOT_STARTED


def test_a_hub_that_names_no_url_of_its_own_checks_no_return(rf):
    """`url_name` is optional — such a hub is mounted under a name only its
    URLconf knows, so there is nothing to compare a member against."""

    class _Elsewhere(_MemberViewSet):
        hub_url_name = "some-other-hub"

    class _Anonymous(_Hub):
        members = [Member("contact", _Elsewhere)]

    request = rf.get("/hub/")
    request.session = _session()

    assert _Anonymous(request).get_member_rows()[0].status == NOT_STARTED


def test_a_member_viewset_that_does_its_own_bookkeeping_is_not_return_checked(rf):
    """Only a `RunMemberMixin` declares a `hub_url_name` to drift from."""

    class _Plain(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/linear_wizard.html"

    class _Named(_Hub):
        url_name = "hub"
        members = [Member("anything", _Plain)]

    request = rf.get("/hub/")
    request.session = _session()

    assert _Named(request).get_member_rows()[0].status == NOT_STARTED


def test_a_member_that_keys_itself_per_request_stashes_under_that_key(rf):
    """A dynamic member's key is only knowable once a request has named the
    item it belongs to, so it comes from the URL rather than the class."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _PerItem(_MemberViewSet):
        member_key = None
        dynamic_member_key = True

        def get_member_key(self):
            return f"guests:{self.kwargs['item']}"

    request = rf.get("/guest/7/run-1/")
    request.session = _session(
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    view = _PerItem()
    view.setup(request, item="7")
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    view.done(bound_wizard)

    assert SessionJourneyStore(context, "default").keys() == ["guests:7"]


def test_a_dynamic_member_that_derives_no_key_is_misconfigured(rf):
    """The inherited message tells you to set a class attribute; a member
    that deliberately has none needs to be told something else."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Undecided(_MemberViewSet):
        member_key = None
        dynamic_member_key = True

    request = rf.get("/contact/run-1/")
    request.session = _session({"gandalf_runs": {"run-1": {"state": []}}})
    view = _Undecided()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    with pytest.raises(ImproperlyConfigured, match="get_member_key"):
        view.done(bound_wizard)


def test_get_member_finds_a_member_by_key_and_rejects_an_unknown_one(hub):
    page = hub()

    assert page.get_member("contact").viewset is _MemberViewSet
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
    assert url == f"/contact/{run_id}/first/"


def test_entering_an_incomplete_member_resumes_its_own_run(hub):
    page = hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )

    url = _entered(page)

    assert url == "/contact/run-1/second/"
    assert SessionJourneyStore(page.request, "default").get_run("contact") == "run-1"


def test_entering_a_completed_member_reopens_its_stash_at_the_first_step(hub):
    """Never the bare run URL: every answer in a resurrected run validates,
    so a GET there would fire `done()` before the user edited anything."""
    page = hub(
        {
            "stashes": {
                "contact": _stash(
                    [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ]
                )
            }
        }
    )

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert url == f"/contact/{run_id}/first/"
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
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Grace"}}]}},
            "stashes": {"contact": _stash([{"step": {"name": "Ada"}}])},
        }
    )

    url = _entered(page)

    assert url == "/contact/run-1/second/"


def test_a_member_whose_recorded_run_was_tombstoned_starts_again(hub):
    """A completed run is *found*, not missing, so resuming has to ask
    `is_complete` as well — a run every request bounces off is worse than
    no run at all."""
    page = hub(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"completed": True}},
        }
    )

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert run_id != "run-1"
    assert url == f"/contact/{run_id}/first/"


def test_a_member_whose_recorded_run_is_gone_starts_again(hub):
    page = hub({"runs": {"contact": "gone"}})

    url = _entered(page)

    run_id = SessionJourneyStore(page.request, "default").get_run("contact")
    assert run_id != "gone"
    assert url == f"/contact/{run_id}/first/"


def test_a_member_can_name_the_step_a_reopened_stash_lands_on(rf):
    class _LandingHub(_Hub):
        members = [Member("contact", _MemberViewSet, reopen_step="second")]

    request = rf.get("/hub/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )
    page = _LandingHub(request)

    url = page.enter(page.get_member("contact"))

    run_id = SessionJourneyStore(
        WizardContext.from_request(request), "default"
    ).get_run("contact")
    assert url == f"/contact/{run_id}/second/"


def test_a_stash_whose_label_no_longer_matches_is_refused_loudly(rf):
    """A deploy reshaped the member and bumped its label. Starting over
    silently would look to the user exactly like their answers vanishing."""
    from gandalf.runtime import InvalidStash

    class _Reshaped(_Hub):
        members = [Member("contact", _MemberViewSet, label="contact-v2")]

    request = rf.get("/hub/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )
    page = _Reshaped(request)

    with pytest.raises(InvalidStash):
        page.enter(page.get_member("contact"))


def test_stash_unusable_can_be_overridden_to_start_over(rf):
    class _Forgiving(_Hub):
        members = [Member("contact", _MemberViewSet, label="contact-v2")]

        def stash_unusable(self, member, error):
            store = self.get_journey_store()
            store.delete_stash(member.key)
            return self.enter(member)

    request = rf.get("/hub/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )
    page = _Forgiving(request)

    url = page.enter(page.get_member("contact"))

    run_id = SessionJourneyStore(
        WizardContext.from_request(request), "default"
    ).get_run("contact")
    assert url == f"/contact/{run_id}/first/"


# --- RunMemberMixin ----------------------------------------------------------


def test_finishing_a_member_stashes_its_answers_and_clears_its_run(rf):
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )
    view = _MemberViewSet()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    view.done(bound_wizard)

    store = SessionJourneyStore(context, "default")
    assert store.get_stash("contact") == {
        "version": STASH_VERSION,
        "label": "contact",
        "state": [{"step": {"name": "Ada"}}],
    }
    assert store.get_run("contact") is None


def test_a_member_done_that_raises_leaves_the_member_resumable(rf):
    """Mirrors `_finish`'s own ordering — the run id is cleared only after
    the application's work has succeeded."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Failing(_MemberViewSet):
        def run_done(self, bound_wizard):
            raise RuntimeError("nope")

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )
    view = _Failing()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    with pytest.raises(RuntimeError):
        view.done(bound_wizard)

    assert SessionJourneyStore(context, "default").get_run("contact") == "run-1"


def test_bookkeeping_recorded_at_completion_runs_between_the_stash_and_member_done(
    rf,
):
    """`run_recorded()` sits above `run_done()` and below the stash, so
    it can read what was just recorded and cannot be pre-empted by an
    application hook that obliterates, escapes or raises."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    events = []

    class _Recording(_MemberViewSet):
        def run_recorded(self, bound_wizard, store, key):
            events.append(("recorded", key, store.get_stash(key)["state"]))

        def run_done(self, bound_wizard):
            events.append(("done", self.get_member_key(), None))
            return super().run_done(bound_wizard)

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {
            "runs": {"contact": "run-1"},
            "gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}},
        }
    )
    view = _Recording()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    view.done(bound_wizard)

    assert events == [
        ("recorded", "contact", [{"step": {"name": "Ada"}}]),
        ("done", "contact", None),
    ]


def test_bookkeeping_recorded_at_completion_can_still_read_the_runs_answers(rf):
    """The window closes when `finish()` tombstones the run, which is why
    anything that has to read the finished answers belongs here."""
    from gandalf.storage import SessionStorage

    seen = []

    class _Recording(_MemberViewSet):
        def run_recorded(self, bound_wizard, store, key):
            seen.append(bound_wizard.get_state())

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    view = _Recording()
    view.setup(request)
    bound_wizard = _Recording.inspect(request, "run-1")

    view.finish(bound_wizard)

    assert seen == [[{"step": {"name": "Ada"}}]]
    assert bound_wizard.is_complete
    assert SessionStorage(bound_wizard.context).get_state("run-1") == []


def test_a_members_stash_label_can_be_bumped_independently_of_its_key(rf):
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Reshaped(_MemberViewSet):
        member_label = "contact-v2"

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    view = _Reshaped()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    view.done(bound_wizard)

    assert (
        SessionJourneyStore(context, "default").get_stash("contact")["label"]
        == "contact-v2"
    )


def test_a_member_without_a_key_is_misconfigured(rf):
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Keyless(_MemberViewSet):
        member_key = None

    request = rf.get("/contact/run-1/")
    request.session = _session({"gandalf_runs": {"run-1": {"state": []}}})
    view = _Keyless()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    with pytest.raises(ImproperlyConfigured, match="member_key"):
        view.done(bound_wizard)


def test_a_member_without_a_hub_url_name_is_misconfigured(rf):
    class _Homeless(_MemberViewSet):
        hub_url_name = None

    view = _Homeless()
    view.setup(rf.get("/contact/"))

    with pytest.raises(ImproperlyConfigured, match="hub_url_name"):
        view.get_hub_url()


def test_a_finished_member_sends_the_user_back_to_its_hub(rf):
    """The default `run_done` — a task list expects a finished task to
    deposit the user back on the list."""
    from gandalf.runtime import BoundWizard
    from gandalf.storage import SessionStorage

    class _Homed(_MemberViewSet):
        hub_url_name = "readme-hub"
        run_done = RunMemberMixin.run_done

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    view = _Homed()
    view.setup(request)
    context = WizardContext.from_request(request)
    bound_wizard = BoundWizard(context, SessionStorage(context))
    bound_wizard.retrieve("run-1")

    response = view.done(bound_wizard)

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


# --- URLs ------------------------------------------------------------------


class _ReversingHub(HubMixin):
    """Reverses this project's real hub patterns rather than faking them."""

    url_name = "readme-hub"
    member_url_name = "readme-hub-member"
    members = [Member("contact", _MemberViewSet)]

    def __init__(self, request, **kwargs):
        self.request = request
        self.kwargs = kwargs


def test_a_row_links_to_the_hubs_own_door_not_the_wizards_urls(rf):
    request = rf.get("/readme/hub/")
    request.session = _session()

    url = _ReversingHub(request).get_member_url(Member("contact", _MemberViewSet))

    assert url == "/readme/hub/contact/"


def test_a_hub_forwards_its_mount_prefix_and_drops_the_member_kwarg(rf):
    request = rf.get("/org/acme/hub/details/")
    request.session = _session()

    page = _ReversingHub(request, org="acme", member="details")

    assert page.get_page_url_kwargs() == {"org": "acme"}


def test_the_hub_url_is_reversed_from_its_own_url_name(rf):
    request = rf.get("/readme/hub/")
    request.session = _session()

    assert _ReversingHub(request).get_page_url() == "/readme/hub/"


def test_an_unknown_member_is_sent_back_to_the_hub(rf):
    request = rf.get("/readme/hub/nope/")
    request.session = _session()

    response = _ReversingHub(request).member_unavailable("nope")

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


def test_a_row_can_point_at_something_that_is_not_a_wizard(rf):
    """A collection page, a payment redirect, a page in another app. The door
    exists to walk a run and pick a step; something with no run to walk has
    nothing for it to do, so the row addresses it directly."""
    request = rf.get("/readme/hub/")
    request.session = _session()
    member = Member(
        "guests",
        url_name="readme-hub",
        status=lambda request, url_kwargs: COMPLETE,
    )

    assert _ReversingHub(request).get_member_url(member) == "/readme/hub/"


def test_a_row_that_decides_its_own_status_is_not_derived_from_storage(rf):
    """A collection is Complete when the *user* said there was nothing more
    to add — no reading of storage under one key can tell a hub that."""

    class _Linked(_ReversingHub):
        members = [
            Member(
                "guests",
                url_name="readme-hub",
                status=lambda request, url_kwargs: COMPLETE,
            )
        ]

    request = rf.get("/readme/hub/")
    request.session = _session()

    (row,) = _Linked(request).get_member_rows()

    assert row.status == COMPLETE
    assert row.status_label == "Complete"
    assert row.url == "/readme/hub/"


def test_a_row_pointing_at_a_non_wizard_must_say_where_and_how_far(rf):
    """Without the first the hub builds a door it cannot open; without the
    second it derives a status from a stash key nothing writes."""

    class _Underspecified(_ReversingHub):
        members = [Member("guests", url_name="readme-hub")]

    request = rf.get("/readme/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="url_name and status"):
        _Underspecified(request).get_member_rows()


def test_the_door_refuses_a_member_it_cannot_walk(rf):
    """Rows never point there, so arriving is a hand-typed or stale URL."""

    class _Linked(_ReversingHub):
        members = [
            Member(
                "guests",
                url_name="readme-hub",
                status=lambda request, url_kwargs: COMPLETE,
            )
        ]

    request = rf.get("/readme/hub/guests/")
    request.session = _session()
    page = _Linked(request)

    assert page.enter(page.get_member("guests")) is None


def test_a_hub_without_a_member_url_name_is_misconfigured(rf):
    class _Nameless(_ReversingHub):
        member_url_name = None

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="member_url_name"):
        _Nameless(request).get_member_url(Member("contact", _MemberViewSet))


def test_a_hub_without_a_url_name_is_misconfigured(rf):
    from gandalf.hubs import HubView

    class _Nameless(_ReversingHub):
        url_name = None

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        _Nameless(request).get_page_url()
    with pytest.raises(ImproperlyConfigured, match="url_name"):

        class _NamelessView(HubView):
            pass

        _NamelessView.urls()


def _profile_hub(rf, path, **kwargs):
    """The README's hub, dispatched directly — one view over two routes."""
    from tests.testapp.readme.ch11_hub import GrantHubView

    request = rf.get(path)
    request.session = _session()
    return GrantHubView.as_view()(request, **kwargs)


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
    assert "/readme/hub-contact/" in response["Location"]


def test_the_door_sends_a_member_it_cannot_walk_back_to_the_hub(rf):
    """A row that is not a wizard links past the door anyway — so arriving
    here is a hand-typed or stale URL."""
    from gandalf.hubs import HubView

    class _Linked(HubView):
        template_name = "testapp/hub.html"
        url_name = "readme-hub"
        member_url_name = "readme-hub-member"
        members = [
            Member("elsewhere", url_name="readme-hub", status=lambda r, k: COMPLETE)
        ]

    request = rf.get("/readme/hub/elsewhere/")
    request.session = _session()

    response = _Linked.as_view()(request, member="elsewhere")

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


def test_the_door_sends_an_unknown_member_back_to_the_hub(rf):
    response = _profile_hub(rf, "/readme/hub/nope/", member="nope")

    assert response.status_code == 302
    assert response["Location"] == "/readme/hub/"


def test_a_hub_publishes_a_page_pattern_and_a_door_pattern():
    from gandalf.hubs import HubView

    class _Published(HubView):
        url_name = "profile-hub"

    page, door = _Published.urls()

    assert page.name == "profile-hub"
    assert door.name == "profile-hub-member"
    assert str(door.pattern) == "<slug:member>/"


# --- a member that is hidden -----------------------------------------------


class _PartnerViewSet(_AddressMemberViewSet):
    """A member that only exists once an answer elsewhere says so."""

    @classmethod
    def hidden(cls, request, member, store):
        return not store.data.get("has_partner", False)


class _PartnerHub(_Hub):
    members = [
        Member("contact", _MemberViewSet, title="Contact details"),
        Member("address", _PartnerViewSet, title="Partner"),
    ]


@pytest.fixture
def partner_hub(rf):
    def build(session=None):
        request = rf.get("/hub/")
        request.session = _session(session or {})
        return _PartnerHub(request)

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

    class _Both(_PartnerViewSet):
        @classmethod
        def blocked(cls, request, member, store):
            return True

    class _BothHub(_Hub):
        members = [Member("address", _Both, title="Partner")]

    request = rf.get("/hub/")
    request.session = _session()

    hub = _BothHub(request).get_hub()

    assert hub.count == 0
    assert hub.blocked == 0


def test_the_declaration_is_vetted_before_anything_is_hidden(rf):
    """A drifted key is a mistake whether or not an answer hides it today."""

    class _Drifted(_PartnerHub):
        members = [Member("billing", _PartnerViewSet)]

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="member_key"):
        _Drifted(request).get_member_rows()


def test_a_hub_override_can_hide_on_the_members_behalf(partner_hub):
    """`member_hidden()` mirrors `member_blocked()`: the hub's hook for
    what one member cannot answer alone, replacing the question."""
    page = partner_hub()
    page.member_hidden = lambda member, store: member.key == "contact"

    # Contact is hidden by the hub; Partner, which the member itself would
    # have hidden, is listed — the override replaced the question.
    assert [row.key for row in page.get_member_rows()] == ["address"]


def test_a_member_that_is_not_a_wizard_is_never_asked_whether_it_is_hidden(rf):
    class _Linked(_Hub):
        members = [
            Member(
                "payment",
                title="Payment",
                url_name="pay",
                status=lambda request, url_kwargs: NOT_STARTED,
            )
        ]

    request = rf.get("/hub/")
    request.session = _session()
    page = _Linked(request)

    store = page.get_journey_store()
    assert page.member_hidden(page.get_member("payment"), store) is False


# --- the journey ------------------------------------------------------------


def test_a_hub_reads_its_journey_off_the_url_when_mounted_under_one(rf):
    request = rf.get("/apply/app-1/")
    request.session = _session()
    page = _Hub(request)
    page.kwargs = {"journey": "app-1"}

    assert page.get_journey() == "app-1"
    assert page.get_journey_url_kwargs() == {"journey": "app-1"}


def test_a_hub_mounted_under_no_journey_uses_the_one_it_declares(hub):
    page = hub()

    assert page.get_journey() == "default"
    assert page.get_journey_url_kwargs() == {}


def test_a_hub_keeps_its_bookkeeping_under_its_journey(rf):
    """Two journeys in one session are two task lists."""
    request = rf.get("/apply/app-2/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}, journey="app-1"
    )
    page = _Hub(request)
    page.kwargs = {"journey": "app-2"}

    (row,) = page.get_member_rows()

    assert row.status == NOT_STARTED


def test_the_door_hands_every_member_view_the_journey(rf):
    """A member mounted under the same segment as its hub reads the same
    journey, so the run it starts is recorded where the hub will look."""
    seen = []

    class _Recording(_MemberViewSet):
        @classmethod
        def begin(cls, request, **url_kwargs):
            seen.append(url_kwargs)
            return super().begin(request)

    class _Mounted(_Hub):
        members = [Member("contact", _Recording, url_kwargs={"org": "acme"})]

    request = rf.get("/apply/app-1/hub/")
    request.session = _session()
    page = _Mounted(request)
    page.kwargs = {"journey": "app-1"}

    page.enter(page.get_member("contact"))

    assert seen == [{"journey": "app-1", "org": "acme"}]
    assert SessionJourneyStore(page.request, "app-1").get_run("contact") is not None


def test_a_status_callable_is_handed_the_journey_too(rf):
    seen = []

    class _Linked(_Hub):
        members = [
            Member(
                "guests",
                title="Guests",
                url_name="pay",
                status=lambda request, url_kwargs: seen.append(url_kwargs) or COMPLETE,
            )
        ]

    request = rf.get("/apply/app-1/hub/")
    request.session = _session()
    page = _Linked(request)
    page.kwargs = {"journey": "app-1"}

    page.get_member_rows()

    assert seen == [{"journey": "app-1"}]


def test_a_member_on_another_journey_than_its_hub_is_rejected(rf):
    """It would finish into a record the hub never reads — the same quiet
    failure as a drifted key, one level up."""

    class _Astray(_MemberViewSet):
        journey = "profile"

    class _Mismatched(_Hub):
        members = [Member("contact", _Astray)]

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="Astray"):
        _Mismatched(request).get_member_rows()


def test_a_member_reading_a_different_journey_kwarg_is_rejected(rf):
    class _Astray(_MemberViewSet):
        journey_url_kwarg = "application"

    class _Mismatched(_Hub):
        members = [Member("contact", _Astray)]

    request = rf.get("/hub/")
    request.session = _session()

    with pytest.raises(ImproperlyConfigured, match="journey_url_kwarg"):
        _Mismatched(request).get_member_rows()


def test_a_member_reads_its_journey_off_the_url_when_mounted_under_one(rf):
    view = _MemberViewSet()
    view.setup(rf.get("/apply-contact/app-1/"), journey="app-1")

    assert view.get_journey() == "app-1"
    assert view.get_journey_store().journey == "app-1"


def test_finishing_a_member_writes_what_it_decided_where_the_hub_reads_it(rf):
    """The whole point of `store.data`: one walk at completion, and every
    later render reads a string."""

    class _Deciding(_MemberViewSet):
        def run_done(self, bound_wizard):
            step = bound_wizard.path.find_step(name="first")
            self.get_journey_store().data["name"] = step.form.cleaned_data["name"]
            return super().run_done(bound_wizard)

    request = rf.get("/contact/run-1/")
    request.session = _session(
        {"gandalf_runs": {"run-1": {"state": [{"step": {"name": "Ada"}}]}}}
    )
    view = _Deciding()
    view.setup(request)

    view.done(_Deciding.inspect(request, "run-1"))

    context = WizardContext.from_request(request)
    assert SessionJourneyStore(context, "default").data["name"] == "Ada"


# --- submitting the journey ---------------------------------------------------


class _SubmittableHub(_PairHub):
    def get_page_url(self):
        return "/hub/"

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
    request = rf.post("/hub/")
    request.session = _session(_complete_pair())
    page = _SubmittableHub(request)

    response = page.submit()

    store = SessionJourneyStore(page.request, "default")
    assert response.content == b"submitted"
    assert store.is_complete() is True
    assert store.keys() == []
    assert store.data["reference"] == "REF-2"


def test_submitting_an_incomplete_journey_is_refused(rf):
    """A stale button or a hand-made POST cannot submit half a journey."""
    request = rf.post("/hub/")
    request.session = _session(
        {"stashes": {"contact": _stash([{"step": {"name": "Ada"}}])}}
    )
    page = _SubmittableHub(request)

    response = page.submit()

    assert response.status_code == 302
    assert response["Location"] == "/hub/"
    assert SessionJourneyStore(page.request, "default").is_complete() is False


def test_a_journey_done_that_raises_leaves_the_journey_resumable(rf):
    """`done()`'s ordering, one level up: the work first, the tombstone only
    once it has succeeded."""

    class _Failing(_SubmittableHub):
        def journey_done(self, hub, store):
            raise RuntimeError("nope")

    request = rf.post("/hub/")
    request.session = _session(_complete_pair())
    page = _Failing(request)

    with pytest.raises(RuntimeError):
        page.submit()

    store = SessionJourneyStore(page.request, "default")
    assert store.is_complete() is False
    assert store.keys() == ["contact", "address"]


def test_a_hub_with_nothing_to_do_at_submit_is_misconfigured(rf):
    request = rf.post("/hub/")
    request.session = _session(_complete_pair())

    with pytest.raises(ImproperlyConfigured, match="journey_done"):
        _PairHub(request).submit()


def test_a_hub_says_a_submitted_journey_is_gone_by_default(rf):
    from django.http import Http404

    request = rf.get("/hub/")
    request.session = _session({"completed": True})
    page = _Hub(request)

    with pytest.raises(Http404):
        page.journey_completed(page.get_journey_store())


def _apply(rf, method, path, session=None, **kwargs):
    """The README's journey hub, dispatched directly under a journey."""
    from tests.testapp.readme.ch14_journey import GrantApplicationHubView

    request = getattr(rf, method)(path)
    request.session = _session(session, journey="app-1")
    return GrantApplicationHubView.as_view()(request, journey="app-1", **kwargs)


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
                "referees": _stash([{"step": {}}], "referees"),
                f"budget:{line}": _stash([{"step": {}}], "budget"),
            },
            "collections": {
                "budget": {
                    "items": [{"id": line, "title": "Paint"}],
                    "declared_done": True,
                }
            },
        },
    )

    assert response.status_code == 302
    assert response["Location"] == "/readme/apply/app-1/"


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
    """A stale step URL must not re-open a member into a tombstone."""
    from tests.testapp.readme.ch14_journey import ContactMemberViewSet

    request = rf.get("/readme/apply-contact/app-1/")
    request.session = _session({"completed": True}, journey="app-1")

    response = ContactMemberViewSet.as_view()(request, journey="app-1")

    assert response.status_code == 302
    assert response["Location"] == "/readme/apply/app-1/"
