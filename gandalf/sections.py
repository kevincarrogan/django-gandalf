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

from dataclasses import dataclass, field as dataclass_field

from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.views.generic import TemplateView

from gandalf.runtime import InvalidStash
from gandalf.storage import RunNotFound, SessionSectionStore, StashNotFound


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
    """

    key: str
    viewset: type
    title: str | None = None
    label: str | None = None
    reopen_step: str | None = None
    # Excluded from comparison so a mutable default cannot make a frozen
    # section unhashable — the same escape `SummaryField.bound_field` takes.
    url_kwargs: dict = dataclass_field(default_factory=dict, compare=False)

    @property
    def stash_label(self):
        """The label stamped into this section's stash — `label` if declared,
        otherwise the key."""
        return self.key if self.label is None else self.label


@dataclass(frozen=True)
class SectionRow:
    """One section of a hub: what it is called, how far it has got, and where
    its link goes. `section` is the underlying `Section`, so a template that
    needs the viewset or the section's own key can still reach them."""

    section: object
    status: str
    title: str
    status_label: str
    url: str

    @property
    def key(self):
        """The section's key."""
        return self.section.key

    @property
    def is_not_started(self):
        return self.status == NOT_STARTED

    @property
    def is_incomplete(self):
        return self.status == INCOMPLETE

    @property
    def is_complete(self):
        return self.status == COMPLETE


class SectionMixin:
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

    section_key = None
    section_label = None
    section_store_class = SessionSectionStore
    hub_url_name = None

    def get_section_key(self):
        if self.section_key is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no section to register as finished. Set "
                f"{name}.section_key to the key its hub declares it under."
            )
        return self.section_key

    def get_section_label(self):
        """The label stamped into this section's stash — `section_label` if
        declared, otherwise the key. Bump it when a deploy reshapes this
        wizard, so a payload from the old shape is refused rather than walked
        into a tree it no longer matches."""
        if self.section_label is None:
            return self.get_section_key()
        return self.section_label

    def get_section_store(self):
        return self.section_store_class(self.request)

    def get_hub_url(self):
        """Where a finished section sends the user back to. Forwards this
        wizard's own mount-prefix kwargs, which is right when hub and section
        share a mount; override when they do not."""
        if self.hub_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set hub_url_name (or override get_hub_url) on {name}."
            )
        return reverse(self.hub_url_name, kwargs=self.get_url_kwargs())

    def done(self, bound_wizard):
        """Record the section as finished, then hand off to `section_done()`.

        The stash is taken first because it can only be taken at all while the
        run's state is readable — completion tears that down after `done()`
        returns (see `WizardViewSet._finish`), but a `section_done()` that
        obliterates or escapes would get there first. The run id is cleared
        after `section_done()` returns, mirroring `_finish`'s own ordering: a
        `section_done()` that raises leaves the section resumable rather than
        stranded with a stash and no way back to the run that made it.
        """
        key = self.get_section_key()
        store = self.get_section_store()
        store.put_stash(key, bound_wizard.stash(label=self.get_section_label()))
        response = self.section_done(bound_wizard)
        store.clear_run(key)
        return response

    def section_done(self, bound_wizard):
        """What this section does when it finishes, beyond being recorded.
        Returns the response the user sees; the default sends them back to the
        hub, which is where a task list expects a finished task to deposit
        them."""
        return redirect(self.get_hub_url())


class HubMixin:
    """Adds `sections` — one `SectionRow` per declared section — to a view's
    template context, and owns the door each row links to.

    Mix into the page listing the sections, or use `HubView`, which is this
    over a `TemplateView` with the two URL patterns already published.
    """

    sections = None
    sections_context_name = "sections"
    section_store_class = SessionSectionStore
    section_url_name = None
    section_url_kwarg = "section"
    url_name = None

    # --- the sections this hub lists ---------------------------------------

    def get_sections(self):
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

    def _vetted_sections(self):
        """`get_sections()`, checked once per request.

        Both halves of the hub ask for the sections — the rows and the door —
        and the checks are properties of the declaration, not of either use,
        so they run once on the view instance Django builds per request.
        """
        if not hasattr(self, "_sections_cache"):
            self._sections_cache = self._validate_sections(self.get_sections())
        return self._sections_cache

    def _validate_sections(self, sections):
        """A key has to name exactly one section, and has to be the key that
        section's own wizard stashes under.

        Drift between the two is the quiet failure: the hub reads a stash key
        the section never writes, so the section completes and still renders
        as not started, forever.
        """
        keys = [section.key for section in sections]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ImproperlyConfigured(
                "Hub section keys must be unique; a key has to name exactly "
                f"one section. Duplicated: {', '.join(duplicates)}."
            )
        drifted = [
            section
            for section in sections
            if getattr(section.viewset, "section_key", None) not in (None, section.key)
        ]
        if drifted:
            names = ", ".join(
                f"{section.key} (its viewset stashes under "
                f"{section.viewset.section_key!r})"
                for section in drifted
            )
            raise ImproperlyConfigured(
                "A hub section's key must match its viewset's section_key, or "
                "the hub reads a stash the section never writes and the "
                f"section can never complete. Mismatched: {names}."
            )
        return list(sections)

    def get_section(self, key):
        """The declared section `key` names, raising `SectionNotFound`
        otherwise."""
        for section in self._vetted_sections():
            if section.key == key:
                return section
        raise SectionNotFound(key)

    def get_section_store(self):
        return self.section_store_class(self.request)

    # --- the page ----------------------------------------------------------

    def get_section_rows(self):
        store = self.get_section_store()
        return [
            self.build_section_row(section, store)
            for section in self._vetted_sections()
        ]

    def build_section_row(self, section, store):
        status = self.get_section_status(section, store)
        return SectionRow(
            section=section,
            status=status,
            title=self.get_section_title(section),
            status_label=self.get_status_label(status),
            url=self.get_section_url(section),
        )

    def get_section_status(self, section, store):
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
        """
        if store.has_stash(section.key):
            return COMPLETE
        if self.get_section_state(section, store):
            return INCOMPLETE
        return NOT_STARTED

    def get_section_state(self, section, store):
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
        storage = section.viewset.storage_class(self.request)
        try:
            return storage.get_state(run_id)
        except RunNotFound:
            return []

    def get_section_title(self, section):
        """The heading for a section's row: its declared `title`, otherwise
        its key made readable."""
        if section.title is not None:
            return section.title
        return capfirst(section.key.replace("_", " ").replace("-", " "))

    def get_status_label(self, status):
        """The status as display text. Override for your own wording."""
        return {
            NOT_STARTED: gettext("Not started"),
            INCOMPLETE: gettext("Incomplete"),
            COMPLETE: gettext("Complete"),
        }[status]

    def get_section_url(self, section):
        """Where a row's link goes: this hub's own entry URL for the section.

        Never the wizard's. A row cannot know which run to resume without
        walking it, and a link straight at the wizard would have to be either
        the start URL — which mints a second run beside the one the user is
        halfway through — or the bare run URL, which fires `done()` on a GET
        the moment every stored answer validates. The door is the one place
        that can afford to ask.
        """
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

    def get_section_url_kwargs(self):
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

    def get_hub_url(self):
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_hub_url) on {name}."
            )
        return reverse(self.url_name, kwargs=self.get_section_url_kwargs())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context[self.sections_context_name] = self.get_section_rows()
        return context

    # --- the door ----------------------------------------------------------

    def enter(self, section):
        """The URL that puts the user inside this section, wherever it left
        off.

        Entering is dispatch, not display: it asks what exists rather than
        what the row rendered. Every arm ends at `entry_url()`, so no path
        here can emit a bare run URL.
        """
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

    def resume_section(self, section, store):
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
            bound_wizard = section.viewset.inspect(
                self.request, run_id, **section.url_kwargs
            )
        except RunNotFound:
            return None
        if bound_wizard.is_complete:
            return None
        return bound_wizard

    def reopen_section(self, section, store):
        """A fresh run seeded from the section's stash, or None with nothing
        stashed. The stash is read, never popped: re-opening keeps working,
        and re-completing overwrites it with the newer answers."""
        try:
            payload = store.get_stash(section.key)
        except StashNotFound:
            return None
        return section.viewset.reopen(
            self.request,
            payload,
            expected_label=section.stash_label,
            **section.url_kwargs,
        )

    def start_section(self, section):
        """A brand-new run for a section with nothing behind it."""
        return section.viewset.begin(self.request, **section.url_kwargs)

    def stash_unusable(self, section, error):
        """What to do with a stash that cannot seed a run — a payload whose
        label no longer matches, which almost always means a deploy reshaped
        this section and bumped it.

        Re-raises by default: a silent fresh start would look to the user
        exactly like their answers vanishing. Override to start over (delete
        the stash and `enter()` again), or to return a URL that explains.
        """
        raise error

    def section_unavailable(self, key):
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
    def urls(cls):
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

    def get(self, request, *args, **kwargs):
        key = kwargs.get(self.section_url_kwarg)
        if key is None:
            return super().get(request, *args, **kwargs)
        try:
            section = self.get_section(key)
        except SectionNotFound:
            return self.section_unavailable(key)
        return redirect(self.enter(section))
