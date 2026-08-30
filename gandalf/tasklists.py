"""A task list: a page of sections the user finishes in any order, and the
journey their answers add up to.

Declared as a class body, and mounted by a viewset:

    class GrantApplication(TaskList):
        setup = Section(SetupSection, title="Applying as")
        contact = Section(contact, title="Contact details", reopen_at="review")
        budget = AddAnother(budget_line, title="Budget", min_items=1)
        supporting = Group(SupportingInformation, title="Supporting information")


    class GrantApplicationViewSet(TaskListViewSet):
        url_name = "apply"
        template_name = "apply/task_list.html"
        task_list = GrantApplication

        def journey_done(self, page, store): ...


    urlpatterns = [path("apply/<slug:journey>/", include(GrantApplicationViewSet.urls()))]

The same split a wizard has: `TaskList` is a value — what the list is, its
entries in order — and `TaskListViewSet` is the view that mounts it and
owns what needs a request: the page, its URL, the journey's ending. A
value can be asked what a view should not be: `GrantApplication.begin(
request)` starts a journey from anywhere.

The attribute name is the entry's key; the body's order is the page's
order, the way a form's fields are. An entry carries *facts* — a title,
where a finished section re-opens — and the thing in its slot carries
*behaviour*: a `Wizard`, which the library wraps in a `SectionViewSet`,
or your own `SectionViewSet` subclass when the section has something to
do when it finishes (`run_done()`) or a reason not to be open yet
(`blocked()`, `hidden()`). Nothing about the task list changes between the
two — the same rule a wizard has for a `Form` and a `FormView`.

The page asks the same three questions of every entry — what is it called,
how far has it got, and where does its link go — and `TaskListViewSet`
answers them once. The template gets a `task_list`: one `Row` per entry,
carrying its title, its status, and one URL that does the right thing
whichever state it is in, wrapped in a `TaskListPage` that says how far
the whole page has got.

A section is *complete* when it ran to its own end and its answers were
stashed. That is the only definition the page has, and it is deliberately
the cheap one: a row costs two storage reads and a `reverse()`, never a
walk. Finding out where a half-finished run actually is does cost a walk,
so it happens once, on the way in, for the one section the user clicked.

`TaskListViewSet` owns the URL tree beneath it. Every entry is mounted
under the page — `contact/` opens the contact section *through the page*,
so there is no bare run URL to link by mistake, and a group's sections are
keyed under its prefix (`"supporting:referees"`) without anyone typing it.

Every decision the page makes is a hook: `get_entries()` chooses the
entries, `get_entry_status()` decides how far one has got,
`get_page_status()` how far they have got between them,
`get_entry_title()` names it, `get_entry_url()` says where its link goes,
and `resume_section()` / `reopen_section()` / `start_section()` each own
one way into a run. A group's page is a subclass of the root's, so an
override on the root applies to the whole tree.

The entries add up to a *journey* — the application, the claim, the
profile — and everything a page keeps is scoped to one: the store is
built with the journey's identity, which a page reads off a URL kwarg or
declares. The root owns the journey's ending: `submit()` runs
`journey_done()` and tombstones the record, after which every way back
in is refused and `submitted()` is the page.
"""

from __future__ import annotations

import re
import uuid
from abc import abstractmethod
from dataclasses import dataclass
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
from django.urls import (
    NoReverseMatch,
    URLPattern,
    URLResolver,
    include,
    path,
    reverse,
)
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.views.generic import TemplateView

from gandalf.context import WizardContext
from gandalf.runtime import Run, InvalidStash
from gandalf.storage import (
    RunNotFound,
    SessionCollectionStore,
    SessionStorage,
    StashNotFound,
)
from gandalf.types import JourneyStore, State, StorageClass, StrOrPromise
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import ConfiguredWizard, Wizard, declared_step_names

if TYPE_CHECKING:
    from gandalf.add_another import AddAnotherViewSet

__all__ = [
    "BLOCKED",
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "AddAnother",
    "Entry",
    "EntryNotFound",
    "Group",
    "Journey",
    "JourneyScoped",
    "Link",
    "Row",
    "Section",
    "SectionViewSet",
    "TaskList",
    "TaskListPage",
    "TaskListViewSet",
]


# Plain strings rather than an enum, following `run_unavailable(reason=...)`:
# a status is rendered into a template and compared in one, and neither reads
# well through a lookup.
NOT_STARTED = "not-started"
INCOMPLETE = "incomplete"
COMPLETE = "complete"
# Named for the state rather than the wording, unlike its three siblings,
# because the wording is a label's job and `is_cannot_start` is no name for a
# property. The default label is the task list's own: "Cannot start yet".
BLOCKED = "blocked"


class EntryNotFound(LookupError):
    """Raised when a key names no entry this task list declares — a stale
    link, a renamed section, or a URL typed by hand."""


#: A section is declared by its `Wizard`, or by a `SectionViewSet` subclass
#: when it has behaviour — `run_done()`, `blocked()`, `hidden()`.
WizardLike = Wizard | ConfiguredWizard | type[WizardViewSet]


# --- the declaration ---------------------------------------------------------


class Entry:
    """One entry of a task list — something the user can enter, leave, and
    come back to. `Section`, `AddAnother`, `Group` and `Link` are the kinds.

    Declared in a `TaskList` body: the attribute name is the key unless
    `key=` says otherwise — the key is the URL segment, and an attribute
    name cannot carry a hyphen — bound when the list is built (`bound()`),
    along with the viewset that runs it. `title` is what the page renders; without one the key is
    made readable. `label` is the stash's shape-identity, bumped when a
    deploy reshapes the wizard so an old payload is refused rather than
    walked; it defaults to the full key. `url_kwargs` are the extra kwargs
    this entry's own URLs take beyond the page's — an item's id.
    """

    #: The step a finished entry re-opens at, where that applies.
    reopen_at: str | None = None
    #: Where a link goes, and what decides its status; `None` for the rest.
    url_name: str | None = None
    status: Callable[[HttpRequest, dict[str, Any]], str] | None = None

    def __init__(
        self,
        *,
        title: StrOrPromise | None = None,
        label: str | None = None,
        key: str = "",
        viewset: type[Any] | None = None,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.title = title
        self.label = label
        self.key = key
        self.viewset = viewset
        self.url_kwargs = dict(url_kwargs or {})

    def facts(self) -> dict[str, Any]:
        """What this entry declares, for building a bound copy of it."""
        return {"title": self.title, "label": self.label}

    def bound(self, key: str, viewset: type[Any] | None = None) -> Entry:
        """This entry under `key`, run by `viewset`."""
        return type(self)(
            **self.facts(), key=key, viewset=viewset, url_kwargs=self.url_kwargs
        )

    def replace(self, **changes: Any) -> Entry:
        """This entry with some of its facts changed — one add-another
        declared once and listed twice with different minimums, say."""
        return type(self)(
            **{**self.facts(), **changes},
            key=self.key,
            viewset=self.viewset,
            url_kwargs=self.url_kwargs,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entry) or type(other) is not type(self):
            return NotImplemented
        return (self.facts(), self.key) == (other.facts(), other.key)

    def __hash__(self) -> int:
        return hash((type(self), self.key))

    def __repr__(self) -> str:
        facts = ", ".join(f"{name}={value!r}" for name, value in self.facts().items())
        return f"{type(self).__name__}({facts}, key={self.key!r})"


class Section(Entry):
    """A wizard the user finishes on its own and can come back to.

    `wizard` is a `Wizard`, or a `SectionViewSet` subclass with the
    section's behaviour on it. `reopen_at` names the step a completed section
    re-opens at — a review step, so the user lands on their answers rather
    than at step one.
    """

    def __init__(
        self,
        wizard: WizardLike,
        *,
        title: StrOrPromise | None = None,
        reopen_at: str | None = None,
        label: str | None = None,
        key: str = "",
        viewset: type[Any] | None = None,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            title=title, label=label, key=key, viewset=viewset, url_kwargs=url_kwargs
        )
        self.wizard = wizard
        self.reopen_at = reopen_at

    def facts(self) -> dict[str, Any]:
        return {**super().facts(), "wizard": self.wizard, "reopen_at": self.reopen_at}


class AddAnother(Entry):
    """A list the user grows, one run of `wizard` per item.

    `item_name` is what an unfinished item is called on the page ("Budget
    line 2"); `item_title` — a `(step, field)`, or a callable handed the
    finished run — is what names a finished one. `min_items` is how many
    a declared-done list needs before it counts as complete. `reopen_at`
    names the step a finished item re-opens at. `label` is every item's
    stash label. `template_name` and `remove_template_name` are the page
    and the remove confirmation.
    """

    def __init__(
        self,
        wizard: WizardLike,
        *,
        title: StrOrPromise | None = None,
        item_name: StrOrPromise | None = None,
        item_title: tuple[str, str] | Callable[[Run], str] | None = None,
        min_items: int = 0,
        reopen_at: str | None = None,
        label: str | None = None,
        template_name: str | None = None,
        remove_template_name: str | None = None,
        key: str = "",
        viewset: type[Any] | None = None,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            title=title, label=label, key=key, viewset=viewset, url_kwargs=url_kwargs
        )
        self.wizard = wizard
        self.item_name = item_name
        self.item_title = item_title
        self.min_items = min_items
        self.reopen_at = reopen_at
        self.template_name = template_name
        self.remove_template_name = remove_template_name

    def facts(self) -> dict[str, Any]:
        return {
            **super().facts(),
            "wizard": self.wizard,
            "item_name": self.item_name,
            "item_title": self.item_title,
            "min_items": self.min_items,
            "reopen_at": self.reopen_at,
            "template_name": self.template_name,
            "remove_template_name": self.remove_template_name,
        }


class Group(Entry):
    """A task list within this one: its sections are keyed under this
    entry's key in the same journey, its row here reads its own rows'
    status, and its Continue returns here rather than ending anything.
    `template_name` is the group's page."""

    def __init__(
        self,
        task_list: type[TaskList],
        *,
        title: StrOrPromise | None = None,
        template_name: str | None = None,
        key: str = "",
        viewset: type[Any] | None = None,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(title=title, key=key, viewset=viewset, url_kwargs=url_kwargs)
        self.task_list = task_list
        self.template_name = template_name

    def facts(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "task_list": self.task_list,
            "template_name": self.template_name,
        }


class Link(Entry):
    """A row that links somewhere the task list does not run — a payment
    page, a page in another app. `status` decides what the row says of it,
    called with the request and the URL kwargs the page would hand the
    entry's own view; the page cannot derive one from a stash nothing
    writes, so it is required."""

    def __init__(
        self,
        url_name: str,
        *,
        title: StrOrPromise | None = None,
        status: Callable[[HttpRequest, dict[str, Any]], str] | None = None,
        key: str = "",
        viewset: type[Any] | None = None,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if status is None:
            raise ImproperlyConfigured(
                f"A Link needs a status: the page cannot derive one for "
                f"{url_name!r} from a stash nothing writes. Pass status=."
            )
        super().__init__(title=title, key=key, viewset=viewset, url_kwargs=url_kwargs)
        self.url_name = url_name
        self.status = status

    def facts(self) -> dict[str, Any]:
        return {"title": self.title, "url_name": self.url_name, "status": self.status}

    def bound(self, key: str, viewset: type[Any] | None = None) -> Entry:
        return Link(
            cast(str, self.url_name),
            title=self.title,
            status=self.status,
            key=key,
            viewset=viewset,
            url_kwargs=self.url_kwargs,
        )


class TaskList:
    """What a task list is: its entries, in order. A value, not a view."""

    #: The entries this class and its bases declare, in definition order.
    entries: dict[str, Entry] = {}
    #: The viewset that mounts this list, once one does.
    viewset: type[TaskListViewSet] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own: dict[str, Entry] = {}
        for name, entry in cls.__dict__.items():
            if not isinstance(entry, Entry):
                continue
            key = entry.key or name
            if key in own:
                raise ImproperlyConfigured(
                    f"{cls.__name__} declares two entries under the key {key!r}. "
                    "An explicit key= must not collide with another entry's."
                )
            own[key] = entry
        cls.entries = {**cls.entries, **own}
        cls.viewset = None

    @classmethod
    def mount(cls, viewset: type[TaskListViewSet]) -> None:
        """Record the viewset that mounts this list — the first one. A
        subclass of it (one that swaps a store, a test's refinement) is the
        same page and changes nothing; a second, unrelated viewset would
        leave `begin()` with two pages to choose from, so it is refused."""
        if cls.viewset is None:
            cls.viewset = viewset
        elif not issubclass(viewset, cls.viewset):
            raise ImproperlyConfigured(
                f"{cls.__name__} is already mounted by {cls.viewset.__name__}; "
                f"{viewset.__name__} cannot mount it too. One list, one page — "
                "declare a second TaskList for a second page."
            )

    @classmethod
    def mounted(cls) -> type[TaskListViewSet]:
        if cls.viewset is None:
            raise ImproperlyConfigured(
                f"{cls.__name__} is not mounted: no TaskListViewSet declares "
                f"task_list = {cls.__name__}, so it has no page to begin a journey on."
            )
        return cls.viewset

    @classmethod
    def begin(
        cls, request: HttpRequest, journey: str | None = None, **url_kwargs: Any
    ) -> Journey:
        """Begin a journey on this list — see `TaskListViewSet.begin()`:

        journey = GrantApplication.begin(request)
        journey.finish("setup", run)
        return redirect(journey.url)
        """
        return cls.mounted().begin(request, journey, **url_kwargs)


# --- what the page renders ---------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One entry as rendered: what it is called, how far it has got, and
    where its link goes. `entry` is the underlying `Entry`, so a template
    that needs the viewset or the key can still reach them."""

    entry: Entry
    status: str
    title: StrOrPromise
    status_label: StrOrPromise
    url: str

    @property
    def key(self) -> str:
        return self.entry.key

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
        """Whether the user cannot start this section yet. A blocked row's
        link is refused at the door, so it is the one status where the row
        and the door have to agree."""
        return self.status == BLOCKED


@dataclass(frozen=True)
class TaskListPage:
    """The task list as rendered: its rows, and how far the whole page has
    got. What the heading and the final submit button both read.

    The counts are the reason this exists. "You have completed 2 of 5
    sections" is the task list pattern, and deriving it in the view means
    asking for the rows a second time. `rows` is built once and counted
    here.
    """

    rows: tuple[Row, ...]
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
        """How many have not — a section the user cannot start yet included,
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
    """What a section's run and a task list have in common: being on a
    journey.

    A journey is one record — `journey_store_class(context, journey)` — and
    every entry reads the same one, so a section nested two groups down
    still reads `store.data` written at the top. Nesting is a key namespace,
    not a second store: a group with a `key` prefixes it onto every entry it
    lists.
    """

    request: HttpRequest
    kwargs: dict[str, Any]

    #: The key this entry finishes under in the journey's store — the full
    #: key, prefix included. `None` for a root task list.
    key: str | None = None
    #: The page finishing returns to — the parent's `url_name`. `None` for
    #: a root task list.
    task_list_url_name: str | None = None
    #: One store class for the whole tree. The collection store is the
    #: journey store plus an item registry, so it serves a list with no
    #: add-another entries just as well, and one class means every entry
    #: of the tree reads the same record.
    journey_store_class: type[Any] = SessionCollectionStore
    #: Which journey this entry belongs to. Read off the URL when mounted
    #: under a `<journey>` segment (`journey_url_kwarg`), otherwise this fixed
    #: one — a list that keeps one journey per session.
    journey: str = "default"
    journey_url_kwarg = "journey"
    #: What joins a group's prefix to an entry's key — and an add-another
    #: entry's key to an item's id.
    key_separator = ":"

    def compose_key(self, prefix: str, key: str) -> str:
        return f"{prefix}{self.key_separator}{key}"

    @property
    def is_nested(self) -> bool:
        """Whether something above lists this — the difference between a
        submit that ends the journey and one that returns to the parent."""
        return self.task_list_url_name is not None

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

    def get_tasklist_url(self) -> str:
        """Where finishing sends the user back to: the page above, under the
        URL kwargs `get_tasklist_url_kwargs()` supplies."""
        if self.task_list_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set task_list_url_name (or override get_tasklist_url) on {name}."
            )
        return reverse(self.task_list_url_name, kwargs=self.get_tasklist_url_kwargs())

    @abstractmethod
    def get_tasklist_url_kwargs(self) -> dict[str, Any]:
        """The URL kwargs the page above is reversed with."""

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Refuse every request once the journey has been submitted.

        A tombstone has no runs and no stashes, so a page rendering it
        would show every section as not started, and a section re-opened
        after submission would stash into it. One store read per request
        buys the guarantee that a submitted journey can never be answered
        again. A group or a section sends the user up; only the root says
        what a submitted journey looks like.
        """
        store = self.get_journey_store()
        if store.is_complete():
            if self.is_nested:
                return redirect(self.get_tasklist_url())
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
        """Whether this entry is listed but not open to the user yet — the
        row reads *Cannot start yet* and the door refuses it. One read of
        the journey's store; `False` by default. A classmethod because the
        page asks before any instance exists, exactly as it asks `begin()`
        and `inspect()`: the point of the question is that there must not
        be a run."""
        return False

    @classmethod
    def hidden(cls, store: JourneyStore) -> bool:
        """Whether this entry should not be listed for this request at all
        — not in the rows, not in the counts, its door refusing a stale
        link. One read of the store; `False` by default."""
        return False


class SectionViewSet(JourneyScoped, WizardViewSet):
    """The viewset a task list runs a section with.

    A `Section(wizard)` gets one built for it. A section with behaviour
    declares its own subclass and puts that in the slot instead:

        class ProjectSection(SectionViewSet):
            wizard = project

            def run_done(self, run):
                record_amount(self.get_journey_store(), run)
                return super().run_done(run)

            @classmethod
            def hidden(cls, store): ...

    Re-opening a completed section and fixing one answer walks to the end
    and fires `done()` again. That is the intended "edit and re-save"
    semantics, which is why the bookkeeping here is idempotent and
    `run_done()` is what runs once per edit.
    """

    task_list_viewset: type[TaskListViewSet] | None = None
    label: str | None = None

    def get_key(self) -> str:
        if self.key is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no section to register as finished: its key is unset."
            )
        return self.key

    def get_label(self) -> str:
        """The label stamped into this section's stash — the declared label,
        otherwise the key."""
        if self.label is None:
            return self.default_label()
        return self.label

    def default_label(self) -> str:
        return self.get_key()

    def get_tasklist_url_kwargs(self) -> dict[str, Any]:
        return self.get_url_kwargs()

    def done(self, run: Run) -> HttpResponseBase:
        """Record the section as finished, then hand off to `run_done()`.

        The stash is taken first because it can only be taken at all while
        the run's state is readable — completion tears that down after
        `done()` returns. The run id is cleared after `run_done()` returns:
        a `run_done()` that raises leaves the section resumable rather than
        stranded with a stash and no way back to the run that made it.
        """
        key = self.get_key()
        store = self.get_journey_store()
        store.put_stash(key, run.stash(label=self.get_label()))
        self.run_recorded(run, store, key)
        response = self.run_done(run)
        store.clear_run(key)
        return response

    def run_recorded(self, run: Run, store: JourneyStore, key: str) -> None:
        """The library's own bookkeeping alongside the stash, inside the
        window where the run's answers are still readable. A plain section
        records nothing; an item caches its title."""

    def run_done(self, run: Run) -> HttpResponseBase:
        """What this section does when it finishes, beyond being recorded.
        The run is still readable here and torn down after, so anything
        another section's `blocked()` or `hidden()` needs to know is read
        off the path now and written to `store.data`, once. The default
        sends the user back to the task list."""
        return redirect(self.get_tasklist_url())


# --- the page ----------------------------------------------------------------


def class_name_for(key: str, suffix: str) -> str:
    words = re.split(r"[^0-9a-zA-Z]+", key)
    return "".join(word.capitalize() for word in words if word) + suffix


class TaskListViewSet(JourneyScoped, TemplateView):
    """The page listing a `TaskList`'s entries, and the door into each.

    Set `task_list` and `url_name`. The entries, their viewsets, their keys,
    their return URLs and the whole URL tree beneath the page are built
    when the class is created. A `Group`'s page becomes a subclass of
    *this* class, so an override here — a status label, a title rule,
    `stash_unusable()` — applies to the whole tree. `journey_done()` and
    `submitted()` are the root's alone.

    `storage_class` and `journey_store_class` set here reach every entry.
    """

    task_list: type[TaskList] | None = None
    #: The run storage every section of this tree uses.
    storage_class: StorageClass = SessionStorage
    #: The template this list's sections render with when their `Wizard`
    #: carries none of its own.
    section_template_name: str | None = None
    #: The base every add-another page in this tree is built on; `None`
    #: means `gandalf.add_another.AddAnotherViewSet`.
    add_another_viewset_class: type[Any] | None = None
    #: The entries, bound to their keys and viewsets.
    entries: list[Entry] = []
    #: Where the `TaskListPage` lands in the template context. `None`
    #: publishes nothing, for a page with a context object of its own.
    page_context_name: str | None = "task_list"
    entry_url_name: str | None = None
    entry_url_kwarg = "entry"
    url_name: str | None = None
    #: `(url segment, patterns)` per entry mounted beneath the page.
    _routes: list[tuple[str, list[URLPattern | URLResolver]]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.declared_entries() is not None and cls.url_name is not None:
            cls.materialise()
        # A root viewset is the list's way into a journey; a group's page
        # (built below, with a key) is reached only through its root.
        if cls.task_list is not None and cls.key is None:
            cls.task_list.mount(cls)

    @classmethod
    def declared_entries(cls) -> dict[str, Entry] | None:
        return None if cls.task_list is None else cls.task_list.entries

    # --- from declaration to classes --------------------------------------

    @classmethod
    def materialise(cls) -> None:
        """Build the entries and the viewsets that run them.

        Runs when a subclass with a task list and a `url_name` is created —
        a root written by the app, or a group's page built here — and
        again on any further subclass, so one that swaps `storage_class`
        or `journey_store_class` gets entries on the same stores.
        """
        declared = cls.declared_entries()
        assert declared is not None
        cls.entry_url_name = f"{cls.url_name}-entry"
        entries: list[Entry] = []
        routes: list[tuple[str, list[URLPattern | URLResolver]]] = []
        for key, entry in declared.items():
            bound, patterns = cls.materialise_entry(key, entry)
            entries.append(bound)
            if patterns is not None:
                routes.append((key, patterns))
        cls.entries = entries
        cls._routes = routes

    @classmethod
    def materialise_entry(
        cls, key: str, entry: Entry
    ) -> tuple[Entry, list[URLPattern | URLResolver] | None]:
        prefix = cls.key
        full_key = key if prefix is None else f"{prefix}{cls.key_separator}{key}"
        url_name = f"{cls.url_name}-{key}"
        if isinstance(entry, Link):
            return entry.bound(key), None
        viewset: type[Any]
        patterns: list[URLPattern | URLResolver]
        if isinstance(entry, Group):
            viewset = cls.build_group(key, entry, full_key, url_name)
            patterns = viewset.urls()
        elif isinstance(entry, AddAnother):
            viewset = cls.build_add_another(key, entry, full_key, url_name)
            patterns = viewset.urls()
        elif isinstance(entry, Section):
            viewset = cls.build_section(key, entry, full_key, url_name)
            patterns = cls.door_first(key, viewset.urls())
        else:
            raise ImproperlyConfigured(
                f"{type(entry).__name__} is not a kind of entry a task list can list."
            )
        return entry.bound(key, viewset), patterns

    @classmethod
    def scoped_attrs(cls, url_name: str) -> dict[str, Any]:
        """What every generated viewset of this tree shares: its URL name,
        the page it returns to, and the journey and stores it is on."""
        return {
            "__module__": cls.__module__,
            "url_name": url_name,
            "task_list_url_name": cls.url_name,
            "task_list_viewset": cls,
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
        if cls.section_template_name is not None and all(
            getattr(base, "template_name", None) is None for base in bases
        ):
            attrs["template_name"] = cls.section_template_name
        return attrs

    @classmethod
    def check_reopen_at(cls, key: str, entry: Entry, wizard: WizardLike | None) -> None:
        """Refuse a `reopen_at` naming a step the entry's wizard does not
        declare. A misspelt step name would not fail: a step URL is a claim,
        so the section would quietly re-open wherever the run happened to
        be. Checked against the declaration, so a step on an arm not taken
        is fine; skipped for a wizard the declaration cannot see — one an
        `.expand()` grows, or one built per request in `get_wizard()`."""
        if entry.reopen_at is None:
            return
        if isinstance(wizard, type):
            wizard = getattr(wizard, "wizard", None)
        if wizard is None:
            return
        declared = declared_step_names(wizard)
        if declared is None or entry.reopen_at in declared:
            return
        raise ImproperlyConfigured(
            f"{cls.__name__}.{key} re-opens at {entry.reopen_at!r}, a step its "
            f"wizard does not declare. Declared steps: {', '.join(sorted(declared))}."
        )

    @classmethod
    def build_section(
        cls, key: str, entry: Section, full_key: str, url_name: str
    ) -> type[SectionViewSet]:
        cls.check_reopen_at(key, entry, entry.wizard)
        bases = cls.wizard_bases(entry.wizard, SectionViewSet)
        attrs = {
            **cls.scoped_attrs(url_name),
            **cls.wizard_attrs(entry.wizard, bases),
            "key": full_key,
            "label": entry.label,
        }
        return type(class_name_for(key, "SectionViewSet"), bases, attrs)

    @classmethod
    def build_add_another(
        cls, key: str, entry: AddAnother, full_key: str, url_name: str
    ) -> type[AddAnotherViewSet]:
        from gandalf.add_another import AddAnotherViewSet

        cls.check_reopen_at(key, entry, entry.wizard)
        attrs = {
            **cls.scoped_attrs(url_name),
            "add_another": entry,
            "key": full_key,
            "section_template_name": cls.section_template_name,
        }
        base = cls.add_another_viewset_class or AddAnotherViewSet
        return type(class_name_for(key, "AddAnotherViewSet"), (base,), attrs)

    @classmethod
    def build_group(
        cls, key: str, entry: Group, full_key: str, url_name: str
    ) -> type[TaskListViewSet]:
        """A group's page is a subclass of this one — its hooks apply — over
        the group's own entries and template."""
        assert entry.task_list is not None
        attrs = {
            **cls.scoped_attrs(url_name),
            "task_list": entry.task_list,
            "key": full_key,
            "section_template_name": cls.section_template_name,
            "template_name": entry.template_name or cls.template_name,
        }
        return type(class_name_for(key, "ViewSet"), (cls,), attrs)

    @classmethod
    def door_first(
        cls, key: str, patterns: list[URLPattern]
    ) -> list[URLPattern | URLResolver]:
        """A section's routes with its bare start URL replaced by the page's
        door for it. A run whose every answer validates completes on a GET,
        so the one URL that must never be linked is the one a
        `WizardViewSet` publishes first; here it opens the section through
        the page instead, under the wizard's own URL name."""
        start, *rest = patterns
        door = path(
            "", cls.as_view(), kwargs={cls.entry_url_kwarg: key}, name=start.name
        )
        return [door, *rest]

    @classmethod
    def urls(cls) -> list[URLPattern | URLResolver]:
        """The page, every entry beneath it, and the door. The door comes
        last so an entry's own segment — a group's page, an add-another
        page — is reached directly."""
        if cls.url_name is None:
            raise ImproperlyConfigured(
                f"{cls.__name__}.urls() requires url_name to be set."
            )
        view = cls.as_view()
        patterns: list[URLPattern | URLResolver] = [path("", view, name=cls.url_name)]
        for key, routes in cls._routes:
            patterns.append(path(f"{key}/", include(routes)))
        patterns.append(
            path(f"<slug:{cls.entry_url_kwarg}>/", view, name=f"{cls.url_name}-entry")
        )
        return patterns

    @classmethod
    def viewset_for(cls, key: str) -> type[Any]:
        """The generated viewset behind one entry, for a test or a driver
        that needs to address it directly."""
        for entry in cls.entries:
            if entry.key == key and entry.viewset is not None:
                return entry.viewset
        raise EntryNotFound(key)

    @classmethod
    def begin(
        cls, request: HttpRequest, journey: str | None = None, **url_kwargs: Any
    ) -> Journey:
        """Begin a journey on this page and hand back a `Journey`: its id,
        its store, the page's URL, and `finish()` for recording a run as
        one of the sections — the whole of what a start wizard needs:

            def done(self, run):
                journey = GrantApplication.begin(self.request)
                journey.finish("setup", run)
                return redirect(journey.url)

        Nothing about it needs a wizard: an "apply again" link, a command
        or an agent begins one the same way. `journey` is made up when not
        given; `url_kwargs` are the page's mount-prefix kwargs, if any.
        """
        return Journey(cls, request, journey or uuid.uuid4().hex, url_kwargs)

    # --- this page's place on the journey -------------------------------------

    def get_key(self) -> str | None:
        """The prefix this page keys its entries under, or `None` at the
        root."""
        return self.key

    def full_key(self, entry: Entry) -> str:
        """An entry's key in the journey's store: its own key, prefixed by
        this page's when this page is a group. The one place nesting is
        spelled out."""
        prefix = self.get_key()
        if prefix is None:
            return entry.key
        return self.compose_key(prefix, entry.key)

    def stash_label(self, entry: Entry) -> str:
        """The label an entry's stash is expected to carry: its declared
        `label`, otherwise its full key."""
        return self.full_key(entry) if entry.label is None else entry.label

    @classmethod
    def status_for(cls, request: HttpRequest, url_kwargs: dict[str, Any]) -> str:
        """This page's status as a row on the page above it — its own rows',
        read off the same record. Costs this page's rows' storage reads,
        and still no walk."""
        view = cls()
        view.setup(request, **url_kwargs)
        return view.get_page().status

    @staticmethod
    def is_group(entry: Entry) -> bool:
        return entry.viewset is not None and issubclass(entry.viewset, TaskListViewSet)

    # --- the entries this page lists ------------------------------------------

    def get_declaration(self) -> type[TaskList]:
        if self.task_list is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no entries to list. Set {name}.task_list to a "
                f"TaskList, or override {name}.get_entries()."
            )
        return self.task_list

    def get_entries(self) -> list[Entry]:
        """The entries this page lists, in the order they are shown.
        Override to choose among them per request — by user, by plan, by
        flag."""
        self.get_declaration()
        return list(self.entries)

    def _vetted_entries(self) -> list[Entry]:
        """`get_entries()` minus the entries hidden for this request, once
        per request. Hiding here is what makes a hidden entry *gone*: not in
        the rows, not in the counts, and unknown to the door."""
        if not hasattr(self, "_entries_cache"):
            store = self.get_journey_store()
            self._entries_cache = [
                entry
                for entry in self.get_entries()
                if not self.entry_hidden(entry, store)
            ]
        return self._entries_cache

    def get_entry(self, key: str) -> Entry:
        for entry in self._vetted_entries():
            if entry.key == key:
                return entry
        raise EntryNotFound(key)

    def entry_url_kwargs(self, entry: Entry) -> dict[str, Any]:
        """The URL kwargs an entry's own URLs take: the page's — its mount
        prefix and its journey — plus the entry's own."""
        return {**self.get_page_url_kwargs(), **entry.url_kwargs}

    def entry_viewset(self, entry: Entry) -> type[WizardViewSet]:
        return cast("type[WizardViewSet]", entry.viewset)

    # --- the page -------------------------------------------------------------

    def get_page(self) -> TaskListPage:
        rows = tuple(self.get_rows())
        status = self.get_page_status(rows)
        return TaskListPage(
            rows=rows, status=status, status_label=self.get_status_label(status)
        )

    def get_page_status(self, rows: tuple[Row, ...]) -> str:
        """Complete when every row is; not started when none has been
        touched (a locked row counts as untouched); incomplete between."""
        if rows and all(row.is_complete for row in rows):
            return COMPLETE
        if all(row.is_not_started or row.is_blocked for row in rows):
            return NOT_STARTED
        return INCOMPLETE

    def get_rows(self) -> list[Row]:
        if not hasattr(self, "_rows_cache"):
            self._rows_cache = self.build_rows()
        return self._rows_cache

    def build_rows(self) -> list[Row]:
        store = self.get_journey_store()
        return [self.build_row(entry, store) for entry in self._vetted_entries()]

    def build_row(self, entry: Entry, store: JourneyStore) -> Row:
        status = self.get_entry_status(entry, store)
        return Row(
            entry=entry,
            status=status,
            title=self.get_entry_title(entry),
            status_label=self.get_status_label(status),
            url=self.get_entry_url(entry),
        )

    def get_entry_status(self, entry: Entry, store: JourneyStore) -> str:
        """In precedence order: a link's own status; blocked; a group's
        rows; a stash (complete); a run (incomplete); nothing (not started).
        Blocked outranks a stash so a section whose prerequisite was
        withdrawn after it was answered reports what the user can do now."""
        if entry.status is not None:
            return entry.status(self.request, self.entry_url_kwargs(entry))
        if self.entry_blocked(entry, store):
            return BLOCKED
        if self.is_group(entry):
            group = cast("type[TaskListViewSet]", entry.viewset)
            return group.status_for(self.request, self.entry_url_kwargs(entry))
        if store.has_stash(self.full_key(entry)):
            return COMPLETE
        if self.get_entry_state(entry, store):
            return INCOMPLETE
        return NOT_STARTED

    def entry_blocked(self, entry: Entry, store: JourneyStore) -> bool:
        """Whether the user cannot start this entry yet: its viewset's
        `blocked()`. Override for a rule spanning rows, or one that needs
        the request."""
        gate = getattr(entry.viewset, "blocked", None)
        return gate is not None and bool(gate(store))

    def entry_hidden(self, entry: Entry, store: JourneyStore) -> bool:
        """Whether this entry should not be listed for this request: its
        viewset's `hidden()`."""
        gate = getattr(entry.viewset, "hidden", None)
        return gate is not None and bool(gate(store))

    def get_entry_state(self, entry: Entry, store: JourneyStore) -> State:
        run_id = store.get_run(self.full_key(entry))
        if run_id is None:
            return []
        storage = self.entry_viewset(entry).storage_class(
            WizardContext.from_request(self.request)
        )
        try:
            return storage.get_state(run_id)
        except RunNotFound:
            return []

    def get_entry_title(self, entry: Entry) -> StrOrPromise:
        if entry.title is not None:
            return entry.title
        return capfirst(entry.key.replace("_", " ").replace("-", " "))

    def get_status_label(self, status: str) -> StrOrPromise:
        """The status as display text. Override for your own wording."""
        return {
            NOT_STARTED: gettext("Not started"),
            INCOMPLETE: gettext("Incomplete"),
            COMPLETE: gettext("Complete"),
            BLOCKED: gettext("Cannot start yet"),
        }[status]

    def get_entry_url(self, entry: Entry) -> str:
        """Where a row links: a group's own page, a link's target, or the
        door for a section — never the section's run."""
        if self.is_group(entry):
            return reverse(
                cast(str, getattr(entry.viewset, "url_name")),
                kwargs=self.entry_url_kwargs(entry),
            )
        if entry.url_name is not None:
            return reverse(entry.url_name, kwargs=self.entry_url_kwargs(entry))
        if self.entry_url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set entry_url_name (or override get_entry_url) on {name}."
            )
        return reverse(
            self.entry_url_name,
            kwargs={**self.get_page_url_kwargs(), self.entry_url_kwarg: entry.key},
        )

    def get_page_url_kwargs(self) -> dict[str, Any]:
        """This page's own URL kwargs: everything the request captured but
        the door's segment."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        return {
            key: value
            for key, value in url_kwargs.items()
            if key != self.entry_url_kwarg
        }

    def get_page_url(self) -> str:
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_page_url) on {name}."
            )
        return reverse(self.url_name, kwargs=self.get_page_url_kwargs())

    def get_tasklist_url_kwargs(self) -> dict[str, Any]:
        return self.get_page_url_kwargs()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        if self.page_context_name is not None:
            context[self.page_context_name] = self.get_page()
        return context

    # --- the door -------------------------------------------------------------

    def enter(self, entry: Entry) -> str | None:
        """The URL to send the user into an entry at, or `None` when there
        is nowhere to send them: a link, a section they cannot start yet,
        or a `stash_unusable()` that declined to name a destination.

        Resume before reopen. Reversed, a completed section under edit
        would resurrect a second run on every click and the user's
        in-flight edits would become unreachable.
        """
        if entry.viewset is None:
            return None
        store = self.get_journey_store()
        if self.get_entry_status(entry, store) == BLOCKED:
            return None
        if self.is_group(entry):
            return self.get_entry_url(entry)
        resumed = self.resume_section(entry, store)
        if resumed is not None:
            return resumed.entry_url()
        try:
            reopened = self.reopen_section(entry, store)
        except InvalidStash as error:
            return self.stash_unusable(entry, error)
        if reopened is not None:
            store.set_run(self.full_key(entry), reopened.run_id)
            return reopened.entry_url(entry.reopen_at)
        started = self.start_section(entry)
        store.set_run(self.full_key(entry), started.run_id)
        return started.entry_url()

    def resume_section(self, entry: Entry, store: JourneyStore) -> Run | None:
        run_id = store.get_run(self.full_key(entry))
        if run_id is None:
            return None
        try:
            run = self.entry_viewset(entry).inspect(
                self.request, run_id, **self.entry_url_kwargs(entry)
            )
        except RunNotFound:
            return None
        if run.is_complete:
            return None
        return run

    def reopen_section(self, entry: Entry, store: JourneyStore) -> Run | None:
        try:
            payload = store.get_stash(self.full_key(entry))
        except StashNotFound:
            return None
        return self.entry_viewset(entry).reopen(
            self.request,
            payload,
            expected_label=self.stash_label(entry),
            **self.entry_url_kwargs(entry),
        )

    def start_section(self, entry: Entry) -> Run:
        return self.entry_viewset(entry).begin(
            self.request, **self.entry_url_kwargs(entry)
        )

    def stash_unusable(self, entry: Entry, error: InvalidStash) -> str | None:
        """A completed section whose stash no longer fits its wizard. Raises
        by default; override to discard it and start over, say."""
        raise error

    def entry_unavailable(self, key: str) -> HttpResponse:
        """A door that cannot open — an unknown, hidden or blocked entry.
        Back to the page."""
        return redirect(self.get_page_url())

    # --- the journey ----------------------------------------------------------

    def submit(self) -> HttpResponseBase:
        """Press the page's button. Refused unless every row is complete;
        then `group_done()` for a group, or `journey_done()` and the
        tombstone for the root."""
        page = self.get_page()
        if not page.is_complete:
            return self.page_incomplete(page)
        store = self.get_journey_store()
        if self.is_nested:
            return self.group_done(page, store)
        response = self.journey_done(page, store)
        store.complete()
        return response

    def group_done(self, page: TaskListPage, store: JourneyStore) -> HttpResponseBase:
        """A group's Continue, every row complete: back to the parent."""
        return redirect(self.get_tasklist_url())

    def journey_done(self, page: TaskListPage, store: JourneyStore) -> HttpResponseBase:
        """The journey's work, and the one thing with no default. Runs once;
        a `journey_done()` that raises leaves every section resumable."""
        name = self.__class__.__name__
        raise ImproperlyConfigured(
            f"{name} has nothing to do when its journey is submitted. Override "
            f"{name}.journey_done() to do the work and return the response."
        )

    def page_incomplete(self, page: TaskListPage) -> HttpResponseBase:
        return redirect(self.get_page_url())

    # --- HTTP -------------------------------------------------------------------

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if kwargs.get(self.entry_url_kwarg) is not None:
            return HttpResponseNotAllowed(["GET"])
        return self.submit()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        key = kwargs.get(self.entry_url_kwarg)
        if key is None:
            return super().get(request, *args, **kwargs)
        try:
            entry = self.get_entry(key)
        except EntryNotFound:
            return self.entry_unavailable(key)
        url = self.enter(entry)
        if url is None:
            return self.entry_unavailable(key)
        return redirect(url)


class Journey:
    """A journey begun on a task list, from outside the page's own requests.

    `id` is the journey's identity, `store` its record, `url` the page for
    it. `finish()` records a finished run as one of the sections exactly as
    finishing it from the page would — stashed under the section's key and
    label, its `run_done()` run — so it arrives complete and re-openable
    like any other row.
    """

    def __init__(
        self,
        task_list_viewset: type[TaskListViewSet],
        request: HttpRequest,
        id: str,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.task_list_viewset = task_list_viewset
        self.request = request
        self.id = id
        self.url_kwargs = dict(url_kwargs or {})

    @property
    def page_kwargs(self) -> dict[str, Any]:
        """The kwargs the page is reversed with: the mount prefix and, when
        the page is mounted under a journey segment, this journey."""
        viewset = self.task_list_viewset
        kwargs = {**self.url_kwargs, viewset.journey_url_kwarg: self.id}
        try:
            reverse(cast(str, viewset.url_name), kwargs=kwargs)
        except NoReverseMatch:
            # One journey per session: no segment to put the id in.
            return self.url_kwargs
        return kwargs

    @property
    def url(self) -> str:
        return reverse(
            cast(str, self.task_list_viewset.url_name), kwargs=self.page_kwargs
        )

    @property
    def store(self) -> JourneyStore:
        return cast(
            JourneyStore,
            self.task_list_viewset.journey_store_class(
                WizardContext.from_request(self.request), self.id
            ),
        )

    def finish(self, section: str, run: Run) -> None:
        """Record `run`'s finished run as `section`."""
        view = self.task_list_viewset.viewset_for(section)()
        view.setup(self.request, **self.page_kwargs)
        view.done(run)
