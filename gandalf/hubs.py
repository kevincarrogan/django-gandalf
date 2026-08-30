"""Hub and spoke: a page of parallel wizards the user drops in and out of.

A hub is declared the way a wizard is — one immutable value, read top-down —
and mounted once:

    application = (
        Hub()
        .member("contact", contact, title="Contact details", reopen="review")
        .member("project", project, title="Project", done=record_amount)
        .collection("budget", budget_line, title="Budget", min_items=1)
        .member("match_funding", match_funding, title="Match funding",
                hidden=lambda store: store.data.get("amount", 0) <= 10_000)
        .hub("supporting", supporting, title="Supporting information")
    )

    class GrantApplicationViewSet(HubViewSet):
        url_name = "apply"
        template_name = "apply/hub.html"
        hub = application

        def journey_done(self, hub, store): ...

    urlpatterns = [path("apply/<slug:journey>/", include(GrantApplicationViewSet.urls()))]

The page asks the same three questions of every member — what is it
called, how far has it got, and where does its link go — and `HubViewSet`
answers them once. The template gets a `hub`: one `MemberRow` per member,
carrying its title, its status, and one URL that does the right thing
whichever state it is in, wrapped in a `HubPage` that says how far the whole
page has got.

A member is *complete* when it ran to its own end and its answers were
stashed. That is the only definition the hub has, and it is deliberately the
cheap one: a row costs two storage reads and a `reverse()`, never a walk.
Finding out where a half-finished run actually is does cost a walk, so it
happens once, on the way in, for the one member the user clicked.

`HubViewSet` owns the URL tree beneath it. Every member is mounted under
the hub — `contact/` opens the contact member *through the hub*, so there
is no bare run URL to link by mistake, and a nested hub's members are keyed
under its prefix (`"supporting:referees"`) without anyone typing it. What
used to be declared twice and checked for drift is now declared once.

Every decision the page makes is still a hook: `get_members()` chooses the
members, `get_member_status()` decides how far one has got,
`get_hub_status()` how far they have got between them, `get_member_title()`
names it, `get_member_url()` says where its link goes, and
`resume_member()` / `reopen_member()` / `start_member()` each own one way
into a run. A nested hub is a subclass of the root, so an override on the
root applies to the whole tree.

The members add up to a *journey* — the application, the claim, the profile
— and everything a hub keeps is scoped to one: the store is built with the
journey's identity, which a hub reads off a URL kwarg or declares. The
root hub owns the journey's ending: `submit()` runs `journey_done()` and
tombstones the record, after which every way back in is refused.
"""

from __future__ import annotations

import re
import uuid
from abc import abstractmethod
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, Callable, cast

from django.core.exceptions import ImproperlyConfigured
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.urls import NoReverseMatch, URLPattern, URLResolver, include, path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.views.generic import TemplateView

from gandalf.context import WizardContext
from gandalf.runtime import BoundWizard, InvalidStash
from gandalf.storage import (
    RunNotFound,
    SessionCollectionStore,
    SessionStorage,
    StashNotFound,
)
from gandalf.types import JourneyStore, State, StorageClass, StrOrPromise
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import ConfiguredWizard, Wizard

if TYPE_CHECKING:
    from gandalf.collections import Collection

__all__ = [
    "BLOCKED",
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "Hub",
    "HubPage",
    "HubViewSet",
    "Journey",
    "JourneyScoped",
    "Member",
    "MemberDeclaration",
    "MemberNotFound",
    "MemberRow",
    "MemberViewSet",
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


#: A gate: one read of the journey's store, answering whether a member is
#: blocked (listed but locked) or hidden (not listed at all). Handed the
#: store and nothing else, so it stays the read a row can afford — see
#: `HubViewSet.member_blocked()` for the hub-side hook that has the request.
Rule = Callable[[JourneyStore], bool]
#: What a member does when it finishes, beyond being recorded: handed the
#: store and the finished run while the run is still readable. Where an
#: answer the rest of the journey turns on is written to `store.data`.
Done = Callable[[JourneyStore, BoundWizard], Any]
#: A wizard member is declared by its `Wizard`, or by a `WizardViewSet`
#: subclass when the member needs a hook a declaration cannot carry
#: (`run_started`, a per-request `get_wizard()`).
WizardLike = Wizard | ConfiguredWizard | type[WizardViewSet]


# --- the declaration ---------------------------------------------------------


@dataclass(frozen=True)
class MemberDeclaration:
    """One row of a `Hub` declaration, as the builder recorded it. Read by
    `HubViewSet` when it materialises the hub into viewsets and members."""

    kind: str
    key: str
    title: StrOrPromise | None = None
    wizard: WizardLike | None = None
    hub: Hub | None = None
    collection: Collection | None = None
    reopen: str | None = None
    label: str | None = None
    done: Done | None = None
    blocked: Rule | None = None
    hidden: Rule | None = None
    # A link's extras: where it goes, and what decides its status.
    url_name: str | None = None
    status: Callable[[HttpRequest, dict[str, Any]], str] | None = None


class Hub:
    """An immutable declaration of a task list: which members it has, in
    what order, and what each one is. Every method returns a new `Hub`, so
    a declaration can be shared, extended and nested without side effects.

    `configure()` carries the page-level settings a declaration needs when
    it is nested and has no viewset of its own: `template_name` for the
    page, and `member_template_name`, the template its wizard members
    render with unless their `Wizard` carries one of its own.
    """

    def __init__(
        self,
        *,
        members: tuple[MemberDeclaration, ...] = (),
        configuration: dict[str, Any] | None = None,
    ) -> None:
        self.members = members
        self.configuration = dict(configuration or {})

    def _with(self, declaration: MemberDeclaration) -> Hub:
        if any(member.key == declaration.key for member in self.members):
            raise ImproperlyConfigured(
                "Hub member keys must be unique; a key has to name exactly "
                f"one member. Duplicated: {declaration.key}."
            )
        return self.__class__(
            members=(*self.members, declaration), configuration=self.configuration
        )

    def member(
        self,
        key: str,
        wizard: WizardLike,
        /,
        *,
        title: StrOrPromise | None = None,
        reopen: str | None = None,
        done: Done | None = None,
        blocked: Rule | None = None,
        hidden: Rule | None = None,
        label: str | None = None,
    ) -> Hub:
        """A wizard the user finishes on its own and can come back to.

        `key` is the member's identity: the stash key its finished answers
        live under and the URL segment it is mounted at. `title` is what the
        row renders; without one the key is made readable. `reopen` names
        the step a completed member re-opens at — a review step, so the
        user lands on their answers rather than at step one. `done` runs
        once per finish. `blocked` and `hidden` are the two gates; `label`
        is the stash's shape-identity, bumped when a deploy reshapes the
        wizard so an old payload is refused rather than walked.
        """
        return self._with(
            MemberDeclaration(
                "wizard",
                key,
                title=title,
                wizard=wizard,
                reopen=reopen,
                done=done,
                blocked=blocked,
                hidden=hidden,
                label=label,
            )
        )

    def collection(
        self,
        key: str,
        collection: Collection | WizardLike,
        /,
        *,
        title: StrOrPromise | None = None,
        blocked: Rule | None = None,
        hidden: Rule | None = None,
        **options: Any,
    ) -> Hub:
        """An "add another" list. Pass a `Collection`, or a wizard and the
        `Collection` keyword arguments to build one from."""
        from gandalf.collections import Collection

        if not isinstance(collection, Collection):
            collection = Collection(collection, **options)
        elif options:
            raise ImproperlyConfigured(
                "Pass a Collection or a wizard with its options, not both: "
                f"{', '.join(sorted(options))} cannot be applied to a Collection."
            )
        return self._with(
            MemberDeclaration(
                "collection",
                key,
                title=title,
                collection=collection,
                blocked=blocked,
                hidden=hidden,
            )
        )

    def hub(
        self,
        key: str,
        hub: Hub,
        /,
        *,
        title: StrOrPromise | None = None,
        blocked: Rule | None = None,
        hidden: Rule | None = None,
    ) -> Hub:
        """A task list within this one. Its members are keyed under `key`
        in the same journey record, its row here reads its own rows'
        status, and its submit returns here rather than ending anything."""
        return self._with(
            MemberDeclaration(
                "hub", key, title=title, hub=hub, blocked=blocked, hidden=hidden
            )
        )

    def link(
        self,
        key: str,
        url_name: str,
        /,
        *,
        title: StrOrPromise | None = None,
        status: Callable[[HttpRequest, dict[str, Any]], str] | None = None,
    ) -> Hub:
        """A row that links somewhere the hub does not run — a payment page,
        a page in another app. `status` decides what the row says of it,
        called with the request and the URL kwargs the hub would hand the
        member's own view; without one the row has no status to derive, so
        both are required."""
        if status is None:
            raise ImproperlyConfigured(
                f"A link needs a status: the hub cannot derive one for {key!r} "
                "from a stash nothing writes. Pass status=."
            )
        return self._with(
            MemberDeclaration(
                "link", key, title=title, url_name=url_name, status=status
            )
        )

    def configure(self, **configuration: Any) -> Hub:
        """Page settings for a hub with no viewset of its own — a nested
        one: `template_name`, and `member_template_name` for its wizards."""
        return self.__class__(
            members=self.members, configuration={**self.configuration, **configuration}
        )


# --- what the page renders ---------------------------------------------------


@dataclass(frozen=True)
class Member:
    """One spoke of a hub, as materialised from its declaration: something
    the user can enter, leave, and come back to.

    `key` is the member's identity relative to the hub that lists it; the
    store sees it under the hub's prefix (`HubViewSet.full_key()`).
    `viewset` runs it — a `MemberViewSet` for a wizard, a `HubViewSet` for
    a task list or a collection. `label` is the stash's shape-identity,
    defaulting to the full key. `reopen_step` names where a completed
    member re-opens. `url_kwargs` are extra URL kwargs this member's own
    URLs take beyond the page's — an item's id. A member with no viewset is
    a link: `url_name` says where, `status` says how far.
    """

    key: str
    viewset: type[WizardViewSet] | type[HubViewSet] | None = None
    title: StrOrPromise | None = None
    label: str | None = None
    reopen_step: str | None = None
    # Excluded from comparison so a mutable default cannot make a frozen
    # member unhashable — the same escape `SummaryField.bound_field` takes.
    url_kwargs: dict[str, Any] = dataclass_field(default_factory=dict, compare=False)
    url_name: str | None = None
    status: Callable[[HttpRequest, dict[str, Any]], str] | None = dataclass_field(
        default=None, compare=False
    )
    blocked: Rule | None = dataclass_field(default=None, compare=False)
    hidden: Rule | None = dataclass_field(default=None, compare=False)


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
class HubPage:
    """The hub as rendered: its rows, and how far the whole page has got.
    What a task list's heading and its final submit button both read.

    The counts are the reason this exists. "You have completed 2 of 5
    sections" is the task list pattern, and deriving it in the view means
    asking for the rows a second time. `rows` is built once and counted
    here.
    """

    rows: tuple[MemberRow, ...]
    status: str
    status_label: StrOrPromise

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def completed(self) -> int:
        return sum(1 for row in self.rows if row.is_complete)

    @property
    def remaining(self) -> int:
        """How many have not — a member the user cannot start yet included,
        since it is still work the journey is waiting on."""
        return self.count - self.completed

    @property
    def blocked(self) -> int:
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


# --- being on a journey --------------------------------------------------------


class JourneyScoped:
    """What a member's run and a hub have in common: being on a journey.

    A journey is one record — `journey_store_class(context, journey)` — and
    every member reads the same one, so a member nested two hubs down still
    reads `store.data` written at the top. Nesting is a key namespace, not a
    second store: a hub with a `member_key` prefixes it onto every member it
    lists.
    """

    request: HttpRequest
    kwargs: dict[str, Any]

    #: The key this member finishes under in the journey's store — the full
    #: key, prefix included. `None` for a hub nothing lists.
    member_key: str | None = None
    #: The hub finishing returns to — the parent's `url_name`. `None` for a
    #: root hub.
    hub_url_name: str | None = None
    #: One store class for the whole tree. The collection store is the
    #: journey store plus an item registry, so it serves a hub with no
    #: collections just as well, and one class means every member of the
    #: tree reads the same record.
    journey_store_class: type[Any] = SessionCollectionStore
    #: Which journey this member belongs to. Read off the URL when mounted
    #: under a `<journey>` segment (`journey_url_kwarg`), otherwise this fixed
    #: one — a hub that lists one journey per session.
    journey: str = "default"
    journey_url_kwarg = "journey"
    #: What joins a hub's prefix to a member's key — and a collection's key
    #: to an item's id.
    key_separator = ":"

    def compose_key(self, prefix: str, key: str) -> str:
        return f"{prefix}{self.key_separator}{key}"

    @property
    def is_nested(self) -> bool:
        """Whether something above lists this — the difference between a
        submit that ends the journey and one that returns to the parent."""
        return self.hub_url_name is not None

    def get_journey(self) -> str:
        url_kwargs = getattr(self, "kwargs", None) or {}
        return str(url_kwargs.get(self.journey_url_kwarg, self.journey))

    def get_journey_store(self) -> JourneyStore:
        return cast(
            JourneyStore,
            self.journey_store_class(
                WizardContext.from_request(self.request), self.get_journey()
            ),
        )

    def get_hub_url(self) -> str:
        """Where finishing sends the user back to: the hub above, under the
        URL kwargs `get_hub_url_kwargs()` supplies."""
        if self.hub_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set hub_url_name (or override get_hub_url) on {name}."
            )
        return reverse(self.hub_url_name, kwargs=self.get_hub_url_kwargs())

    @abstractmethod
    def get_hub_url_kwargs(self) -> dict[str, Any]:
        """The URL kwargs the hub above is reversed with."""

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Refuse every request once the journey has been submitted.

        A tombstone has no runs and no stashes, so a hub rendering it would
        show every member as not started, and a member re-opened after
        submission would stash into it. One store read per request buys the
        guarantee that a submitted journey can never be answered again. A
        nested hub or a member sends the user up; only the root says what a
        submitted journey looks like.
        """
        store = self.get_journey_store()
        if store.is_complete():
            if self.is_nested:
                return redirect(self.get_hub_url())
            return self.submitted(store)
        return cast(HttpResponseBase, super().dispatch(request, *args, **kwargs))  # type: ignore[misc]

    def submitted(self, store: JourneyStore) -> HttpResponseBase:
        """The page for a journey that has been submitted — what any request
        reaching the root after the tombstone gets. `Http404` until the app
        says what a submitted journey looks like; `store.data` is what the
        tombstone kept."""
        raise Http404(f"Journey {self.get_journey()!r} has been submitted.")

    @classmethod
    def blocked(cls, store: JourneyStore) -> bool:
        """Whether this member is listed but not open to the user yet — the
        row reads *Cannot start yet* and the door refuses it. One read of
        the journey's store; `False` by default. A classmethod because the
        hub asks before any instance exists, exactly as it asks `begin()`
        and `inspect()`: the point of the question is that there must not
        be a run."""
        return False

    @classmethod
    def hidden(cls, store: JourneyStore) -> bool:
        """Whether this member should not be listed for this request at all
        — not in the rows, not in the counts, its door refusing a stale
        link. One read of the store; `False` by default."""
        return False


class MemberViewSet(JourneyScoped, WizardViewSet):
    """The viewset a hub runs a wizard member with. Built by `HubViewSet`
    from the member's declaration — one subclass per member, carrying its
    key, its hub, its wizard and its `done` — and never written by hand.

    Re-opening a completed member and fixing one answer walks to the end
    and fires `done()` again. That is the intended "edit and re-save"
    semantics, which is why the bookkeeping here is idempotent and the
    declared `done` is what runs once per edit.
    """

    hub_viewset: type[HubViewSet] | None = None
    member_label: str | None = None
    member_done: Done | None = None

    def get_member_key(self) -> str:
        if self.member_key is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no member to register as finished: its member_key "
                "is unset."
            )
        return self.member_key

    def get_member_label(self) -> str:
        """The label stamped into this member's stash — the declared label,
        otherwise the key."""
        if self.member_label is None:
            return self.default_member_label()
        return self.member_label

    def default_member_label(self) -> str:
        return self.get_member_key()

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        return self.get_url_kwargs()

    def submitted(self, store: JourneyStore) -> HttpResponseBase:
        return redirect(self.get_hub_url())

    def done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        """Record the member as finished, then hand off to `run_done()`.

        The stash is taken first because it can only be taken at all while
        the run's state is readable — completion tears that down after
        `done()` returns. The run id is cleared after `run_done()` returns:
        a `done` that raises leaves the member resumable rather than
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
        """The library's own bookkeeping alongside the stash, inside the
        window where the run's answers are still readable. A plain member
        records nothing; an item caches its title."""

    def run_done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        """What this member does when it finishes, beyond being recorded:
        the declared `done`, then back to the hub."""
        if self.member_done is not None:
            self.member_done(self.get_journey_store(), bound_wizard)
        return redirect(self.get_hub_url())


# --- the page ----------------------------------------------------------------


def _class_name(key: str, suffix: str) -> str:
    words = re.split(r"[^0-9a-zA-Z]+", key)
    return "".join(word.capitalize() for word in words if word) + suffix


class HubViewSet(JourneyScoped, TemplateView):
    """The page listing a `Hub`'s members, and the door into each.

    Set `hub` and `url_name`. The members, their viewsets, their keys, their
    return URLs and the whole URL tree beneath the page are derived from
    the declaration when the class is created. A nested hub in the
    declaration becomes a subclass of *this* class, so an override here —
    a status label, a title rule, `stash_unusable()` — applies to the whole
    tree. `journey_done()` and `submitted()` are the root's alone.

    `storage_class` and `journey_store_class` set here reach every member.
    """

    hub: Hub | None = None
    #: Which attribute carries the declaration, for the error that says it
    #: is missing.
    declaration_name = "hub"
    #: The run storage every wizard member of this tree uses.
    storage_class: StorageClass = SessionStorage
    #: The base every collection in this tree is built on; `None` means
    #: `gandalf.collections.CollectionViewSet`. Set a subclass to give the
    #: tree's collections a hook — `item_removed()`, say.
    collection_viewset_class: type[Any] | None = None
    #: The template this hub's wizard members render with when their
    #: `Wizard` carries none of its own.
    member_template_name: str | None = None
    members: list[Member] = []
    #: Where the `HubPage` lands in the template context. `None` publishes
    #: nothing, for a page with a context object of its own — a collection.
    hub_context_name: str | None = "hub"
    member_url_name: str | None = None
    member_url_kwarg = "member"
    url_name: str | None = None
    #: `(url segment, patterns)` per member mounted beneath the page.
    _routes: list[tuple[str, list[URLPattern | URLResolver]]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.declaration() is not None and cls.url_name is not None:
            cls.materialise()

    @classmethod
    def declaration(cls) -> Hub | None:
        return cls.hub

    # --- from declaration to classes --------------------------------------

    @classmethod
    def materialise(cls) -> None:
        """Build the members and the viewsets that run them.

        Runs when a subclass with a declaration and a `url_name` is
        created — a root written by the app, or a nested hub generated
        here — and again on any further subclass, so a subclass that swaps
        `storage_class` or `journey_store_class` gets members on the same
        stores.
        """
        hub = cls.declaration()
        assert hub is not None
        cls.member_url_name = f"{cls.url_name}-member"
        cls.member_template_name = hub.configuration.get(
            "member_template_name", cls.member_template_name
        )
        members: list[Member] = []
        routes: list[tuple[str, list[URLPattern | URLResolver]]] = []
        for declaration in hub.members:
            member, patterns = cls.materialise_member(declaration)
            members.append(member)
            if patterns is not None:
                routes.append((declaration.key, patterns))
        cls.members = members
        cls._routes = routes

    @classmethod
    def materialise_member(
        cls, declaration: MemberDeclaration
    ) -> tuple[Member, list[URLPattern | URLResolver] | None]:
        key = declaration.key
        prefix = cls.member_key
        full_key = key if prefix is None else f"{prefix}{cls.key_separator}{key}"
        url_name = f"{cls.url_name}-{key}"
        if declaration.kind == "link":
            member = Member(
                key,
                title=declaration.title,
                url_name=declaration.url_name,
                status=declaration.status,
            )
            return member, None
        viewset: type[Any]
        patterns: list[URLPattern | URLResolver]
        if declaration.kind == "hub":
            viewset = cls.build_nested_hub(declaration, full_key, url_name)
            patterns = viewset.urls()
        elif declaration.kind == "collection":
            viewset = cls.build_collection(declaration, full_key, url_name)
            patterns = viewset.urls()
        else:
            viewset = cls.build_member_viewset(declaration, full_key, url_name)
            patterns = cls.door_first(key, viewset.urls())
        member = Member(
            key,
            viewset,
            title=declaration.title,
            reopen_step=declaration.reopen,
            label=declaration.label,
            blocked=declaration.blocked,
            hidden=declaration.hidden,
        )
        return member, patterns

    @classmethod
    def scoped_attrs(cls, url_name: str) -> dict[str, Any]:
        """What every generated viewset of this tree shares: its URL name,
        the hub it returns to, and the journey and stores it is on."""
        return {
            "__module__": cls.__module__,
            "url_name": url_name,
            "hub_url_name": cls.url_name,
            "hub_viewset": cls,
            "journey": cls.journey,
            "journey_url_kwarg": cls.journey_url_kwarg,
            "journey_store_class": cls.journey_store_class,
            "storage_class": cls.storage_class,
        }

    @classmethod
    def wizard_bases(cls, wizard: WizardLike | None, base: type) -> tuple[type, ...]:
        declared = wizard if isinstance(wizard, type) else None
        if declared is None:
            return (base,)
        if issubclass(declared, base):
            return (declared,)
        return (base, declared)

    @classmethod
    def wizard_attrs(
        cls, wizard: WizardLike | None, bases: tuple[type, ...]
    ) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if not isinstance(wizard, type):
            attrs["wizard"] = wizard
        if cls.member_template_name is not None and all(
            getattr(base, "template_name", None) is None for base in bases
        ):
            attrs["template_name"] = cls.member_template_name
        return attrs

    @classmethod
    def build_member_viewset(
        cls, declaration: MemberDeclaration, full_key: str, url_name: str
    ) -> type[MemberViewSet]:
        bases = cls.wizard_bases(declaration.wizard, MemberViewSet)
        attrs = {
            **cls.scoped_attrs(url_name),
            **cls.wizard_attrs(declaration.wizard, bases),
            "member_key": full_key,
            "member_label": declaration.label,
            "member_done": staticmethod(declaration.done)
            if declaration.done is not None
            else None,
        }
        return type(_class_name(declaration.key, "MemberViewSet"), bases, attrs)

    @classmethod
    def build_collection(
        cls, declaration: MemberDeclaration, full_key: str, url_name: str
    ) -> type[Any]:
        from gandalf.collections import CollectionViewSet

        attrs = {
            **cls.scoped_attrs(url_name),
            "collection": declaration.collection,
            "member_key": full_key,
            "member_template_name": cls.member_template_name,
        }
        base = cls.collection_viewset_class or CollectionViewSet
        return type(_class_name(declaration.key, "CollectionViewSet"), (base,), attrs)

    @classmethod
    def build_nested_hub(
        cls, declaration: MemberDeclaration, full_key: str, url_name: str
    ) -> type[HubViewSet]:
        hub = declaration.hub
        assert hub is not None
        attrs = {
            **cls.scoped_attrs(url_name),
            "hub": hub,
            "member_key": full_key,
            "member_template_name": cls.member_template_name,
            "template_name": hub.configuration.get("template_name", cls.template_name),
        }
        return type(_class_name(declaration.key, "HubViewSet"), (cls,), attrs)

    @classmethod
    def door_first(
        cls, key: str, patterns: list[URLPattern]
    ) -> list[URLPattern | URLResolver]:
        """A wizard member's routes with its bare start URL replaced by the
        hub's door for it. A run whose every answer validates completes on
        a GET, so the one URL that must never be linked is the one a
        `WizardViewSet` publishes first; here it opens the member through
        the hub instead, under the wizard's own URL name."""
        start, *rest = patterns
        door = path(
            "", cls.as_view(), kwargs={cls.member_url_kwarg: key}, name=start.name
        )
        return [door, *rest]

    @classmethod
    def urls(cls) -> list[URLPattern | URLResolver]:
        """The page, every member beneath it, and the door. The door comes
        last so a member's own segment — a nested hub's page, a collection's
        — is reached directly."""
        if cls.url_name is None:
            raise ImproperlyConfigured(
                f"{cls.__name__}.urls() requires url_name to be set."
            )
        view = cls.as_view()
        patterns: list[URLPattern | URLResolver] = [path("", view, name=cls.url_name)]
        for key, routes in cls._routes:
            patterns.append(path(f"{key}/", include(routes)))
        patterns.append(
            path(f"<slug:{cls.member_url_kwarg}>/", view, name=f"{cls.url_name}-member")
        )
        return patterns

    @classmethod
    def begin(
        cls, request: HttpRequest, journey: str | None = None, **url_kwargs: Any
    ) -> Journey:
        """Begin a journey on this hub and hand back a `Journey`: its id,
        its store, its page's URL, and `finish()` for recording a run as
        one of the sections — the whole of what a start wizard needs:

            def done(self, bound_wizard):
                journey = GrantApplication.begin(self.request)
                journey.finish("setup", bound_wizard)
                return redirect(journey.url)

        Nothing about it needs a wizard: an "apply again" link, a command
        or an agent begins one the same way. `journey` is made up when not
        given; `url_kwargs` are the page's mount-prefix kwargs, if any.
        """
        return Journey(cls, request, journey or uuid.uuid4().hex, url_kwargs)

    @classmethod
    def viewset_for(cls, key: str) -> type[Any]:
        """The generated viewset behind one member, for a test or a driver
        that needs to address it directly."""
        for member in cls.members:
            if member.key == key and member.viewset is not None:
                return member.viewset
        raise MemberNotFound(key)

    # --- this hub's place on the journey ------------------------------------

    def get_member_key(self) -> str | None:
        """The prefix this hub keys its members under, or `None` at the root."""
        return self.member_key

    def full_key(self, member: Member) -> str:
        """A member's key in the journey's store: its own key, prefixed by
        this hub's when this hub is nested. The one place nesting is spelled
        out."""
        prefix = self.get_member_key()
        if prefix is None:
            return member.key
        return self.compose_key(prefix, member.key)

    def stash_label(self, member: Member) -> str:
        """The label a member's stash is expected to carry: its declared
        `label`, otherwise its full key."""
        return self.full_key(member) if member.label is None else member.label

    @classmethod
    def status_for(cls, request: HttpRequest, url_kwargs: dict[str, Any]) -> str:
        """This hub's status as a row on the hub above it — its own rows',
        read off the same record. Costs this hub's rows' storage reads, and
        still no walk."""
        view = cls()
        view.setup(request, **url_kwargs)
        return view.get_hub().status

    @staticmethod
    def is_hub(member: Member) -> bool:
        return member.viewset is not None and issubclass(member.viewset, HubViewSet)

    # --- the members this hub lists -----------------------------------------

    def get_declaration(self) -> Any:
        """The declaration this page was built from, or the error that says
        there is none."""
        declaration = self.declaration()
        if declaration is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no members to list. Set {name}.{self.declaration_name} "
                f"to a {self.declaration_name.capitalize()}() declaration, or "
                f"override {name}.get_members()."
            )
        return declaration

    def get_members(self) -> list[Member]:
        """The members this hub lists, in the order they are shown. Override
        to choose among them per request — by user, by plan, by flag."""
        self.get_declaration()
        return list(self.members)

    def _vetted_members(self) -> list[Member]:
        """`get_members()` minus the members hidden for this request, once
        per request. Hiding here is what makes a hidden member *gone*: not
        in the rows, not in the counts, and unknown to the door."""
        if not hasattr(self, "_members_cache"):
            store = self.get_journey_store()
            self._members_cache = [
                member
                for member in self.get_members()
                if not self.member_hidden(member, store)
            ]
        return self._members_cache

    def get_member(self, key: str) -> Member:
        for member in self._vetted_members():
            if member.key == key:
                return member
        raise MemberNotFound(key)

    def member_url_kwargs(self, member: Member) -> dict[str, Any]:
        """The URL kwargs a member's own URLs take: the page's — its mount
        prefix and its journey — plus the member's own."""
        return {**self.get_page_url_kwargs(), **member.url_kwargs}

    def member_viewset(self, member: Member) -> type[WizardViewSet]:
        return cast("type[WizardViewSet]", member.viewset)

    # --- the page -------------------------------------------------------------

    def get_hub(self) -> HubPage:
        rows = tuple(self.get_member_rows())
        status = self.get_hub_status(rows)
        return HubPage(
            rows=rows, status=status, status_label=self.get_status_label(status)
        )

    def get_hub_status(self, rows: tuple[MemberRow, ...]) -> str:
        """Complete when every row is; not started when none has been
        touched (a locked row counts as untouched); incomplete between."""
        if rows and all(row.is_complete for row in rows):
            return COMPLETE
        if all(row.is_not_started or row.is_blocked for row in rows):
            return NOT_STARTED
        return INCOMPLETE

    def get_member_rows(self) -> list[MemberRow]:
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
        """In precedence order: a link's own status; blocked; a nested hub's
        rows; a stash (complete); a run (incomplete); nothing (not started).
        Blocked outranks a stash so a member whose prerequisite was withdrawn
        after it was answered reports what the user can do now."""
        if member.status is not None:
            return member.status(self.request, self.member_url_kwargs(member))
        if self.member_blocked(member, store):
            return BLOCKED
        if self.is_hub(member):
            hub = cast("type[HubViewSet]", member.viewset)
            return hub.status_for(self.request, self.member_url_kwargs(member))
        if store.has_stash(self.full_key(member)):
            return COMPLETE
        if self.get_member_state(member, store):
            return INCOMPLETE
        return NOT_STARTED

    def member_blocked(self, member: Member, store: JourneyStore) -> bool:
        """Whether the user cannot start this member yet: the member's own
        `blocked` rule, or its viewset's `blocked()`. Override for a rule
        spanning rows, or one that needs the request."""
        if member.blocked is not None and member.blocked(store):
            return True
        gate = getattr(member.viewset, "blocked", None)
        return gate is not None and bool(gate(store))

    def member_hidden(self, member: Member, store: JourneyStore) -> bool:
        """Whether this member should not be listed for this request: the
        member's own `hidden` rule, or its viewset's `hidden()`."""
        if member.hidden is not None and member.hidden(store):
            return True
        gate = getattr(member.viewset, "hidden", None)
        return gate is not None and bool(gate(store))

    def get_member_state(self, member: Member, store: JourneyStore) -> State:
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
        """Where a row links: a nested hub's own page, a link's target, or
        the door for a wizard — never the wizard's run."""
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
            kwargs={**self.get_page_url_kwargs(), self.member_url_kwarg: member.key},
        )

    def get_page_url_kwargs(self) -> dict[str, Any]:
        """This page's own URL kwargs: everything the request captured but
        the door's segment."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        return {
            key: value
            for key, value in url_kwargs.items()
            if key != self.member_url_kwarg
        }

    def get_page_url(self) -> str:
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_page_url) on {name}."
            )
        return reverse(self.url_name, kwargs=self.get_page_url_kwargs())

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        return self.get_page_url_kwargs()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        if self.hub_context_name is not None:
            context[self.hub_context_name] = self.get_hub()
        return context

    # --- the door -------------------------------------------------------------

    def enter(self, member: Member) -> str | None:
        """The URL to send the user into a member at, or `None` when there
        is nowhere to send them: a link, a member they cannot start yet, or
        a `stash_unusable()` that declined to name a destination.

        Resume before reopen. Reversed, a completed member under edit would
        resurrect a second run on every click and the user's in-flight edits
        would become unreachable.
        """
        if member.viewset is None:
            return None
        store = self.get_journey_store()
        if self.get_member_status(member, store) == BLOCKED:
            return None
        if self.is_hub(member):
            return self.get_member_url(member)
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
        return self.member_viewset(member).begin(
            self.request, **self.member_url_kwargs(member)
        )

    def stash_unusable(self, member: Member, error: InvalidStash) -> str | None:
        """A completed member whose stash no longer fits its wizard. Raises
        by default; override to discard it and start over, say."""
        raise error

    def member_unavailable(self, key: str) -> HttpResponse:
        """A door that cannot open — an unknown, hidden or blocked member.
        Back to the page."""
        return redirect(self.get_page_url())

    # --- the journey ----------------------------------------------------------

    def submit(self) -> HttpResponseBase:
        """Press the page's button. Refused unless every row is complete;
        then `hub_done()` for a nested hub, or `journey_done()` and the
        tombstone for the root."""
        hub = self.get_hub()
        if not hub.is_complete:
            return self.hub_incomplete(hub)
        store = self.get_journey_store()
        if self.is_nested:
            return self.hub_done(hub, store)
        response = self.journey_done(hub, store)
        store.complete()
        return response

    def hub_done(self, hub: HubPage, store: JourneyStore) -> HttpResponseBase:
        return redirect(self.get_hub_url())

    def journey_done(self, hub: HubPage, store: JourneyStore) -> HttpResponseBase:
        """The journey's work, and the one thing with no default. Runs once;
        a `journey_done()` that raises leaves every member resumable."""
        name = self.__class__.__name__
        raise ImproperlyConfigured(
            f"{name} has nothing to do when its journey is submitted. Override "
            f"{name}.journey_done() to do the work and return the response."
        )

    def hub_incomplete(self, hub: HubPage) -> HttpResponseBase:
        return redirect(self.get_page_url())

    # --- HTTP -------------------------------------------------------------------

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
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
            return self.member_unavailable(key)
        return redirect(url)


class Journey:
    """A journey begun on a hub, from outside the hub's own requests.

    `id` is the journey's identity, `store` its record, `url` the hub's
    page for it. `finish()` records a finished run as one of the hub's
    sections exactly as finishing it from the page would — stashed under
    the section's key and label, its `run_done()` run — so it arrives
    complete and re-openable like any other row.
    """

    def __init__(
        self,
        hub: type[HubViewSet],
        request: HttpRequest,
        id: str,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.hub = hub
        self.request = request
        self.id = id
        self.url_kwargs = dict(url_kwargs or {})

    @property
    def page_kwargs(self) -> dict[str, Any]:
        """The kwargs the hub's page is reversed with: the mount prefix and,
        when the hub is mounted under a journey segment, this journey."""
        kwargs = {**self.url_kwargs, self.hub.journey_url_kwarg: self.id}
        try:
            reverse(cast(str, self.hub.url_name), kwargs=kwargs)
        except NoReverseMatch:
            # One journey per session: no segment to put the id in.
            return self.url_kwargs
        return kwargs

    @property
    def url(self) -> str:
        return reverse(cast(str, self.hub.url_name), kwargs=self.page_kwargs)

    @property
    def store(self) -> JourneyStore:
        return cast(
            JourneyStore,
            self.hub.journey_store_class(
                WizardContext.from_request(self.request), self.id
            ),
        )

    def finish(self, section: str, bound_wizard: BoundWizard) -> None:
        """Record `bound_wizard`'s finished run as `section`."""
        view = self.hub.viewset_for(section)()
        view.setup(self.request, **self.page_kwargs)
        view.done(bound_wizard)
