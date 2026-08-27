"""Hub and spoke: a page of parallel wizards the user drops in and out of.

A hub asks the same three questions of every section — what is it called, how
far has it got, and where does its link go — so `HubMixin` answers them once.
Mix it into the page's view and the template gets a `sections` list: one
`SectionRow` per declared section, carrying its title, its status, and one URL
that does the right thing whichever of the three states it is in.

A section is *complete* when it ran to its own end and `done()` stashed the
answers. That is the only definition the hub has, and it is deliberately the
cheap one: a row costs two storage reads and a `reverse()`, never a walk.
Finding out where a half-finished run actually is does cost a walk, so it
happens once, on the way in, for the one section the user clicked.

Every decision is a hook: `get_sections()` chooses the sections,
`get_section_status()` decides how far one has got, `get_section_title()` names
it, `get_section_url()` says where its link goes, and `resume_section()` /
`reopen_section()` / `start_section()` each own one way into a run. The
defaults suit a plain task list; override what your domain needs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect
from django.urls import URLPattern, path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.views.generic import TemplateView

from gandalf.context import WizardContext
from gandalf.runtime import BoundWizard, InvalidStash
from gandalf.storage import RunNotFound, SessionSectionStore, StashNotFound
from gandalf.types import State, StrOrPromise
from gandalf.viewsets import WizardViewSet


if TYPE_CHECKING:
    # Mixins with no bases of their own: at type-check time each is given the
    # class it documents itself as mixing into, so `self.request`,
    # `get_context_data()` and the rest resolve. At runtime both stay plain
    # mixins.
    _SectionMixinBase = WizardViewSet
    _HubMixinBase = TemplateView
else:
    _SectionMixinBase = object
    _HubMixinBase = object


__all__ = [
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "HubMixin",
    "HubView",
    "Section",
    "SectionMixin",
    "SectionNotFound",
    "SectionRow",
]


# Plain strings rather than an enum, following `run_unavailable(reason=...)`:
# a status is rendered into a template and compared in one, and neither reads
# well through a member lookup.
NOT_STARTED = "not-started"
INCOMPLETE = "incomplete"
COMPLETE = "complete"


class SectionNotFound(LookupError):
    """Raised when a key names no section this hub declares — a stale link,
    a renamed section, or a URL typed by hand."""


@dataclass(frozen=True)
class Section:
    """One spoke of a hub: a wizard the user can enter, leave, and come back
    to.

    `key` is the section's identity — the stash key its finished answers live
    under and the URL segment the hub's own door routes on. `viewset` is the
    `WizardViewSet` subclass that runs it. `title` is what the hub renders;
    without one the key is made readable, exactly as a summary row's label is.

    `label` is the *shape's* identity, not the section's: it is stamped into
    the stash and checked on the way back out, so a deploy that reshapes this
    wizard can bump the label without renaming the section, and a payload from
    the old shape is refused at the door rather than walked into a tree it no
    longer matches. Defaults to `key`.

    `reopen_step` names the step a completed section re-opens at; without one
    it is the first step on the route, so the user walks their own answers
    rather than landing at the end. `url_kwargs` are the mount-prefix kwargs
    this section's wizard is mounted under (a tenant slug, a plan), forwarded
    into every URL the hub builds for it — the section's own, not the hub's,
    since the two can be mounted separately.

    A section need not be a wizard at all. Leave `viewset` out and supply
    `url_name` and `status` instead, and the row becomes a link to somewhere
    the hub does not run: a collection page, a payment redirect, a page in
    another app. Both are required together — without the first the hub builds
    a door it cannot open, and without the second it derives a status from a
    stash key nothing writes.
    """

    key: str
    viewset: type[WizardViewSet] | None = None
    title: StrOrPromise | None = None
    label: str | None = None
    reopen_step: str | None = None
    # Excluded from comparison so a mutable default cannot make a frozen
    # section unhashable — the same escape `SummaryField.bound_field` takes.
    url_kwargs: dict[str, Any] = dataclass_field(default_factory=dict, compare=False)
    #: Where this row links, instead of the hub's own door. The door exists to
    #: walk a run and pick a step; something with no run to walk has nothing
    #: for it to do, so the row addresses it directly.
    url_name: str | None = None
    #: What decides this section's status when the hub cannot. Called with the
    #: request. Excluded from comparison for the same reason as `url_kwargs`.
    status: Callable[[HttpRequest], str] | None = dataclass_field(
        default=None, compare=False
    )

    @property
    def stash_label(self) -> str:
        """The label stamped into this section's stash — `label` if declared,
        otherwise the key."""
        return self.key if self.label is None else self.label


@dataclass(frozen=True)
class SectionRow:
    """One section of a hub: what it is called, how far it has got, and where
    its link goes. `section` is the underlying `Section`, so a template that
    needs the viewset or the section's own key can still reach them."""

    section: Section
    status: str
    title: StrOrPromise
    status_label: StrOrPromise
    url: str

    @property
    def key(self) -> str:
        """The section's key."""
        return self.section.key

    @property
    def is_not_started(self) -> bool:
        return self.status == NOT_STARTED

    @property
    def is_incomplete(self) -> bool:
        return self.status == INCOMPLETE

    @property
    def is_complete(self) -> bool:
        return self.status == COMPLETE


class SectionMixin(_SectionMixinBase):
    """Mix into a section's `WizardViewSet` so finishing it registers with the
    hub.

    **Sections override `section_done()`, never `done()`.** `done()` is this
    mixin's: a subclass that replaced it would stash nothing, and the hub
    would never learn the section had finished — a section that appears to
    reset itself every time it is completed.

        class ContactSectionViewSet(SectionMixin, WizardViewSet):
            url_name = "profile-contact"
            section_key = "contact"
            hub_url_name = "profile-hub"
            wizard = ...

            def section_done(self, bound_wizard):
                save_contact(self.request.user, bound_wizard)
                return super().section_done(bound_wizard)

    Re-opening a completed section and fixing one answer walks to the end and
    fires `done()` again. That is the intended "edit and re-save" semantics,
    which is why the bookkeeping here is idempotent and `section_done()` is
    where work that runs once per edit belongs. Give the wizard a review step
    if the user should get an explicit confirm gate first.
    """

    section_key: str | None = None
    section_label: str | None = None
    section_store_class = SessionSectionStore
    hub_url_name: str | None = None
    #: Whether this section's key is only knowable per request — one wizard
    #: mounted per item of a collection, keyed off a URL kwarg. Such a section
    #: overrides `get_section_key()` and declares no `section_key`, so the
    #: usual "set the class attribute" advice would be wrong for it.
    dynamic_section_key: bool = False

    def get_section_key(self) -> str:
        if self.section_key is None:
            name = self.__class__.__name__
            if self.dynamic_section_key:
                raise ImproperlyConfigured(
                    f"{name} declares dynamic_section_key but derives no key. "
                    f"Override {name}.get_section_key() to build one from the "
                    f"request — a URL kwarg, the user, the tenant."
                )
            raise ImproperlyConfigured(
                f"{name} has no section to register as finished. Set "
                f"{name}.section_key to the key its hub declares it under."
            )
        return self.section_key

    def get_section_label(self) -> str:
        """The label stamped into this section's stash — `section_label` if
        declared, otherwise the key. Bump it when a deploy reshapes this
        wizard, so a payload from the old shape is refused rather than walked
        into a tree it no longer matches."""
        if self.section_label is None:
            return self.get_section_key()
        return self.section_label

    def get_section_store(self) -> SessionSectionStore:
        return self.section_store_class(WizardContext.from_request(self.request))

    def get_hub_url(self) -> str:
        """Where a finished section sends the user back to. Forwards this
        wizard's own mount-prefix kwargs, which is right when hub and section
        share a mount; override when they do not."""
        if self.hub_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set hub_url_name (or override get_hub_url) on {name}."
            )
        return reverse(self.hub_url_name, kwargs=self.get_url_kwargs())

    def done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        """Record the section as finished, then hand off to `section_done()`.

        The stash is taken first because it can only be taken at all while the
        run's state is readable — completion tears that down after `done()`
        returns (see `WizardViewSet.finish`), but a `section_done()` that
        obliterates or escapes would get there first. `section_recorded()`
        shares that window, for the same reason. The run id is cleared after
        `section_done()` returns, mirroring `finish`'s own ordering: a
        `section_done()` that raises leaves the section resumable rather than
        stranded with a stash and no way back to the run that made it.
        """
        key = self.get_section_key()
        store = self.get_section_store()
        store.put_stash(key, bound_wizard.stash(label=self.get_section_label()))
        self.section_recorded(bound_wizard, store, key)
        response = self.section_done(bound_wizard)
        store.clear_run(key)
        return response

    def section_recorded(
        self, bound_wizard: BoundWizard, store: SessionSectionStore, key: str
    ) -> None:
        """Bookkeeping to record alongside the stash, inside the window where
        the run's answers are still readable.

        Sits where it does for the same reason the stash does: completion
        tears the run's state down after `done()` returns, and a
        `section_done()` that obliterates or escapes gets there first — so
        anything that has to *read* the finished run belongs above it. A plain
        section records nothing here; a collection's item caches its title,
        because working one out means reading `bound_wizard.path` and there is
        no later moment at which that is possible.

        Not for application work. That is `section_done()`, which runs once
        per edit and is allowed to fail; this is the library's own half of the
        same ordering, and a hub whose bookkeeping raised here would leave a
        stash it could not describe.
        """

    def section_done(self, bound_wizard: BoundWizard) -> HttpResponseBase:
        """What this section does when it finishes, beyond being recorded.
        Returns the response the user sees; the default sends them back to the
        hub, which is where a task list expects a finished task to deposit
        them."""
        return redirect(self.get_hub_url())


class HubMixin(_HubMixinBase):
    """Adds `sections` — one `SectionRow` per declared section — to a view's
    template context, and owns the door each row links to.

    Mix into the page listing the sections, or use `HubView`, which is this
    over a `TemplateView` with the two URL patterns already published.
    """

    sections: list[Section] | None = None
    sections_context_name = "sections"
    section_store_class = SessionSectionStore
    section_url_name: str | None = None
    section_url_kwarg = "section"
    url_name: str | None = None

    # --- the sections this hub lists ---------------------------------------

    def get_sections(self) -> list[Section]:
        """The sections this hub lists, in the order they are shown. Override
        to choose them per request — by user, by plan, by feature flag."""
        if self.sections is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no sections to list. Define {name}.sections as a "
                f"list of Section declarations, or override "
                f"{name}.get_sections() to build one per request."
            )
        return list(self.sections)

    def _vetted_sections(self) -> list[Section]:
        """`get_sections()`, checked once per request.

        Both halves of the hub ask for the sections — the rows and the door —
        and the checks are properties of the declaration, not of either use,
        so they run once on the view instance Django builds per request.
        """
        if not hasattr(self, "_sections_cache"):
            self._sections_cache = self._validate_sections(self.get_sections())
        return self._sections_cache

    def _validate_sections(self, sections: list[Section]) -> list[Section]:
        """A key has to name exactly one section, has to be the key that
        section's own wizard stashes under, and that wizard has to return to
        this hub.

        Drift is the quiet failure in all three. A key the section never
        stashes under means the hub reads a stash nothing writes, so the
        section completes and still renders as not started, forever. A
        `hub_url_name` naming some other page means finishing works and simply
        deposits the user somewhere that does not list the section they just
        finished — the pair only ever holds because both sides were typed the
        same, so it is checked rather than trusted.

        Both viewset checks are lenient about `None`: a section doing its own
        bookkeeping declares neither, and a hub that leaves `url_name` unset
        is mounted under a name only its URLconf knows, so there is nothing to
        compare against.
        """
        keys = [section.key for section in sections]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ImproperlyConfigured(
                "Hub section keys must be unique; a key has to name exactly "
                f"one section. Duplicated: {', '.join(duplicates)}."
            )
        unreachable = [
            section.key
            for section in sections
            if section.viewset is None
            and (section.url_name is None or section.status is None)
        ]
        if unreachable:
            raise ImproperlyConfigured(
                "A hub section that is not a wizard must declare both "
                "url_name and status: without the first the hub builds a door "
                "it cannot open, and without the second it derives a status "
                f"from a stash key nothing writes. Underspecified: "
                f"{', '.join(sorted(unreachable))}."
            )
        drifted = [
            section
            for section in sections
            if getattr(section.viewset, "section_key", None) not in (None, section.key)
        ]
        if drifted:
            names = ", ".join(
                f"{section.key} (its viewset stashes under "
                f"{getattr(section.viewset, 'section_key')!r})"
                for section in drifted
            )
            raise ImproperlyConfigured(
                "A hub section's key must match its viewset's section_key, or "
                "the hub reads a stash the section never writes and the "
                f"section can never complete. Mismatched: {names}."
            )
        if self.url_name is not None:
            mispointed = [
                section
                for section in sections
                if getattr(section.viewset, "hub_url_name", None)
                not in (None, self.url_name)
            ]
            if mispointed:
                names = ", ".join(
                    f"{section.key} (its viewset returns to "
                    f"{getattr(section.viewset, 'hub_url_name')!r})"
                    for section in mispointed
                )
                raise ImproperlyConfigured(
                    "A hub section's viewset must return to the hub that "
                    "lists it, or finishing the section deposits the user on "
                    f"a page that does not list it. Mispointed: {names}."
                )
        return list(sections)

    def get_section(self, key: str) -> Section:
        """The declared section `key` names, raising `SectionNotFound`
        otherwise."""
        for section in self._vetted_sections():
            if section.key == key:
                return section
        raise SectionNotFound(key)

    def get_section_store(self) -> SessionSectionStore:
        return self.section_store_class(WizardContext.from_request(self.request))

    def section_viewset(self, section: Section) -> type[WizardViewSet]:
        """The wizard behind a section, for the four places that run one.

        A section with no viewset supplies its own status and is turned away
        at the door, so none of those four can be reached with one — see
        `_validate_sections()` and `enter()`.
        """
        return cast("type[WizardViewSet]", section.viewset)

    # --- the page ----------------------------------------------------------

    def get_section_rows(self) -> list[SectionRow]:
        store = self.get_section_store()
        return [
            self.build_section_row(section, store)
            for section in self._vetted_sections()
        ]

    def build_section_row(
        self, section: Section, store: SessionSectionStore
    ) -> SectionRow:
        status = self.get_section_status(section, store)
        return SectionRow(
            section=section,
            status=status,
            title=self.get_section_title(section),
            status_label=self.get_status_label(status),
            url=self.get_section_url(section),
        )

    def get_section_status(self, section: Section, store: SessionSectionStore) -> str:
        """How far a section has got: `COMPLETE`, `INCOMPLETE`, or
        `NOT_STARTED`.

        Complete means the section ran to its own end — `done()` fired and
        stashed — because a stash under the section's key is the only thing
        that can only have come from finishing. Incomplete means a run is
        recorded for the section and holds at least one submission: the user
        went in and answered something. Everything else has not started,
        including a section the user opened and left without answering, and
        one whose run the storage has since forgotten (an expired session, an
        obliterated run). There is nothing to pick up, so the honest thing to
        say is that it has not begun.

        Two storage reads and no walk. Whether the stored answers still
        *validate* is deliberately not asked: that costs one form `clean()`
        per answered step per row, and the answer would not change the row —
        an answer that no longer validates leaves the section in progress just
        as surely as one that does.

        A section carrying its own `status` answers for itself and none of
        this runs, which is the only way a row can report something no stash
        key can express.
        """
        if section.status is not None:
            return section.status(self.request)
        if store.has_stash(section.key):
            return COMPLETE
        if self.get_section_state(section, store):
            return INCOMPLETE
        return NOT_STARTED

    def get_section_state(self, section: Section, store: SessionSectionStore) -> State:
        """The stored state of the section's recorded run — an empty list when
        it has none, or one the storage no longer holds.

        Read straight off the section's own `storage_class`, not through
        `WizardViewSet.inspect()`: the shape of the state is the whole
        question, and building a runtime to answer it would resolve the wizard
        and walk its tree to find out something the storage already knows.
        Public so a hub that wants a progress count can compute one from the
        raw entries — bearing in mind that they are positional against a tree
        whose shape may depend on a branch predicate nobody has evaluated.
        """
        run_id = store.get_run(section.key)
        if run_id is None:
            return []
        storage = self.section_viewset(section).storage_class(
            WizardContext.from_request(self.request)
        )
        try:
            return storage.get_state(run_id)
        except RunNotFound:
            return []

    def get_section_title(self, section: Section) -> StrOrPromise:
        """The heading for a section's row: its declared `title`, otherwise
        its key made readable."""
        if section.title is not None:
            return section.title
        return capfirst(section.key.replace("_", " ").replace("-", " "))

    def get_status_label(self, status: str) -> StrOrPromise:
        """The status as display text. Override for your own wording."""
        return {
            NOT_STARTED: gettext("Not started"),
            INCOMPLETE: gettext("Incomplete"),
            COMPLETE: gettext("Complete"),
        }[status]

    def get_section_url(self, section: Section) -> str:
        """Where a row's link goes: this hub's own entry URL for the section.

        Never the wizard's. A row cannot know which run to resume without
        walking it, and a link straight at the wizard would have to be either
        the start URL — which mints a second run beside the one the user is
        halfway through — or the bare run URL, which fires `done()` on a GET
        the moment every stored answer validates. The door is the one place
        that can afford to ask.

        The one exception is a section that is not a wizard. It declares its
        own `url_name`, and the row goes straight there: there is no run to
        walk, so the door would have nothing to decide.
        """
        if section.url_name is not None:
            return reverse(
                section.url_name,
                kwargs={**self.get_section_url_kwargs(), **section.url_kwargs},
            )
        if self.section_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set section_url_name (or override get_section_url) on {name}."
            )
        return reverse(
            self.section_url_name,
            kwargs={
                **self.get_section_url_kwargs(),
                self.section_url_kwarg: section.key,
            },
        )

    def get_section_url_kwargs(self) -> dict[str, Any]:
        """URL kwargs the hub's mount prefix captured (e.g. a tenant slug),
        forwarded into every reverse of the hub's own URLs — the same
        arrangement `WizardViewSet.get_url_kwargs()` makes. Everything the
        request captured except the section key the door itself owns."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        return {
            key: value
            for key, value in url_kwargs.items()
            if key != self.section_url_kwarg
        }

    def get_hub_url(self) -> str:
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_hub_url) on {name}."
            )
        return reverse(self.url_name, kwargs=self.get_section_url_kwargs())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context[self.sections_context_name] = self.get_section_rows()
        return context

    # --- the door ----------------------------------------------------------

    def enter(self, section: Section) -> str | None:
        """The URL that puts the user inside this section, wherever it left
        off.

        Entering is dispatch, not display: it asks what exists rather than
        what the row rendered. Every arm ends at `entry_url()`, so no path
        here can emit a bare run URL.

        A section that is not a wizard has no run to enter, and its row links
        past the door anyway — so arriving here at all is a hand-typed or
        stale URL, and it is refused rather than guessed at.
        """
        if section.viewset is None:
            return None
        store = self.get_section_store()
        # Resume before reopen. Reversed, a completed section under edit
        # would resurrect a second run on every click and the user's
        # in-flight edits would become unreachable.
        resumed = self.resume_section(section, store)
        if resumed is not None:
            return resumed.entry_url()
        try:
            reopened = self.reopen_section(section, store)
        except InvalidStash as error:
            return self.stash_unusable(section, error)
        if reopened is not None:
            store.set_run(section.key, reopened.run_id)
            return reopened.entry_url(section.reopen_step)
        started = self.start_section(section)
        store.set_run(section.key, started.run_id)
        return started.entry_url()

    def resume_section(
        self, section: Section, store: SessionSectionStore
    ) -> BoundWizard | None:
        """The section's live run, or None when it has none.

        A recorded run is resumable only while storage still holds it and it
        has not been tombstoned. A completed run is *addressable* but not
        runnable — `retrieve_run` finds it, and `is_complete` is what tells
        the two apart, the same pair `WizardViewSet._retrieve_run` checks
        before it will serve a request. Sending the user into a tombstoned run
        would bounce every request back to the start URL with no error to
        explain it.
        """
        run_id = store.get_run(section.key)
        if run_id is None:
            return None
        try:
            bound_wizard = self.section_viewset(section).inspect(
                self.request, run_id, **section.url_kwargs
            )
        except RunNotFound:
            return None
        if bound_wizard.is_complete:
            return None
        return bound_wizard

    def reopen_section(
        self, section: Section, store: SessionSectionStore
    ) -> BoundWizard | None:
        """A fresh run seeded from the section's stash, or None with nothing
        stashed. The stash is read, never popped: re-opening keeps working,
        and re-completing overwrites it with the newer answers."""
        try:
            payload = store.get_stash(section.key)
        except StashNotFound:
            return None
        return self.section_viewset(section).reopen(
            self.request,
            payload,
            expected_label=section.stash_label,
            **section.url_kwargs,
        )

    def start_section(self, section: Section) -> BoundWizard:
        """A brand-new run for a section with nothing behind it."""
        return self.section_viewset(section).begin(self.request, **section.url_kwargs)

    def stash_unusable(self, section: Section, error: InvalidStash) -> str | None:
        """What to do with a stash that cannot seed a run — a payload whose
        label no longer matches, which almost always means a deploy reshaped
        this section and bumped it.

        Re-raises by default: a silent fresh start would look to the user
        exactly like their answers vanishing. Override to start over (delete
        the stash and `enter()` again), or to return a URL that explains.
        """
        raise error

    def section_unavailable(self, key: str) -> HttpResponse:
        """Response for a key this hub declares no section for — a stale
        link, a renamed section. The default sends the user back to the hub
        itself; override to raise `Http404`."""
        return redirect(self.get_hub_url())


class HubView(HubMixin, TemplateView):
    """A hub page and the door into each of its sections.

    One view over two routes, for the same reason a wizard is one view over
    three: the door has to make the decision the page cannot afford to. A row
    renders without walking anything, so it cannot know which run its link
    should resume; the door walks exactly the one section the user clicked and
    redirects to a step URL.

        class ProfileHubView(HubView):
            template_name = "profile/hub.html"
            url_name = "profile-hub"
            section_url_name = "profile-hub-section"
            sections = [
                Section("contact", ContactSectionViewSet, title="Contact details"),
                Section("address", AddressSectionViewSet, title="Address"),
            ]

    Mount it exactly like a wizard:

        path("profile/", include(ProfileHubView.urls()))
    """

    @classmethod
    def urls(cls) -> list[URLPattern]:
        """URL patterns for this hub, derived from `url_name`: `<url_name>`
        (the page) and `<url_name>-section` (the door into one section)."""
        if cls.url_name is None:
            raise ImproperlyConfigured("HubView.urls() requires url_name to be set.")
        view = cls.as_view()
        return [
            path("", view, name=cls.url_name),
            path(
                f"<slug:{cls.section_url_kwarg}>/",
                view,
                name=f"{cls.url_name}-section",
            ),
        ]

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        key = kwargs.get(self.section_url_kwarg)
        if key is None:
            return super().get(request, *args, **kwargs)
        try:
            section = self.get_section(key)
        except SectionNotFound:
            return self.section_unavailable(key)
        url = self.enter(section)
        if url is None:
            # Nothing to walk — a section that is not a wizard, or a
            # `stash_unusable()` that declined to name a destination.
            return self.section_unavailable(key)
        return redirect(url)
