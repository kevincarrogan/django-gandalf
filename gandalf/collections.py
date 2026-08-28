"""Add another: a page of same-shaped items the user grows.

Some things a journey collects are not one answer but a list of them, and the
user decides how long the list is — guests, dependants, previous addresses,
employments. Each is collected by its own run through one item wizard, and each
has to be separately resumable, separately completable and separately
destroyable.

**A collection is a hub whose sections are built rather than declared.** One
`Section` per id in an ordered registry, and everything `HubMixin` already does
— the status derivation, the row building, the resume-before-reopen door —
applies unchanged, because none of it ever cared where the list came from. Most
of what follows is a name for something the hub already knew how to do.

Two things a hub does not have.

*Completeness is declared, not derived.* A hub section is Complete when a stash
appears, because finishing is the only thing that can produce one. No amount of
reading a collection's storage can say whether the user has more guests to add
— only the user can, so the page asks, and the answer is stored.

*A row is a thing that can be destroyed.* Removing an item takes its live run,
its uploaded bytes, its stash, its cached title, whatever the application saved
for it, and its place in the registry — in that order, so a failure part-way
leaves an item that is still listed and still removable rather than one that
has vanished with its side effects intact.

Not to be confused with `Wizard.expand()`, which grows *steps* inside one run
from a count the user just gave. An expansion's answers are positional, so
deleting from the middle shifts every answer after it; and one run means there
is no such thing as a half-finished item. Use `.expand()` for "how many
children? now tell me about each"; use a collection for "add another, as many
as you like, and change your mind later".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.urls import URLPattern, path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext, gettext_lazy as _
from django.views.generic import TemplateView

from gandalf.runtime import BoundWizard
from gandalf.sections import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    Hub,
    HubMixin,
    Section,
    SectionMixin,
    SectionRow,
)
from gandalf.storage import RunNotFound, SessionCollectionStore
from gandalf.types import CollectionStore, SectionStore, StrOrPromise
from gandalf.viewsets import WizardViewSet


__all__ = [
    # Re-exported so a collection's statuses read from one import, as a hub's
    # do; they are `gandalf.sections`' and mean exactly the same thing.
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "AddAnotherForm",
    "Collection",
    "CollectionMixin",
    "CollectionRow",
    "CollectionView",
    "ItemNotFound",
    "ItemSectionMixin",
]


class ItemNotFound(LookupError):
    """Raised when an id names no item this collection's registry lists — a
    removed item, a stale link, or a URL typed by hand."""


class AddAnotherForm(forms.Form):
    """The question the whole pattern turns on.

    A real form rather than the view reading `request.POST` directly, so an
    unanswered question re-renders with an error the template already knows how
    to show, exactly as a step does.
    """

    add_another = forms.ChoiceField(
        label=_("Do you want to add another?"),
        choices=[("yes", _("Yes")), ("no", _("No"))],
        widget=forms.RadioSelect,
        error_messages={"required": _("Select yes if you want to add another")},
    )

    @property
    def wants_another(self) -> bool:
        """Whether the user asked for one more. Valid only once cleaned."""
        return bool(self.cleaned_data["add_another"] == "yes")


@dataclass(frozen=True)
class CollectionRow(SectionRow):
    """One item of a collection: what it is called, how far it has got, and
    the two links a row carries — change it, remove it.

    `title` is a *cached string*, not a computation. The item's own section
    worked it out at the moment it finished, when it had the answers and a walk
    to read them with; the row reads it back. That is what keeps a collection
    of thirty items costing thirty dict lookups rather than thirty walks — the
    same bargain a hub row strikes, paid once per item instead of once per
    render.

    An item that has never finished has no cached title and falls back to a
    positional name (`Guest 2`), which is honest: nothing it has answered is
    known to name it.
    """

    item_id: str = ""
    position: int = 0
    remove_url: str = ""


@dataclass(frozen=True)
class Collection(Hub):
    """The collection as a whole: its items, and how far the whole thing has
    got. What the page's heading and a parent hub's row both read.

    A `Hub`, because that is what a collection is. The rows, the status and
    the counts — `count`, `completed`, `remaining`, `blocked` — are the hub's
    own and mean here exactly what they mean there, so "you have added 3
    guests, 2 of them finished" costs no loop in the template and cannot drift
    from what a task list would say about the same rows.

    What it adds is what a hub has no notion of: where the page is (`key`,
    `url`), whether the user has said there are no more to add, and how many
    there have to be before that answer can finish the page. `min_items` is
    here rather than left on the view because a page that asks for at least
    one has to be able to *say* so, and the alternative is a template reaching
    back through the view for a class attribute.
    """

    rows: tuple[CollectionRow, ...]
    key: str
    url: str
    declared_done: bool
    min_items: int

    @property
    def is_empty(self) -> bool:
        return not self.rows


class ItemSectionMixin(SectionMixin):
    """Mix into the wizard that collects one item of a collection.

    Everything `SectionMixin` does, keyed per item instead of per class. The
    key cannot be a class attribute — there is one section per item, and the
    items are not known until the user makes them — so it comes from the URL.
    Mount this wizard under an item segment and the id reaches every request
    through `self.kwargs`, exactly as a tenant slug does:

        path("party/guest/<uuid:item>/", include(GuestItemViewSet.urls()))

    **Mount it beside the collection page, never underneath it.**
    `WizardViewSet.urls()` publishes `""` as its start URL, so a wizard mounted
    at `party/guests/<uuid:item>/` would collide with the collection's own
    door at that exact path — and whichever `include()` is listed first
    silently wins, which looks like *Change stopped working* rather than like a
    URL conflict.

    That segment is *this wizard's own mount*, not shared context, which is the
    one thing to keep straight: it belongs in every URL this wizard builds for
    itself (`get_url_kwargs()` forwards it for free, since it is not among
    `reserved_url_kwargs`) and in none of the collection's, which is why
    `get_hub_url_kwargs()` drops it. The collection page is this wizard's hub:
    `hub_url_name` names it, as it would for a plain section.

    **Items override `section_done()`, never `done()`** — `SectionMixin`'s rule
    holds here for its own reason, with one more on top: `done()` is also where
    the item's title is cached, and a section that never caches one leaves a
    page that can only ever say *Guest 1*, *Guest 2*.
    """

    dynamic_section_key = True
    section_store_class = SessionCollectionStore

    #: The collection this item belongs to — its page's `section_key`, which
    #: is the full key when the collection is itself nested under a hub.
    collection_key: str | None = None
    item_url_kwarg = "item"
    #: The step and field whose answer names an item on the collection page.
    #: Override `get_item_title()` instead when the name is not one field.
    item_title_step: str | None = None
    item_title_field: str | None = None

    def get_collection_key(self) -> str:
        if self.collection_key is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} collects items for no collection. Set "
                f"{name}.collection_key to the key its collection page uses."
            )
        return self.collection_key

    def get_item_id(self) -> str:
        """The item this request is answering, from the URL."""
        item_id = self.kwargs.get(self.item_url_kwarg)
        if item_id is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} is not mounted under an item segment, so no request "
                f"can say which item it is answering. Mount it as "
                f'path("guest/<uuid:{self.item_url_kwarg}>/", '
                f"include({name}.urls()))."
            )
        return str(item_id)

    def get_section_key(self) -> str:
        """This item's key in the shared section key space."""
        return f"{self.get_collection_key()}{self.key_separator}{self.get_item_id()}"

    def get_section_label(self) -> str:
        """The *collection's* label, not this item's key.

        The inherited default is the section key, which here carries an opaque
        per-item id — so every item would stamp a different label into its
        stash and the deploy guard would never match anything. One shape, one
        label, however many items wear it.
        """
        if self.section_label is None:
            return self.get_collection_key()
        return self.section_label

    def get_section_store(self) -> CollectionStore:
        # `section_store_class` is narrowed on this subclass; mypy reads the
        # attribute through the base's declaration.
        return cast(CollectionStore, super().get_section_store())

    def get_item_title(self, bound_wizard: BoundWizard) -> str:
        """The name this item goes by on the collection page.

        Reads `item_title_field` off the answer to `item_title_step` by
        default. Returns `""` when that step is not on the route the user
        actually took, so the row falls back to a positional name rather than
        inventing one.

        Costs one walk, once, at completion — on a request that has already
        walked twice — in exchange for no walk at all on every later render of
        this page and of any hub above it. It is `gandalf.sections`' bargain,
        moved one level down.
        """
        if self.item_title_step is None or self.item_title_field is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} cannot name its items. Set {name}.item_title_step "
                f"and {name}.item_title_field to the answer that names one, "
                f"or override {name}.get_item_title()."
            )
        step = bound_wizard.path.find_step(name=self.item_title_step)
        if step is None:
            return ""
        return str(step.form.cleaned_data.get(self.item_title_field, ""))

    def section_recorded(
        self, bound_wizard: BoundWizard, store: SectionStore, key: str
    ) -> None:
        """Cache this item's title, in the window where its answers are still
        readable."""
        title = self.get_item_title(bound_wizard)
        self.get_section_store().set_item_title(
            self.get_collection_key(), self.get_item_id(), title or None
        )

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        """The collection page is reversed without the item segment: it is
        this wizard's own mount, and the collection's URL has no place for it.
        Everything else is forwarded, so a collection under a tenant prefix is
        reached under the same one."""
        return {
            key: value
            for key, value in self.get_url_kwargs().items()
            if key != self.item_url_kwarg
        }

    def run_unavailable(
        self, bound_wizard: BoundWizard, reason: str
    ) -> HttpResponseBase:
        """Back to the collection page, not to this wizard's start URL.

        The default would reverse straight back into this item and mint a
        fresh run for it — and for an item the user has just removed, that run
        would complete and stash under a key no row lists. A removed item has
        one honest destination and it is the page it was removed from.
        """
        return redirect(self.get_hub_url())

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Refuse a request for an item the registry does not list.

        The collection's own routes check this too, but they are not the only
        way in: a start, run or step URL of this wizard addresses an item
        directly. One store read per request buys the guarantee that a run can
        never be answered for an item that no longer exists.
        """
        store = self.get_section_store()
        if not store.has_item(self.get_collection_key(), self.get_item_id()):
            return self.item_unavailable()
        return super().dispatch(request, *args, **kwargs)

    def item_unavailable(self) -> HttpResponseBase:
        """Response for an item this collection no longer lists. The default
        sends the user back to the page; override to raise `Http404`."""
        return redirect(self.get_hub_url())


class CollectionMixin(HubMixin):
    """Adds `collection` to a view's template context, and owns the four
    things a user can do to one: add an item, change one, remove one, and say
    there are no more.

    Mix into the page listing the items, or use `CollectionView`, which is this
    over a `TemplateView` with the three URL patterns already published.
    """

    section_store_class = SessionCollectionStore
    #: A collection page answers "how far has the whole thing got" with its
    #: `Collection`, whose completeness is the user's declared answer to *add
    #: another* rather than anything the rows can tell you. Publishing a `Hub`
    #: beside it would put a second, differently-derived status on the same
    #: page, so the hub's own context object is suppressed.
    hub_context_name: str | None = None
    item_viewset: type[WizardViewSet] | None = None
    item_url_kwarg = "item"
    item_label: str | None = None
    item_reopen_step: str | None = None
    item_name: StrOrPromise | None = None
    #: Items required before a declared-done collection counts as complete.
    #: Zero is right for "any other income?"; one for "add at least one".
    min_items = 0
    collection_context_name = "collection"
    form_class = AddAnotherForm
    remove_template_name: str | None = None

    # --- the items ---------------------------------------------------------

    def get_section_key(self) -> str:
        """A collection's key is never `None`: it is the prefix its items are
        registered and keyed under, whether or not a hub above lists it."""
        if self.section_key is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no collection to list. Set {name}.section_key "
                f"to the key its items are registered under."
            )
        return self.section_key

    def get_collection_key(self) -> str:
        return self.get_section_key()

    def get_collection_store(self) -> CollectionStore:
        return cast(CollectionStore, self.get_section_store())

    def get_item_viewset(self) -> type[WizardViewSet]:
        if self.item_viewset is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no wizard to collect an item with. Set "
                f"{name}.item_viewset to an ItemSectionMixin viewset."
            )
        return self.item_viewset

    def get_item_ids(self) -> list[str]:
        return self.get_collection_store().item_ids(self.get_collection_key())

    def get_item_label(self) -> str:
        """The *shape's* identity, shared by every item — see
        `ItemSectionMixin.get_section_label()`."""
        if self.item_label is None:
            return self.get_collection_key()
        return self.item_label

    def item_section_key(self, item_id: str) -> str:
        """An item's key in the journey's store — what `full_key()` composes
        for its section, and what its own wizard composes for itself."""
        return f"{self.get_collection_key()}{self.key_separator}{item_id}"

    def get_item_section(self, item_id: str) -> Section:
        """One item, as the `Section` the hub machinery already understands.

        This is the piece the reuse rests on: past here, resuming, re-opening
        and starting an item are `HubMixin`'s, unchanged. The section's key is
        the item's id, and the collection's own key is the prefix `full_key()`
        puts in front of it — exactly as a nested hub prefixes its sections.
        """
        return Section(
            key=item_id,
            viewset=self.get_item_viewset(),
            label=self.get_item_label(),
            reopen_step=self.item_reopen_step,
            url_kwargs={
                **self.get_collection_url_kwargs(),
                self.item_url_kwarg: item_id,
            },
        )

    def get_sections(self) -> list[Section]:
        """The hub's own hook, answered from the registry instead of a
        declaration."""
        return [self.get_item_section(item_id) for item_id in self.get_item_ids()]

    def get_item(self, item_id: str) -> Section:
        """The section for a listed item, raising `ItemNotFound` otherwise.

        Asks `get_item_ids()`, not the registry underneath it, so a
        collection that builds its list from somewhere else — the
        application's own records — serves exactly the items it renders.
        """
        if item_id not in self.get_item_ids():
            raise ItemNotFound(item_id)
        return self.get_item_section(item_id)

    def _validate_sections(self, sections: list[Section]) -> list[Section]:
        """The hub's checks, plus the collection's own two drift checks.

        An item viewset whose `collection_key` is not this page's
        `section_key` registers under one prefix and stashes under another,
        so a finished item never shows as complete. One whose label disagrees
        with the collection's writes stashes that the door will refuse on the
        way back in, so a completed item could never be changed. Both are the
        quiet failure the hub's key drift check exists to catch, one level
        down.
        """
        viewset = self.get_item_viewset()
        key = getattr(viewset, "collection_key", None)
        if key is not None and key != self.get_collection_key():
            raise ImproperlyConfigured(
                "A collection's item viewset must name the collection it "
                "belongs to, or its items stash under a key this page never "
                f"reads. {self.__class__.__name__} is {self.get_collection_key()!r} "
                f"and {viewset.__name__} declares collection_key={key!r}."
            )
        declared = getattr(viewset, "section_label", None)
        expected = self.get_item_label()
        if declared is not None and declared != expected:
            raise ImproperlyConfigured(
                "A collection's item label must match its item viewset's, or "
                "a re-opened item is refused at the door and can never be "
                f"changed. {self.__class__.__name__} labels items {expected!r} "
                f"and {viewset.__name__} stamps {declared!r}."
            )
        return super()._validate_sections(sections)

    @classmethod
    def status_for(cls, request: HttpRequest, url_kwargs: dict[str, Any]) -> str:
        """A collection's status on the hub above it is its own — declared by
        the user, not derived from the rows alone — so it answers with the
        `Collection`'s, which no stash key could express."""
        view = cls()
        view.setup(request, **url_kwargs)
        return view.get_collection().status

    # --- the page ----------------------------------------------------------

    def build_section_rows(self) -> list[SectionRow]:
        """The hub's own row builder, one `CollectionRow` per item.

        A collection's rows *are* its sections' rows, so `hub.rows` and
        `collection.rows` name one list and a template written for a hub reads
        a collection unchanged. `HubMixin.get_section_rows()` caches what this
        returns, so wrapping them in a `Collection` costs no second build.
        """
        store = self.get_collection_store()
        return [
            self.build_collection_row(section, store, position)
            for position, section in enumerate(self._vetted_sections())
        ]

    def get_collection(self) -> Collection:
        store = self.get_collection_store()
        key = self.get_collection_key()
        rows = tuple(cast("list[CollectionRow]", self.get_section_rows()))
        status = self.get_collection_status(rows, store)
        return Collection(
            key=key,
            url=self.get_page_url(),
            rows=rows,
            status=status,
            status_label=self.get_status_label(status),
            declared_done=store.is_declared_done(key),
            min_items=self.min_items,
        )

    def build_collection_row(
        self, section: Section, store: CollectionStore, position: int
    ) -> CollectionRow:
        item_id = self.item_id_for(section)
        status = self.get_section_status(section, store)
        return CollectionRow(
            section=section,
            status=status,
            title=self.get_item_title(item_id, store, position),
            status_label=self.get_status_label(status),
            url=self.get_section_url(section),
            item_id=item_id,
            position=position,
            remove_url=self.get_item_remove_url(item_id),
        )

    def item_id_for(self, section: Section) -> str:
        return cast(str, section.url_kwargs[self.item_url_kwarg])

    def get_item_title(
        self, item_id: str, store: CollectionStore, position: int
    ) -> StrOrPromise:
        """What names an item on the page: the title its own section cached
        when it last finished, or a positional name for one that never has."""
        title = store.get_item_title(self.get_collection_key(), item_id)
        if title:
            return title
        return self.get_placeholder_title(position)

    def get_placeholder_title(self, position: int) -> StrOrPromise:
        """The name of an item with nothing known to name it. One-based, so it
        reads as the user counts."""
        return gettext("%(name)s %(number)d") % {
            "name": self.get_item_name(),
            "number": position + 1,
        }

    def get_item_name(self) -> StrOrPromise:
        """What one item is called — `item_name`, else the collection key made
        readable and singular enough to number."""
        if self.item_name is not None:
            return self.item_name
        key = self.get_collection_key().replace("_", " ").replace("-", " ")
        return capfirst(key[:-1] if key.endswith("s") else key)

    def get_collection_status(
        self, rows: tuple[CollectionRow, ...], store: CollectionStore
    ) -> str:
        """How far the whole collection has got.

        Declaring is necessary but not sufficient. A user can answer *no more*
        while an item sits half-finished — they can only see the question from
        a page that lists it — and the honest thing to report then is
        Incomplete, not Complete over answers nobody gave.
        """
        if not store.is_declared_done(self.get_collection_key()):
            return NOT_STARTED if not rows else INCOMPLETE
        if len(rows) < self.min_items:
            return INCOMPLETE
        if any(not row.is_complete for row in rows):
            return INCOMPLETE
        return COMPLETE

    def get_collection_url_kwargs(self) -> dict[str, Any]:
        """Mount-prefix kwargs this page came in through, minus the item the
        routes own — the same arrangement `get_section_url_kwargs()` makes."""
        url_kwargs = getattr(self, "kwargs", None) or {}
        return {
            key: value
            for key, value in url_kwargs.items()
            if key != self.item_url_kwarg
        }

    def get_page_url(self) -> str:
        """This collection's own page, reversed without the item segment."""
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_page_url) on {name}."
            )
        return reverse(self.url_name, kwargs=self.get_collection_url_kwargs())

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        return self.get_collection_url_kwargs()

    def get_section_url(self, section: Section) -> str:
        """The hub's own hook: a row links to this page's door for its item."""
        return self.get_item_url(self.item_id_for(section))

    def get_item_url(self, item_id: str) -> str:
        """Where a row's *Change* link goes: this page's own door for the
        item. Never the wizard's, for the reason `HubMixin.get_section_url()`
        gives at length."""
        return self._reverse_item("item", item_id)

    def get_item_remove_url(self, item_id: str) -> str:
        return self._reverse_item("remove", item_id)

    def _reverse_item(self, suffix: str, item_id: str) -> str:
        if self.url_name is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"Set url_name (or override get_item_url) on {name}."
            )
        return reverse(
            f"{self.url_name}-{suffix}",
            kwargs={
                **self.get_collection_url_kwargs(),
                self.item_url_kwarg: item_id,
            },
        )

    def get_form_class(self) -> type[AddAnotherForm]:
        return self.form_class

    def get_form(self, data: Any = None) -> AddAnotherForm:
        return self.get_form_class()(data=data)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context[self.collection_context_name] = self.get_collection()
        context.setdefault("form", self.get_form())
        return context

    # --- the actions -------------------------------------------------------

    def new_item_id(self) -> str:
        """Identity for a new item. Opaque, never positional: removing from
        the middle must not renumber the survivors or repoint a live URL."""
        return str(uuid.uuid4())

    def add_item(self) -> str | None:
        """Register a new item, then enter its wizard.

        The registry is written *first*. That is what makes a half-finished
        item possible at all, and it is `SectionMixin.done()`'s discipline —
        write the durable fact, then do the thing that can fail. If entering
        raises, the user is left with a listed, removable, not-started row
        rather than a live run nothing points at.
        """
        store = self.get_collection_store()
        key = self.get_collection_key()
        item_id = self.new_item_id()
        store.add_item(key, item_id)
        # Pressing Add *is* the user withdrawing their answer to "any more?".
        store.set_declared_done(key, False)
        return self.enter(self.get_item_section(item_id))

    def declare_done(self) -> HttpResponseBase:
        """Record that the user has nothing more to add, and move them on."""
        self.get_collection_store().set_declared_done(self.get_collection_key(), True)
        return self.collection_done()

    def collection_done(self) -> HttpResponseBase:
        """What the collection does once the user says that is all. The
        default sends them up to the hub that lists this collection — the
        collection's `hub_done()`, in effect, without a submit of its own."""
        return redirect(self.get_hub_url())

    def remove_item(self, item_id: str) -> HttpResponse:
        """Destroy an item, pointer last.

        The exact mirror of `SectionMixin.done()`: everything reachable
        *through* the registry goes before the registry entry itself, so a
        hook that raises leaves an item still listed and still removable
        rather than one that has vanished with its side effects intact.
        Removal answers no question, so the user's *no more to add* stands.
        """
        store = self.get_collection_store()
        key = self.get_collection_key()
        section = self.get_item_section(item_id)
        self.discard_item_run(section, store)
        store.clear_run(self.full_key(section))
        store.delete_stash(self.full_key(section))
        store.set_item_title(key, item_id, None)
        self.item_removed(item_id, section, store)
        store.remove_item(key, item_id)
        return redirect(self.get_page_url())

    def discard_item_run(self, section: Section, store: CollectionStore) -> None:
        """Forget an item's live run and reclaim anything it uploaded. A run
        the storage no longer holds has already answered the question."""
        run_id = store.get_run(self.full_key(section))
        if run_id is None:
            return
        try:
            bound_wizard = self.section_viewset(section).inspect(
                self.request, run_id, **self.section_url_kwargs(section)
            )
        except RunNotFound:
            return
        bound_wizard.obliterate()

    def item_removed(
        self, item_id: str, section: Section, store: CollectionStore
    ) -> None:
        """Application work for an item going away — deleting whatever
        `section_done()` saved for it. Runs while the item is still listed, so
        raising here is recoverable."""

    def item_unavailable(self, item_id: str) -> HttpResponse:
        """Response for an id this collection lists no item for — a removed
        item, a stale link. The default sends the user back to the page;
        override to raise `Http404`."""
        return redirect(self.get_page_url())


class CollectionView(CollectionMixin, TemplateView):
    """A collection page, its door into each item, and its remove route.

    One view over three routes, for the same reason a wizard is one view over
    three: a row renders without walking anything, so it cannot know which run
    its link should resume, and the door walks exactly the one item the user
    clicked.

        class GuestCollectionView(CollectionView):
            template_name = "party/guests.html"
            remove_template_name = "party/remove_guest.html"
            url_name = "party-guests"
            section_key = "guests"
            item_viewset = GuestItemViewSet
            hub_url_name = "party-hub"

    Mount it beside its item wizard, never above it:

        path("party/guests/", include(GuestCollectionView.urls())),
        path("party/guest/<uuid:item>/", include(GuestItemViewSet.urls())),

    `HubView` is deliberately not in the ancestry: its two patterns and its
    GET-only door are precisely the two things a collection replaces.
    """

    @classmethod
    def urls(cls) -> list[URLPattern]:
        """URL patterns for this collection, derived from `url_name`:
        `<url_name>` (the page — GET lists, POST answers *add another*),
        `<url_name>-item` (the door into one item) and `<url_name>-remove`
        (confirm on GET, remove on POST).

        The item kwarg is a `uuid`, not a slug, which is what lets `remove/`
        be a safe sibling — a slug would swallow it, and every verb after it.
        """
        if cls.url_name is None:
            raise ImproperlyConfigured(
                "CollectionView.urls() requires url_name to be set."
            )
        view = cls.as_view()
        return [
            path("", view, name=cls.url_name),
            path(f"<uuid:{cls.item_url_kwarg}>/", view, name=f"{cls.url_name}-item"),
            path(
                f"<uuid:{cls.item_url_kwarg}>/remove/",
                view,
                name=f"{cls.url_name}-remove",
            ),
        ]

    def _item_id(self) -> str | None:
        item_id = self.kwargs.get(self.item_url_kwarg)
        return None if item_id is None else str(item_id)

    def _is_remove(self) -> bool:
        return self.request.resolver_match is not None and (
            self.request.resolver_match.url_name == f"{self.url_name}-remove"
        )

    def get_template_names(self) -> list[str]:
        if self._is_remove():
            if self.remove_template_name is None:
                name = self.__class__.__name__
                raise ImproperlyConfigured(
                    f"Set {name}.remove_template_name to the page that asks "
                    f"the user to confirm removing an item."
                )
            return [self.remove_template_name]
        return super().get_template_names()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        item_id = self._item_id()
        if item_id is None:
            return super().get(request, *args, **kwargs)
        try:
            section = self.get_item(item_id)
        except ItemNotFound:
            return self.item_unavailable(item_id)
        if self._is_remove():
            return self.render_to_response(self.get_context_data(row=self.row(item_id)))
        # Entering yields a step URL for any item this collection lists —
        # every one has a viewset, so the only arm that declines is a
        # `section_blocked()` an app has overridden to gate its items.
        url = self.enter(section)
        if url is None:
            return self.item_unavailable(item_id)
        return redirect(url)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        item_id = self._item_id()
        if item_id is not None:
            # Which route, not merely which id. Two patterns carry an item and
            # only one of them destroys anything, so branching on the id alone
            # made a POST to the *door* remove the item it was meant to open —
            # a form posting to the URL its own row links to, and nothing to
            # say the answer had gone. `get_template_names()` already tells the
            # two apart; the verb has to agree with it.
            if not self._is_remove():
                return HttpResponseNotAllowed(["GET"])
            try:
                self.get_item(item_id)
            except ItemNotFound:
                return self.item_unavailable(item_id)
            return self.remove_item(item_id)
        form = self.get_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        if form.wants_another:
            # `add_item()` registers before it enters, so a gated collection
            # leaves the user a listed, removable, not-started row and the
            # page it was pressed from — the same bargain the docstring there
            # strikes with an entry that raises.
            url = self.add_item()
            if url is None:
                return redirect(self.get_page_url())
            return redirect(url)
        return self.declare_done()

    def row(self, item_id: str) -> CollectionRow:
        """The one row a confirmation page is about, built rather than
        searched for — `get_item()` has already vouched for the id."""
        return self.build_collection_row(
            self.get_item_section(item_id),
            self.get_collection_store(),
            self.get_item_ids().index(item_id),
        )
