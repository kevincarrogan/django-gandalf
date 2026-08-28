"""Hub and spoke: a page of parallel wizards the user drops in and out of.

A hub asks the same three questions of every member — what is it called, how
far has it got, and where does its link go — so `HubMixin` answers them once.
Mix it into the page's view and the template gets a `hub`: one `MemberRow`
per declared member, carrying its title, its status, and one URL that does
the right thing whichever of the three states it is in, wrapped in a `Hub`
that says how far the whole page has got.

A member is *complete* when it ran to its own end and `done()` stashed the
answers. That is the only definition the hub has, and it is deliberately the
cheap one: a row costs two storage reads and a `reverse()`, never a walk.
Finding out where a half-finished run actually is does cost a walk, so it
happens once, on the way in, for the one member the user clicked.

Every decision is a hook: `get_members()` chooses the members,
`get_member_status()` decides how far one has got, `get_hub_status()` decides
how far they have got between them, `get_member_title()` names it,
`get_member_url()` says where its link goes, and `resume_member()` /
`reopen_member()` / `start_member()` each own one way into a run. The
defaults suit a plain task list; override what your domain needs.

Whether a member is open to the user yet is the one question the member
answers rather than the hub: `RunMemberMixin.blocked()` on its own viewset, so
the rule lives with the wizard it gates instead of as an arm of a hub method
with a key in scope. `hidden()` is its sibling for a member that should not
be listed at all yet. `member_blocked()` and `member_hidden()` remain for
what one member cannot answer alone.

The members add up to a *journey* — the application, the claim, the profile
— and everything a hub keeps is scoped to one: `SessionJourneyStore` is built
with the journey's identity, which a hub reads off a URL kwarg or declares.
`store.data` is the journey's record of what its members decided, written at
`run_done()` and read by `blocked()` and `hidden()` without a walk. And a
journey has its own completion: `submit()` runs `journey_done()` once the
hub is complete, then tombstones the journey so a revisit reads as submitted.

A hub can be a member of a hub. Nesting is a key namespace over the same
record — a nested hub prefixes its `member_key` onto every member it lists
(`full_key()`), the way a collection prefixes its items — so task lists nest
to any depth, a member two hubs down still reads the journey's `data`, and
the root's submit still ends everything at once. A *member* is anything a
hub lists — a run (`RunMemberMixin` on its viewset), a hub, a collection —
and `JourneyMemberMixin` is what they share: a key, a return, a journey, and
`blocked()` / `hidden()`.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.urls import URLPattern, path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.views.generic import TemplateView, View

from gandalf.context import WizardContext
from gandalf.runtime import BoundWizard, InvalidStash
from gandalf.storage import RunNotFound, SessionJourneyStore, StashNotFound
from gandalf.types import JourneyStore, State, StrOrPromise
from gandalf.viewsets import WizardViewSet


if TYPE_CHECKING:
    # Mixins with no bases of their own: at type-check time each is given the
    # class it documents itself as mixing into, so `self.request`,
    # `get_context_data()` and the rest resolve. At runtime both stay plain
    # mixins.
    _JourneyMemberBase = View
    _MemberMixinBase = WizardViewSet
    _HubMixinBase = TemplateView
else:
    _JourneyMemberBase = object
    _MemberMixinBase = object
    _HubMixinBase = object


__all__ = [
    "BLOCKED",
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "Hub",
    "HubMixin",
    "HubView",
    "JourneyMemberMixin",
    "Member",
    "RunMemberMixin",
    "MemberNotFound",
    "MemberRow",
]


# Plain strings rather than an enum, following `run_unavailable(reason=...)`:
# a status is rendered into a template and compared in one, and neither reads
# well through a member lookup.
NOT_STARTED = "not-started"
INCOMPLETE = "incomplete"
COMPLETE = "complete"
# Named for the state rather than the wording, unlike its three siblings,
# because the wording is a label's job and `is_cannot_start` is no name for a
# property. The default label is the task list's own: "Cannot start yet".
BLOCKED = "blocked"


class MemberNotFound(LookupError):
    """Raised when a key names no member this hub declares — a stale link,
    a renamed member, or a URL typed by hand."""


@dataclass(frozen=True)
class Member:
    """One spoke of a hub: something the user can enter, leave, and come back
    to — a wizard, or another hub.

    `key` is the member's identity — the stash key its finished answers live
    under and the URL segment the hub's own door routes on. Relative to the
    hub that lists it: a hub nested under a parent prefixes its own key, so
    the store sees `"supporting:referees"` where the hub declared
    `"referees"` (see `HubMixin.full_key()`). `viewset` is the class that runs
    it — a `RunMemberMixin` wizard viewset, or a `HubMixin` view for a task list
    (or a collection) that is itself a member of this one. `title` is what
    the hub renders; without one the key is made readable, exactly as a
    summary row's label is.

    `label` is the *shape's* identity, not the member's: it is stamped into
    the stash and checked on the way back out, so a deploy that reshapes this
    wizard can bump the label without renaming the member, and a payload from
    the old shape is refused at the door rather than walked into a tree it no
    longer matches. Defaults to the full key (`HubMixin.stash_label()`).

    `reopen_step` names the step a completed member re-opens at; without one
    it is the first step on the route, so the user walks their own answers
    rather than landing at the end. `url_kwargs` are the mount-prefix kwargs
    this member's wizard is mounted under (a tenant slug, a plan), forwarded
    into every URL the hub builds for it — the member's own, not the hub's,
    since the two can be mounted separately.

    A member need not be a wizard at all. Leave `viewset` out and supply
    `url_name` and `status` instead, and the row becomes a link to somewhere
    the hub does not run: a collection page, a payment redirect, a page in
    another app. Both are required together — without the first the hub builds
    a door it cannot open, and without the second it derives a status from a
    stash key nothing writes.
    """

    key: str
    viewset: type[WizardViewSet] | type[HubMixin] | None = None
    title: StrOrPromise | None = None
    label: str | None = None
    reopen_step: str | None = None
    # Excluded from comparison so a mutable default cannot make a frozen
    # member unhashable — the same escape `SummaryField.bound_field` takes.
    url_kwargs: dict[str, Any] = dataclass_field(default_factory=dict, compare=False)
    #: Where this row links, instead of the hub's own door. The door exists to
    #: walk a run and pick a step; something with no run to walk has nothing
    #: for it to do, so the row addresses it directly.
    url_name: str | None = None
    #: What decides this member's status when the hub cannot. Called with the
    #: request and the URL kwargs the hub would hand the member's own view
    #: (`HubMixin.member_url_kwargs()`: its journey, under these `url_kwargs`)
    #: so the answer is scoped as the hub is.
    #: Excluded from comparison for the same reason as `url_kwargs`.
    status: Callable[[HttpRequest, dict[str, Any]], str] | None = dataclass_field(
        default=None, compare=False
    )


@dataclass(frozen=True)
class MemberRow:
    """One member of a hub: what it is called, how far it has got, and where
    its link goes. `member` is the underlying `Member`, so a template that
    needs the viewset or the member's own key can still reach them."""

    member: Member
    status: str
    title: StrOrPromise
    status_label: StrOrPromise
    url: str

    @property
    def key(self) -> str:
        """The member's key."""
        return self.member.key

    @property
    def is_not_started(self) -> bool:
        return self.status == NOT_STARTED

    @property
    def is_incomplete(self) -> bool:
        return self.status == INCOMPLETE

    @property
    def is_complete(self) -> bool:
        return self.status == COMPLETE

    @property
    def is_blocked(self) -> bool:
        """Whether the user cannot start this member yet. A blocked row's
        link is refused at the door, so it is the one status where the row and
        the door have to agree."""
        return self.status == BLOCKED


@dataclass(frozen=True)
class Hub:
    """The hub as a whole: its rows, and how far the whole page has got. What
    a task list's heading and its final submit button both read.

    The counts are the reason this exists. "You have completed 2 of 5
    members" is the task list pattern, and deriving it in the view means
    asking for the rows a second time — a second pair of storage reads per
    member, and a whole second `Collection` for any member that is one.
    `rows` is built once and counted here.
    """

    rows: tuple[MemberRow, ...]
    status: str
    status_label: StrOrPromise

    @property
    def count(self) -> int:
        """How many members the hub lists."""
        return len(self.rows)

    @property
    def completed(self) -> int:
        """How many of them have run to their own end."""
        return sum(1 for row in self.rows if row.is_complete)

    @property
    def remaining(self) -> int:
        """How many have not — a member the user cannot start yet included,
        since it is still work the journey is waiting on."""
        return self.count - self.completed

    @property
    def blocked(self) -> int:
        """How many are waiting on an answer given elsewhere."""
        return sum(1 for row in self.rows if row.is_blocked)

    @property
    def is_not_started(self) -> bool:
        return self.status == NOT_STARTED

    @property
    def is_incomplete(self) -> bool:
        return self.status == INCOMPLETE

    @property
    def is_complete(self) -> bool:
        return self.status == COMPLETE


class JourneyMemberMixin(_JourneyMemberBase):
    """What a run and a hub have in common: being a member of a journey.

    Both are listed by a hub above them — a wizard as a `RunMemberMixin`
    viewset, a task list or a collection as a `HubMixin` view — and a hub
    asks the same things of each: which key it finishes under
    (`member_key`), where finishing sends the user back to (`hub_url_name`),
    which journey it is on (`journey` / `journey_url_kwarg`), and whether the
    user may open it yet (`blocked()` / `hidden()`). A root hub, listed by
    nothing, declares neither key nor return.

    A journey is one record — `SessionJourneyStore(context, journey)` — and
    every member reads the same one, so a member nested two hubs down still
    reads `store.data` written at the top. Nesting is a key namespace, not a
    second store: a hub with a `member_key` prefixes it onto every member
    it lists (`HubMixin.full_key()`), the way a collection prefixes its items.
    """

    #: The key this member finishes under in the journey's store — the *full*
    #: key, prefix included: `"referees"` under a root hub,
    #: `"supporting:referees"` under a hub keyed `"supporting"`. A wizard
    #: stashes under it; a hub keys every member it lists under it. It is the
    #: same string the hub above computes with `full_key()` from the *short*
    #: `Member.key` it lists this member by, and the hub checks that the two
    #: agree. `None` for a hub nothing lists.
    member_key: str | None = None
    #: The hub finishing returns to — the parent's `url_name`. `None` for a
    #: root hub.
    hub_url_name: str | None = None
    journey_store_class = SessionJourneyStore
    #: Which journey this member belongs to. Read off the URL when mounted
    #: under a `<journey>` segment (`journey_url_kwarg`), otherwise this fixed
    #: one — a hub that lists one journey per session, which is what a profile
    #: task list is. Has to agree with the hub's, and the hub checks that it
    #: does.
    journey: str = "default"
    journey_url_kwarg = "journey"
    #: What joins a hub's prefix to a member's key — and a collection's key
    #: to an item's id. One character on every member, so a key composed by
    #: a page and one composed by an item wizard agree.
    key_separator = ":"

    @classmethod
    def blocked(cls, request: HttpRequest, member: Member, store: JourneyStore) -> bool:
        """Whether this member is visible but not open to the user yet — the
        row reads **Cannot start yet**, and the door refuses it.

        `False` for everything by default. Two rules cover nearly every task
        list, and both are one read of the journey's store:

            class EmploymentHistoryMemberViewSet(RunMemberMixin, WizardViewSet):
                member_key = "employment_history"

                # Unlocks once the Employment member has been finished.
                @classmethod
                def blocked(cls, request, member, store):
                    return not store.has_stash("employment")

            class ReferencesMemberViewSet(RunMemberMixin, WizardViewSet):
                member_key = "references"

                # Unlocks once the applicant has said they are employed —
                # a fact the Employment member wrote at run_done().
                @classmethod
                def blocked(cls, request, member, store):
                    return store.data.get("employment_status") != "employed"

        Answered by the member rather than asked about it, so the rule lives
        with the wizard it gates: it has a name, a docstring, a subclass, and
        a test that needs no hub. Declared on this side, there is no key in
        scope to branch on, which is the whole point — the hub's own
        `member_blocked()` hook is still there for a rule one member cannot
        answer alone. A nested hub answers for itself the same way.

        A classmethod because the hub asks from outside this member's own
        dispatch, exactly as it asks `begin()` and `inspect()`: there is no
        instance yet, and the point of the question is that there must not be
        a run.

        Read `store.data` and `store.has_stash()` here, never a stash's
        *state*. A stash is positional against a tree whose shape may depend
        on a branch predicate nobody has evaluated, so reading an answer out
        of one costs a walk; `run_done()` is where a member pays that
        once and writes what it decided into `store.data`, and this is where
        the rest of the journey reads it back for free.

        The sibling question — should this member be listed at all yet — is
        `hidden()`. A locked row is still work the journey is waiting on and
        keeps the hub off `COMPLETE`; a hidden one does not exist.

        `member` is the row being asked about — what one viewset mounted per
        item of a collection needs to tell its items apart, and what a plain
        member can ignore.

        Called once per row when the page renders, and once more at the door,
        so keep it cheap — the hub's promise is that a row costs storage reads
        and no walk, and this runs inside it.
        """
        return False

    @classmethod
    def hidden(cls, request: HttpRequest, member: Member, store: JourneyStore) -> bool:
        """Whether this member should not be listed yet — because an answer
        given elsewhere has not made it relevant, or has made it moot.

        `False` for everything by default. Override with the same kind of
        rule `blocked()` takes, read from the same store:

            class PartnerMemberViewSet(RunMemberMixin, WizardViewSet):
                member_key = "partner"

                # Only exists for an applicant who said they have one.
                @classmethod
                def hidden(cls, request, member, store):
                    return not store.data.get("has_partner", False)

        A hidden member is gone from the hub for this request: not in its
        rows, not in its counts, and its door refuses a stale link exactly as
        it refuses a key the hub never declared. That is the difference from
        `blocked()`, which keeps the row and locks it. Use this for a member
        that may never apply; use `blocked()` for one that will, once the
        user has done something else first.

        Asked once per declared member per request, before the rows are
        built, so it costs what `blocked()` costs and no more.
        """
        return False

    def get_journey(self) -> str:
        """Which journey this request is on: the URL's `journey_url_kwarg`
        when mounted under one, otherwise the declared `journey`."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        return str(url_kwargs.get(self.journey_url_kwarg, self.journey))

    def get_journey_store(self) -> JourneyStore:
        return self.journey_store_class(
            WizardContext.from_request(self.request), self.get_journey()
        )

    def get_hub_url(self) -> str:
        """Where finishing sends the user back to: the hub that lists this
        member, under the URL kwargs `get_hub_url_kwargs()` supplies."""
        if self.hub_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set hub_url_name (or override get_hub_url) on {name}."
            )
        return reverse(self.hub_url_name, kwargs=self.get_hub_url_kwargs())

    @abstractmethod
    def get_hub_url_kwargs(self) -> dict[str, Any]:
        """The URL kwargs the hub above is reversed with — the journey, a
        tenant prefix. Each kind of member knows its own mount: a run forwards
        its wizard's, a hub its page's, an item everything but its segment."""

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Refuse every request once the journey has been submitted.

        A tombstone has no runs and no stashes, so a hub rendering it would
        show every member as not started over a journey that is finished,
        and a member re-opened after submission would stash into it. The
        hub's routes are not the only way in — a bookmarked step URL addresses
        a member directly — so every member checks. One store read per
        request buys the guarantee that a submitted journey can never be
        answered again.
        """
        store = self.get_journey_store()
        if store.is_complete():
            return self.journey_completed(store)
        return super().dispatch(request, *args, **kwargs)

    def journey_completed(self, store: JourneyStore) -> HttpResponseBase:
        """Response for a request that reaches this member after its journey
        was submitted. The default sends the user back to the hub above, whose
        own `journey_completed()` says what a submitted journey looks like;
        override to raise `Http404`."""
        return redirect(self.get_hub_url())


class RunMemberMixin(JourneyMemberMixin, _MemberMixinBase):
    """Mix into a member's `WizardViewSet` so finishing it registers with the
    hub.

    **Members override `run_done()`, never `done()`.** `done()` is this
    mixin's: a subclass that replaced it would stash nothing, and the hub
    would never learn the member had finished — a member that appears to
    reset itself every time it is completed.

        class ContactMemberViewSet(RunMemberMixin, WizardViewSet):
            url_name = "profile-contact"
            member_key = "contact"
            hub_url_name = "profile-hub"
            wizard = ...

            def run_done(self, bound_wizard):
                save_contact(self.request.user, bound_wizard)
                return super().run_done(bound_wizard)

    Re-opening a completed member and fixing one answer walks to the end and
    fires `done()` again. That is the intended "edit and re-save" semantics,
    which is why the bookkeeping here is idempotent and `run_done()` is
    where work that runs once per edit belongs. Give the wizard a review step
    if the user should get an explicit confirm gate first.

    `member_key` is the *full* key — under a nested hub, the hub's prefix and
    the member's own key joined with `:` (`"supporting:referees"`), since
    this viewset stashes in its own request and nothing but its declaration
    can tell it where. The hub checks it agrees.
    """

    member_label: str | None = None
    #: Whether this member's key is only knowable per request — one wizard
    #: mounted per item of a collection, keyed off a URL kwarg. Such a member
    #: overrides `get_member_key()` and declares no `member_key`, so the
    #: usual "set the class attribute" advice would be wrong for it.
    dynamic_member_key: bool = False

    def get_member_key(self) -> str:
        if self.member_key is None:
            name = self.__class__.__name__
            if self.dynamic_member_key:
                raise ImproperlyConfigured(
                    f"{name} declares dynamic_member_key but derives no key. "
                    f"Override {name}.get_member_key() to build one from the "
                    f"request — a URL kwarg, the user, the tenant."
                )
            raise ImproperlyConfigured(
                f"{name} has no member to register as finished. Set "
                f"{name}.member_key to the key its hub declares it under."
            )
        return self.member_key

    def get_member_label(self) -> str:
        """The label stamped into this member's stash — `member_label` if
        declared, otherwise the key. Bump it when a deploy reshapes this
        wizard, so a payload from the old shape is refused rather than walked
        into a tree it no longer matches."""
        if self.member_label is None:
            return self.get_member_key()
        return self.member_label

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        """This wizard's own mount-prefix kwargs — the journey among them."""
        return self.get_url_kwargs()

    def done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        """Record the member as finished, then hand off to `run_done()`.

        The stash is taken first because it can only be taken at all while the
        run's state is readable — completion tears that down after `done()`
        returns (see `WizardViewSet.finish`), but a `run_done()` that
        obliterates or escapes would get there first. `run_recorded()`
        shares that window, for the same reason. The run id is cleared after
        `run_done()` returns, mirroring `finish`'s own ordering: a
        `run_done()` that raises leaves the member resumable rather than
        stranded with a stash and no way back to the run that made it.
        """
        key = self.get_member_key()
        store = self.get_journey_store()
        store.put_stash(key, bound_wizard.stash(label=self.get_member_label()))
        self.run_recorded(bound_wizard, store, key)
        response = self.run_done(bound_wizard)
        store.clear_run(key)
        return response

    def run_recorded(
        self, bound_wizard: BoundWizard, store: JourneyStore, key: str
    ) -> None:
        """Bookkeeping to record alongside the stash, inside the window where
        the run's answers are still readable.

        Sits where it does for the same reason the stash does: completion
        tears the run's state down after `done()` returns, and a
        `run_done()` that obliterates or escapes gets there first — so
        anything that has to *read* the finished run belongs above it. A plain
        member records nothing here; a collection's item caches its title,
        because working one out means reading `bound_wizard.path` and there is
        no later moment at which that is possible.

        Not for application work. That is `run_done()`, which runs once
        per edit and is allowed to fail; this is the library's own half of the
        same ordering, and a hub whose bookkeeping raised here would leave a
        stash it could not describe.
        """

    def run_done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        """What this member does when it finishes, beyond being recorded.
        Returns the response the user sees; the default sends them back to the
        hub, which is where a task list expects a finished task to deposit
        them.

        This is where the answers become the journey's. The run is still
        readable here and torn down after, so anything another member's
        `blocked()` or `hidden()` needs to know is read off the path now and
        written to `store.data`, once:

            def run_done(self, bound_wizard):
                step = bound_wizard.path.find_step(name="status")
                self.get_journey_store().data["employment_status"] = (
                    step.form.cleaned_data["status"]
                )
                return super().run_done(bound_wizard)
        """
        return redirect(self.get_hub_url())


class HubMixin(JourneyMemberMixin, _HubMixinBase):
    """Adds `hub` — one `MemberRow` per declared member, and the counts and
    status of the set — to a view's template context, and owns the door each
    row links to.

    Mix into the page listing the members, or use `HubView`, which is this
    over a `TemplateView` with the two URL patterns already published.

    A hub is itself a member of the hub that lists it, when one does. A
    *root* hub — the application's task list — declares no `member_key` and
    no `hub_url_name`, reads its journey off the URL (`path("apply/<journey>/",
    include(ApplicationHubView.urls()))`, so two applications in two tabs are
    two URLs and two records in one session) or declares one, and owns the
    journey's ending. A *nested* hub declares both: `member_key` is the prefix
    every member it lists is keyed under in the shared store, and
    `hub_url_name` is where its own submit returns to. Its status on the
    parent is derived from its rows, exactly as its own `hub.status` is, and
    it tombstones nothing — only the root's `submit()` ends the journey.
    """

    members: list[Member] | None = None
    #: Where the `Hub` lands in the template context. `None` publishes
    #: nothing, for a page that answers "how far has the whole thing got" with
    #: an object of its own — which is what a collection does.
    hub_context_name: str | None = "hub"
    member_url_name: str | None = None
    member_url_kwarg = "member"
    url_name: str | None = None

    # --- this hub's place on the journey -----------------------------------

    def get_member_key(self) -> str | None:
        """The prefix this hub keys its members under: its own full key on the
        journey (`"supporting"`, or `"supporting:more"` two hubs down), or
        `None` for a root hub."""
        return self.member_key

    @property
    def is_nested(self) -> bool:
        """Whether a hub above lists this one — the difference between a
        submit that ends the journey and one that returns to the parent."""
        return self.hub_url_name is not None

    def full_key(self, member: Member) -> str:
        """A member's key in the journey's store: its own key, prefixed by
        this hub's when this hub is nested.

        The one place nesting is spelled out. Everything the hub reads or
        writes about a member — its run, its stash, its state — goes through
        here, so a member's key on the page stays the short one it was
        declared with while the store sees where it sits.
        """
        prefix = self.get_member_key()
        if prefix is None:
            return member.key
        return f"{prefix}{self.key_separator}{member.key}"

    def stash_label(self, member: Member) -> str:
        """The label a member's stash is expected to carry: its declared
        `label`, otherwise its full key — which is what its own viewset stamps
        by default."""
        return self.full_key(member) if member.label is None else member.label

    @classmethod
    def status_for(cls, request: HttpRequest, url_kwargs: dict[str, Any]) -> str:
        """This hub's status as a row on the hub above it.

        What the parent asks instead of reading a stash key: a hub finishes
        nothing into the store, its completion *is* its rows'. The parent hands
        over the URL kwargs it would run this page with — its journey under
        this member's `url_kwargs` — so the answer is read off the same
        record. Costs this hub's rows' storage reads, and still no walk.
        """
        view = cls()
        view.setup(request, **url_kwargs)
        return view.get_hub().status

    @staticmethod
    def is_hub(member: Member) -> bool:
        """Whether a member is another hub rather than a wizard."""
        return member.viewset is not None and issubclass(member.viewset, HubMixin)

    # --- the members this hub lists ---------------------------------------

    def get_members(self) -> list[Member]:
        """The members this hub lists, in the order they are shown. Override
        to choose them per request — by user, by plan, by feature flag."""
        if self.members is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no members to list. Define {name}.members as a "
                f"list of Member declarations, or override "
                f"{name}.get_members() to build one per request."
            )
        return list(self.members)

    def _vetted_members(self) -> list[Member]:
        """`get_members()`, checked once per request, minus the members
        hidden for it.

        Both halves of the hub ask for the members — the rows and the door —
        and the checks are properties of the declaration, not of either use,
        so they run once on the view instance Django builds per request. The
        whole declaration is checked before any of it is hidden: drift is a
        property of what was declared, and a mistake should not pass because
        an answer happened to hide the member carrying it.

        Hiding here, rather than in the rows, is what makes a hidden member
        *gone*: not in `Hub.rows`, not in its counts, and unknown to the
        door, so a stale link to it is refused as a key the hub never
        declared.
        """
        if not hasattr(self, "_members_cache"):
            members = self._validate_members(self.get_members())
            store = self.get_journey_store()
            self._members_cache = [
                member for member in members if not self.member_hidden(member, store)
            ]
        return self._members_cache

    def _validate_members(self, members: list[Member]) -> list[Member]:
        """A key has to name exactly one member, has to be the key that
        member's own viewset finishes under, and that viewset has to return
        to this hub.

        Drift is the quiet failure in all three. A key the member never
        stashes under means the hub reads a stash nothing writes, so the
        member completes and still renders as not started, forever. A
        `hub_url_name` naming some other page means finishing works and simply
        deposits the user somewhere that does not list the member they just
        finished — the pair only ever holds because both sides were typed the
        same, so it is checked rather than trusted.

        The wizard checks are lenient about `None`: a member doing its own
        bookkeeping declares neither. A hub listed as a member is not — it
        keys every member *it* lists under its `member_key`, so one that
        declares none would file them at the root beside this hub's own; and
        a hub with no `hub_url_name` has nowhere for its submit to go. Those
        two are reported as what they are, something left undeclared, rather
        than as drift. A hub that leaves `url_name` unset is mounted under a
        name only its URLconf knows, so there is nothing to compare the
        return against.
        """
        keys = [member.key for member in members]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ImproperlyConfigured(
                "Hub member keys must be unique; a key has to name exactly "
                f"one member. Duplicated: {', '.join(duplicates)}."
            )
        unreachable = [
            member.key
            for member in members
            if member.viewset is None
            and (member.url_name is None or member.status is None)
        ]
        if unreachable:
            raise ImproperlyConfigured(
                "A hub member that is not a wizard must declare both "
                "url_name and status: without the first the hub builds a door "
                "it cannot open, and without the second it derives a status "
                f"from a stash key nothing writes. Underspecified: "
                f"{', '.join(sorted(unreachable))}."
            )
        unmounted = [
            member.key
            for member in members
            if self.is_hub(member) and getattr(member.viewset, "url_name", None) is None
        ]
        if unmounted:
            raise ImproperlyConfigured(
                "A hub listed as a member must declare url_name, or the hub "
                "above it has no page to send the user to. Unmounted: "
                f"{', '.join(sorted(unmounted))}."
            )
        undeclared = [
            f"{member.key} ({member.viewset.__name__} leaves {', '.join(missing)} unset)"
            for member in members
            if self.is_hub(member) and member.viewset is not None
            for missing in [
                [
                    name
                    for name in ("member_key", "hub_url_name")
                    if getattr(member.viewset, name, None) is None
                ]
            ]
            if missing
        ]
        if undeclared:
            raise ImproperlyConfigured(
                "A hub listed as a member must declare member_key (the prefix "
                "it keys its own members under — here its key on this hub, "
                "under this hub's prefix if any) and hub_url_name (this hub, "
                f"where its submit returns to). Undeclared: {', '.join(undeclared)}."
            )
        drifted = [
            member
            for member in members
            if member.viewset is not None
            and getattr(member.viewset, "member_key", None) != self.full_key(member)
            and (
                self.is_hub(member)
                or getattr(member.viewset, "member_key", None) is not None
            )
        ]
        if drifted:
            names = ", ".join(
                f"{member.key} (expected {self.full_key(member)!r}, its viewset "
                f"declares {getattr(member.viewset, 'member_key')!r})"
                for member in drifted
            )
            raise ImproperlyConfigured(
                "A hub member's key must match its viewset's member_key, or "
                "the hub reads a stash the member never writes and the "
                f"member can never complete. Mismatched: {names}."
            )
        if self.url_name is not None:
            mispointed = [
                member
                for member in members
                if member.viewset is not None
                and getattr(member.viewset, "hub_url_name", None) != self.url_name
                and (
                    self.is_hub(member)
                    or getattr(member.viewset, "hub_url_name", None) is not None
                )
            ]
            if mispointed:
                names = ", ".join(
                    f"{member.key} (its viewset returns to "
                    f"{getattr(member.viewset, 'hub_url_name')!r})"
                    for member in mispointed
                )
                raise ImproperlyConfigured(
                    "A hub member's viewset must return to the hub that "
                    "lists it, or finishing the member deposits the user on "
                    f"a page that does not list it. Mispointed: {names}."
                )
        # A member on a different journey from its hub stashes into a record
        # the hub never reads — the same quiet failure as a drifted key, one
        # level up. Only a journey member declares a journey to drift from.
        astray = [
            member
            for member in members
            if hasattr(member.viewset, "journey")
            and (
                getattr(member.viewset, "journey") != self.journey
                or getattr(member.viewset, "journey_url_kwarg")
                != self.journey_url_kwarg
            )
        ]
        if astray:
            names = ", ".join(
                f"{member.key} (its viewset declares journey="
                f"{getattr(member.viewset, 'journey')!r}, journey_url_kwarg="
                f"{getattr(member.viewset, 'journey_url_kwarg')!r})"
                for member in astray
            )
            raise ImproperlyConfigured(
                "A hub member's viewset must be on the same journey as its "
                f"hub (journey={self.journey!r}, journey_url_kwarg="
                f"{self.journey_url_kwarg!r}), or it finishes into a record "
                f"the hub never reads. Astray: {names}."
            )
        return list(members)

    def get_member(self, key: str) -> Member:
        """The declared member `key` names, raising `MemberNotFound`
        otherwise."""
        for member in self._vetted_members():
            if member.key == key:
                return member
        raise MemberNotFound(key)

    def get_journey_url_kwargs(self) -> dict[str, Any]:
        """The journey segment this request came in through, as URL kwargs —
        empty for a hub mounted under none. What every member's own view is
        handed, so a member mounted under the same segment reads the same
        journey."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        if self.journey_url_kwarg in url_kwargs:
            return {self.journey_url_kwarg: url_kwargs[self.journey_url_kwarg]}
        return {}

    def member_url_kwargs(self, member: Member) -> dict[str, Any]:
        """The URL kwargs a member's own view is run and reversed with: the
        journey this hub is on, under the member's declared `url_kwargs`.

        The one rule for every use of a member — asking its `blocked()`,
        its `status`, a hub child's `status_for()`, reversing its page,
        beginning or resuming its run. The hub's *own* mount prefix is not
        forwarded by default (`get_page_url_kwargs()` is for the hub's own
        URLs): a member is mounted wherever it is mounted, and one under a
        tenant prefix says so in `Member.url_kwargs` — `get_members()` can
        read the prefix off `self.kwargs` and declare it per request.
        """
        return {**self.get_journey_url_kwargs(), **member.url_kwargs}

    def member_viewset(self, member: Member) -> type[WizardViewSet]:
        """The wizard behind a member, for the four places that run one.

        A member with no viewset supplies its own status, and a member that
        is a hub has no run; both are turned away at the door, so none of
        those four can be reached with either — see `_validate_members()`
        and `enter()`.
        """
        return cast("type[WizardViewSet]", member.viewset)

    # --- the page ----------------------------------------------------------

    def get_hub(self) -> Hub:
        """The whole page: its rows, and how far they have got between them."""
        rows = tuple(self.get_member_rows())
        status = self.get_hub_status(rows)
        return Hub(
            rows=rows,
            status=status,
            status_label=self.get_status_label(status),
        )

    def get_hub_status(self, rows: tuple[MemberRow, ...]) -> str:
        """How far the hub has got as a whole — every row complete, every row
        untouched, or anything in between.

        A hub listing nothing has not started: there is no member to have
        begun. A member the user cannot start yet does not make the page
        *incomplete* either — a fresh task list whose later members are
        locked has still not been begun — but it does keep the page off
        `COMPLETE` for as long as it is locked, which is why a member that
        will never unlock is one for `hidden()` rather than `blocked()`.

        Override for a domain where some members do not count towards the
        whole — an optional one, or one another answer made moot.
        """
        if rows and all(row.is_complete for row in rows):
            return COMPLETE
        if all(row.is_not_started or row.is_blocked for row in rows):
            return NOT_STARTED
        return INCOMPLETE

    def get_member_rows(self) -> list[MemberRow]:
        """One row per declared member, built once per request.

        Both halves of the page ask for them — the `Hub` counting them, and a
        collection wrapping the same list in a `Collection` — and a row is
        cheap but not free: two storage reads and a `reverse()` each, and a
        whole `Collection` build for a member that is one. Cached on the view
        instance Django builds per request, exactly as `_vetted_members()`
        is. Override `build_member_rows()` to change what is built.
        """
        if not hasattr(self, "_member_rows_cache"):
            self._member_rows_cache = self.build_member_rows()
        return self._member_rows_cache

    def build_member_rows(self) -> list[MemberRow]:
        store = self.get_journey_store()
        return [
            self.build_member_row(member, store) for member in self._vetted_members()
        ]

    def build_member_row(self, member: Member, store: JourneyStore) -> MemberRow:
        status = self.get_member_status(member, store)
        return MemberRow(
            member=member,
            status=status,
            title=self.get_member_title(member),
            status_label=self.get_status_label(status),
            url=self.get_member_url(member),
        )

    def get_member_status(self, member: Member, store: JourneyStore) -> str:
        """How far a member has got: `COMPLETE`, `INCOMPLETE`, or
        `NOT_STARTED`.

        Complete means the member ran to its own end — `done()` fired and
        stashed — because a stash under the member's key is the only thing
        that can only have come from finishing. Incomplete means a run is
        recorded for the member and holds at least one submission: the user
        went in and answered something. Everything else has not started,
        including a member the user opened and left without answering, and
        one whose run the storage has since forgotten (an expired session, an
        obliterated run). There is nothing to pick up, so the honest thing to
        say is that it has not begun.

        Two storage reads and no walk. Whether the stored answers still
        *validate* is deliberately not asked: that costs one form `clean()`
        per answered step per row, and the answer would not change the row —
        an answer that no longer validates leaves the member in progress just
        as surely as one that does.

        A member carrying its own `status` answers for itself and none of
        this runs. A member that is a hub answers for itself too, through
        `status_for()`: its completion is its rows', and no stash key could
        express it.

        `BLOCKED` outranks the storage reads below it, so a member whose
        prerequisite was withdrawn reports what the user can do rather than
        what they once did. That is the honest reading when the door is about
        to refuse them: a row saying **Complete** over a link that turns the
        user away is worse than one saying they cannot start yet.
        """
        if member.status is not None:
            return member.status(self.request, self.member_url_kwargs(member))
        if self.member_blocked(member, store):
            return BLOCKED
        if self.is_hub(member):
            hub = cast("type[HubMixin]", member.viewset)
            return hub.status_for(self.request, self.member_url_kwargs(member))
        if store.has_stash(self.full_key(member)):
            return COMPLETE
        if self.get_member_state(member, store):
            return INCOMPLETE
        return NOT_STARTED

    def member_blocked(self, member: Member, store: JourneyStore) -> bool:
        """Whether this member is visible but not open to the user yet.

        Asks the member itself — `RunMemberMixin.blocked()` on its own viewset
        — because that is where a rule about one member belongs, and a hub
        method taking a `member` is a method with a key in scope. Override
        here only for what a member cannot answer alone: a rule spanning
        rows, or a collection gating every item at once. An override replaces
        the question rather than joining it, so call `super()` where the
        members should still get their say.

        A member with no viewset is never blocked from here. It supplies its
        own `status` — which may be `BLOCKED` — and the door asks for that.
        """
        blocked = getattr(member.viewset, "blocked", None)
        return blocked is not None and blocked(self.request, member, store)

    def member_hidden(self, member: Member, store: JourneyStore) -> bool:
        """Whether this member should not be listed for this request.

        The exact mirror of `member_blocked()`: asks `RunMemberMixin.hidden()`
        on the member's own viewset, and is the hub's hook for what one
        member cannot answer alone — a collection hiding every item at once.
        A member with no viewset is never hidden from here; a hub that wants
        to hide one leaves it out of `get_members()`.
        """
        hidden = getattr(member.viewset, "hidden", None)
        return hidden is not None and hidden(self.request, member, store)

    def get_member_state(self, member: Member, store: JourneyStore) -> State:
        """The stored state of the member's recorded run — an empty list when
        it has none, or one the storage no longer holds.

        Read straight off the member's own `storage_class`, not through
        `WizardViewSet.inspect()`: the shape of the state is the whole
        question, and building a runtime to answer it would resolve the wizard
        and walk its tree to find out something the storage already knows.
        Public so a hub that wants a progress count can compute one from the
        raw entries — bearing in mind that they are positional against a tree
        whose shape may depend on a branch predicate nobody has evaluated.
        """
        run_id = store.get_run(self.full_key(member))
        if run_id is None:
            return []
        storage = self.member_viewset(member).storage_class(
            WizardContext.from_request(self.request)
        )
        try:
            return storage.get_state(run_id)
        except RunNotFound:
            return []

    def get_member_title(self, member: Member) -> StrOrPromise:
        """The heading for a member's row: its declared `title`, otherwise
        its key made readable."""
        if member.title is not None:
            return member.title
        return capfirst(member.key.replace("_", " ").replace("-", " "))

    def get_status_label(self, status: str) -> StrOrPromise:
        """The status as display text. Override for your own wording."""
        return {
            NOT_STARTED: gettext("Not started"),
            INCOMPLETE: gettext("Incomplete"),
            COMPLETE: gettext("Complete"),
            BLOCKED: gettext("Cannot start yet"),
        }[status]

    def get_member_url(self, member: Member) -> str:
        """Where a row's link goes: this hub's own entry URL for the member.

        Never the wizard's. A row cannot know which run to resume without
        walking it, and a link straight at the wizard would have to be either
        the start URL — which mints a second run beside the one the user is
        halfway through — or the bare run URL, which fires `done()` on a GET
        the moment every stored answer validates. The door is the one place
        that can afford to ask.

        The exceptions are the members that are not wizards. One that is a
        hub links straight at that hub's page, and one that declares its own
        `url_name` goes straight there: neither has a run to walk, so the
        door would have nothing to decide.
        """
        if self.is_hub(member):
            return reverse(
                cast(str, getattr(member.viewset, "url_name")),
                kwargs=self.member_url_kwargs(member),
            )
        if member.url_name is not None:
            return reverse(member.url_name, kwargs=self.member_url_kwargs(member))
        if self.member_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set member_url_name (or override get_member_url) on {name}."
            )
        return reverse(
            self.member_url_name,
            kwargs={
                **self.get_page_url_kwargs(),
                self.member_url_kwarg: member.key,
            },
        )

    def get_page_url_kwargs(self) -> dict[str, Any]:
        """URL kwargs the hub's mount prefix captured (e.g. a tenant slug),
        forwarded into every reverse of the hub's *own* URLs — its page and
        its doors — the same arrangement `WizardViewSet.get_url_kwargs()`
        makes. Everything the request captured except the member key the
        door itself owns. Not what a member is reversed with: that is
        `member_url_kwargs()`."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        return {
            key: value
            for key, value in url_kwargs.items()
            if key != self.member_url_kwarg
        }

    def get_page_url(self) -> str:
        """This hub's own page — where its doors, its refusals and a finished
        member all land. Not `get_hub_url()`, which on every member of a
        journey is the hub *above*."""
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_page_url) on {name}."
            )
        return reverse(self.url_name, kwargs=self.get_page_url_kwargs())

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        """The parent hub is reversed with this page's own mount-prefix
        kwargs — the journey among them — since the two share a mount."""
        return self.get_page_url_kwargs()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        if self.hub_context_name is not None:
            context[self.hub_context_name] = self.get_hub()
        return context

    # --- the door ----------------------------------------------------------

    def enter(self, member: Member) -> str | None:
        """The URL that puts the user inside this member, wherever it left
        off.

        Entering is dispatch, not display: it asks what exists rather than
        what the row rendered. Every arm ends at `entry_url()`, so no path
        here can emit a bare run URL.

        A member that is not a wizard has no run to enter, and its row links
        past the door anyway. For a hub, the door sends the user on to its
        page all the same — a typed door URL should land where the row would
        have. For a member with its own `url_name`, arriving here at all is
        a hand-typed or stale URL, and it is refused rather than guessed at.

        A member the user cannot start yet is refused the same way. This is
        the one place display and dispatch have to agree: the row rendered a
        link the user is not allowed to follow, and a stale link or a typed
        URL would otherwise start the run regardless. The status is asked for
        rather than the hook, so a `Member.status` that reports `BLOCKED`
        under its own steam is guarded too — two storage reads, against a walk
        this saves entirely.
        """
        if member.viewset is None:
            return None
        store = self.get_journey_store()
        if self.get_member_status(member, store) == BLOCKED:
            return None
        if self.is_hub(member):
            return self.get_member_url(member)
        # Resume before reopen. Reversed, a completed member under edit
        # would resurrect a second run on every click and the user's
        # in-flight edits would become unreachable.
        resumed = self.resume_member(member, store)
        if resumed is not None:
            return resumed.entry_url()
        try:
            reopened = self.reopen_member(member, store)
        except InvalidStash as error:
            return self.stash_unusable(member, error)
        if reopened is not None:
            store.set_run(self.full_key(member), reopened.run_id)
            return reopened.entry_url(member.reopen_step)
        started = self.start_member(member)
        store.set_run(self.full_key(member), started.run_id)
        return started.entry_url()

    def resume_member(self, member: Member, store: JourneyStore) -> BoundWizard | None:
        """The member's live run, or None when it has none.

        A recorded run is resumable only while storage still holds it and it
        has not been tombstoned. A completed run is *addressable* but not
        runnable — `retrieve_run` finds it, and `is_complete` is what tells
        the two apart, the same pair `WizardViewSet._retrieve_run` checks
        before it will serve a request. Sending the user into a tombstoned run
        would bounce every request back to the start URL with no error to
        explain it.
        """
        run_id = store.get_run(self.full_key(member))
        if run_id is None:
            return None
        try:
            bound_wizard = self.member_viewset(member).inspect(
                self.request, run_id, **self.member_url_kwargs(member)
            )
        except RunNotFound:
            return None
        if bound_wizard.is_complete:
            return None
        return bound_wizard

    def reopen_member(self, member: Member, store: JourneyStore) -> BoundWizard | None:
        """A fresh run seeded from the member's stash, or None with nothing
        stashed. The stash is read, never popped: re-opening keeps working,
        and re-completing overwrites it with the newer answers."""
        try:
            payload = store.get_stash(self.full_key(member))
        except StashNotFound:
            return None
        return self.member_viewset(member).reopen(
            self.request,
            payload,
            expected_label=self.stash_label(member),
            **self.member_url_kwargs(member),
        )

    def start_member(self, member: Member) -> BoundWizard:
        """A brand-new run for a member with nothing behind it."""
        return self.member_viewset(member).begin(
            self.request, **self.member_url_kwargs(member)
        )

    def stash_unusable(self, member: Member, error: InvalidStash) -> str | None:
        """What to do with a stash that cannot seed a run — a payload whose
        label no longer matches, which almost always means a deploy reshaped
        this member and bumped it.

        Re-raises by default: a silent fresh start would look to the user
        exactly like their answers vanishing. Override to start over (delete
        the stash and `enter()` again), or to return a URL that explains.
        """
        raise error

    def member_unavailable(self, key: str) -> HttpResponse:
        """Response for a member this hub will not open — a key it declares
        nothing for (a stale link, a renamed member), or one the user cannot
        start yet.

        The default sends the user back to the hub itself, which is the right
        landing for both: the page they came from says why, either by not
        listing the member or by rendering it **Cannot start yet**. Override
        to raise `Http404`.
        """
        return redirect(self.get_page_url())

    # --- the journey -------------------------------------------------------

    def submit(self) -> HttpResponseBase:
        """Finish this hub, once every member has.

        The counterpart of `RunMemberMixin.done()` one level up, with the same
        ordering: the application's work first, the bookkeeping after. If
        the hub is not complete the submit is refused (`hub_incomplete()`),
        so a stale button or a hand-made POST cannot submit half a journey.

        A nested hub finishes into the hub above it: `hub_done()` does what
        the application needs and sends the user back up, and nothing is torn
        down — the parent reads this hub's completion off the same rows.

        A root hub finishes the journey: `journey_done()` does what submitting
        *means* — files the application, raises the claim — and only once it
        has returned is the journey tombstoned, so a `journey_done()` that
        raises leaves every member resumable rather than a journey that is
        neither submitted nor editable. It runs inside the window where the
        stashes are still readable, exactly as `run_done()` runs before
        the run is torn down. Anything it needs to keep for the done page goes
        in `store.data`, which the tombstone keeps.
        """
        hub = self.get_hub()
        if not hub.is_complete:
            return self.hub_incomplete(hub)
        store = self.get_journey_store()
        if self.is_nested:
            return self.hub_done(hub, store)
        response = self.journey_done(hub, store)
        store.complete()
        return response

    def hub_done(self, hub: Hub, store: JourneyStore) -> HttpResponseBase:
        """What a nested hub does when it is submitted, and the response the
        user sees after. The default sends them up to the hub that lists this
        one, which is where a task list expects a finished task to deposit
        them; override for work that runs once per submit of this part."""
        return redirect(self.get_hub_url())

    def journey_done(self, hub: Hub, store: JourneyStore) -> HttpResponseBase:
        """What submitting this journey does, and the response the user sees
        after. There is no default: a journey with nothing to do when it is
        submitted is a hub with no reason to have a submit.

            def journey_done(self, hub, store):
                application = file_application(
                    self.request.user,
                    contact=store.get_stash("contact"),
                    employment=store.get_stash("employment"),
                )
                store.data["application_ref"] = application.reference
                return redirect("apply-done", journey=self.get_journey())
        """
        name = self.__class__.__name__
        raise ImproperlyConfigured(
            f"{name} has nothing to do when its journey is submitted. Override "
            f"{name}.journey_done() to do the work and return the response."
        )

    def hub_incomplete(self, hub: Hub) -> HttpResponseBase:
        """Response for a submit that arrived before every member was
        complete. The default sends the user back to the hub, which shows
        them what is left; override to render the page with an error."""
        return redirect(self.get_page_url())

    def journey_completed(self, store: JourneyStore) -> HttpResponseBase:
        """Response for a request that reaches this hub after its journey
        was submitted — the page and the door alike.

        A nested hub sends the user up to the hub above, whose own
        `journey_completed()` says what a submitted journey looks like. A root
        hub answers `Http404` by default, because the library cannot know.
        Override to render a done page from what the tombstone kept:

            def journey_completed(self, store):
                return render(self.request, "apply/done.html", {
                    "reference": store.data["application_ref"],
                })
        """
        if self.is_nested:
            return super().journey_completed(store)
        raise Http404(f"Journey {self.get_journey()!r} has been submitted.")


class HubView(HubMixin, TemplateView):
    """A hub page and the door into each of its members.

    One view over two routes, for the same reason a wizard is one view over
    three: the door has to make the decision the page cannot afford to. A row
    renders without walking anything, so it cannot know which run its link
    should resume; the door walks exactly the one member the user clicked and
    redirects to a step URL.

        class ProfileHubView(HubView):
            template_name = "profile/hub.html"
            url_name = "profile-hub"
            member_url_name = "profile-hub-member"
            members = [
                Member("contact", ContactMemberViewSet, title="Contact details"),
                Member("address", AddressMemberViewSet, title="Address"),
            ]

    Mount it exactly like a wizard:

        path("profile/", include(ProfileHubView.urls()))
    """

    @classmethod
    def urls(cls) -> list[URLPattern]:
        """URL patterns for this hub, derived from `url_name`: `<url_name>`
        (the page) and `<url_name>-member` (the door into one member)."""
        if cls.url_name is None:
            raise ImproperlyConfigured("HubView.urls() requires url_name to be set.")
        view = cls.as_view()
        return [
            path("", view, name=cls.url_name),
            path(
                f"<slug:{cls.member_url_kwarg}>/",
                view,
                name=f"{cls.url_name}-member",
            ),
        ]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """A POST to the page submits the journey. The door is GET-only: the
        route that opens a member never destroys or finishes anything."""
        if kwargs.get(self.member_url_kwarg) is not None:
            return HttpResponseNotAllowed(["GET"])
        return self.submit()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        key = kwargs.get(self.member_url_kwarg)
        if key is None:
            return super().get(request, *args, **kwargs)
        try:
            member = self.get_member(key)
        except MemberNotFound:
            return self.member_unavailable(key)
        url = self.enter(member)
        if url is None:
            # Nowhere to send them — a member that is not a wizard, one the
            # user cannot start yet, or a `stash_unusable()` that declined to
            # name a destination.
            return self.member_unavailable(key)
        return redirect(url)
