"""Add another: a collection of items the user grows, one wizard per item.

A collection is a hub whose members are *built* rather than declared — one
per id in an ordered registry the user grows — so everything a hub does
applies unchanged: the status derivation, the resume-before-reopen door,
the guarantee that no row ever links a bare run URL. What it adds is the
page pattern itself: a list of what has been added with **Change** and
**Remove** on each row, an **Add another** question, and one item wizard
behind all of them.

Declared as a value, like a hub:

    budget = Collection(
        budget_line,
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
        template_name="apply/budget.html",
        remove_template_name="apply/budget_remove.html",
    )

and either listed on a hub — `Hub().collection("budget", budget, title=
"Budget")`, which mounts it beneath the hub — or mounted on its own:

    class VehiclesViewSet(CollectionViewSet):
        url_name = "vehicles"
        member_key = "vehicles"
        collection = vehicles
        hub_url_name = "quote"   # where Continue goes

Completeness is declared, not derived: no reading of storage can say
whether the user has more to add, so the page asks, and the answer is kept
in the collection store beside the registry. An item is a uuid, never a
position: remove one from the middle and the rest keep their ids, their
URLs and their answers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, cast

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect
from django.urls import URLPattern, URLResolver, include, path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext, gettext_lazy as _

from gandalf.hubs import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    Done,
    HubPage,
    HubViewSet,
    Member,
    MemberRow,
    MemberViewSet,
    WizardLike,
    _class_name,
)
from gandalf.runtime import BoundWizard
from gandalf.storage import RunNotFound
from gandalf.types import CollectionStore, JourneyStore, StrOrPromise

__all__ = [
    "BLOCKED",
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "AddAnotherForm",
    "Collection",
    "CollectionPage",
    "CollectionRow",
    "CollectionViewSet",
    "ItemNotFound",
    "ItemViewSet",
]

#: What names an item on the page: the `(step, field)` whose answer does, or
#: a callable handed the finished run.
ItemTitle = tuple[str, str] | Callable[[BoundWizard], str]


class ItemNotFound(LookupError):
    """Raised when an id names no item of this collection."""


class AddAnotherForm(forms.Form):
    """The one question a collection page asks. Two submit buttons carry the
    answer, so the field needs no widget of its own on the page."""

    add_another = forms.ChoiceField(
        label=_("Do you want to add another?"),
        choices=[("yes", _("Yes")), ("no", _("No"))],
        widget=forms.RadioSelect,
        error_messages={"required": _("Select yes if you want to add another")},
    )

    @property
    def wants_another(self) -> bool:
        return bool(self.cleaned_data["add_another"] == "yes")


# --- the declaration ---------------------------------------------------------


@dataclass(frozen=True)
class Collection:
    """An immutable declaration of an "add another" list.

    `wizard` runs one item. `item_name` is what an unfinished item is
    called on the page ("Budget line 2"); `item_title` is what names a
    finished one. `min_items` is how many a declared-done collection needs
    before it counts as complete. `reopen` names the step a finished item
    re-opens at. `label` is the stash's shape-identity for every item; bump
    it when a deploy reshapes the item wizard. `done` runs when an item
    finishes. The two templates are the page and the remove confirmation.
    """

    wizard: WizardLike
    item_name: StrOrPromise | None = None
    item_title: ItemTitle | None = None
    min_items: int = 0
    reopen: str | None = None
    label: str | None = None
    done: Done | None = None
    template_name: str | None = None
    remove_template_name: str | None = None


# --- what the page renders ---------------------------------------------------


@dataclass(frozen=True)
class CollectionRow(MemberRow):
    """One item: a member row that also knows its id, its position, and
    where to remove it."""

    item_id: str = ""
    position: int = 0
    remove_url: str = ""


@dataclass(frozen=True)
class CollectionPage(HubPage):
    """The collection as rendered: its rows, and whether the user has said
    there are no more. `status` is derived from both."""

    rows: tuple[CollectionRow, ...]
    key: str
    url: str
    declared_done: bool
    min_items: int

    @property
    def is_empty(self) -> bool:
        return not self.rows


# --- one item ------------------------------------------------------------------


class ItemViewSet(MemberViewSet):
    """The viewset a collection runs one item with. Built by
    `CollectionViewSet` from the declaration and mounted under
    `<uuid:item>/` beneath the page, so one class serves every row."""

    collection_key: str | None = None
    item_url_kwarg = "item"
    item_title: ItemTitle | None = None

    def get_collection_key(self) -> str:
        if self.collection_key is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} collects items for no collection."
            )
        return self.collection_key

    def get_item_id(self) -> str:
        item_id = self.kwargs.get(self.item_url_kwarg)
        if item_id is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} is not mounted under an item segment, so no request "
                f"can say which item it is answering."
            )
        return str(item_id)

    def get_member_key(self) -> str:
        return self.compose_key(self.get_collection_key(), self.get_item_id())

    def default_member_label(self) -> str:
        """Items share the collection's label: a per-item id would never
        match anything on the way back in."""
        return self.get_collection_key()

    def get_journey_store(self) -> CollectionStore:
        return cast(CollectionStore, super().get_journey_store())

    def get_item_title(self, bound_wizard: BoundWizard) -> str:
        """The name this item goes by on the page, read off the finished
        run: `item_title`'s field, or its callable. A step that is not on
        the route the user took names nothing, and the page falls back to a
        positional name rather than inventing one."""
        if self.item_title is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} cannot name its items. Declare the collection with "
                f"item_title=(step, field), or a callable of the finished run."
            )
        if callable(self.item_title):
            return str(self.item_title(bound_wizard))
        step_name, field_name = self.item_title
        step = bound_wizard.path.find_step(name=step_name)
        if step is None:
            return ""
        return str(step.form.cleaned_data.get(field_name, ""))

    def run_recorded(
        self, bound_wizard: BoundWizard, store: JourneyStore, key: str
    ) -> None:
        title = self.get_item_title(bound_wizard)
        cast(CollectionStore, store).set_item_title(
            self.get_collection_key(), self.get_item_id(), title or None
        )

    def get_hub_url_kwargs(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.get_url_kwargs().items()
            if key != self.item_url_kwarg
        }

    def run_unavailable(
        self, bound_wizard: BoundWizard, reason: str
    ) -> HttpResponseBase:
        return redirect(self.get_hub_url())

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """An item that is not on the registry — removed, or never added —
        has no page to be on, whatever run its URL names."""
        store = self.get_journey_store()
        if not store.has_item(self.get_collection_key(), self.get_item_id()):
            return self.item_unavailable()
        return super().dispatch(request, *args, **kwargs)

    def item_unavailable(self) -> HttpResponseBase:
        return redirect(self.get_hub_url())


# --- the page ----------------------------------------------------------------


class CollectionViewSet(HubViewSet):
    """The page listing a `Collection`'s items, and everything done to it.

    A hub whose members are the registry's items. `member_key` is the key
    the registry lives under — the full key, when the collection is listed
    by a hub, which is how a hub builds it. Set `collection`, `url_name`
    and `member_key` on a root; a nested collection gets them from its
    hub.
    """

    collection: Collection | None = None
    declaration_name = "collection"
    #: The generated `ItemViewSet`, for a driver that addresses an item.
    item_viewset: type[ItemViewSet] | None = None
    hub_context_name: str | None = None
    #: The door segment is an item's id, a uuid rather than a slug — which
    #: is what lets `remove/` be a safe sibling of it.
    member_url_kwarg = "item"
    collection_context_name = "collection"
    form_class = AddAnotherForm
    remove_template_name: str | None = None

    @classmethod
    def declaration(cls) -> Any:
        return cls.collection

    @classmethod
    def materialise(cls) -> None:
        collection = cls.collection
        assert collection is not None
        if cls.member_key is None:
            raise ImproperlyConfigured(
                f"{cls.__name__} has no collection to list. Set "
                f"{cls.__name__}.member_key to the key its items are registered under."
            )
        # The declaration's pages, unless this class names its own.
        for name in ("template_name", "remove_template_name"):
            declared = getattr(collection, name)
            if declared is not None and name not in cls.__dict__:
                setattr(cls, name, declared)
        item_url_name = f"{cls.url_name}-item"
        bases = cls.wizard_bases(collection.wizard, ItemViewSet)
        attrs = {
            **cls.scoped_attrs(item_url_name),
            **cls.wizard_attrs(collection.wizard, bases),
            "collection_key": cls.member_key,
            "member_label": collection.label,
            "item_title": staticmethod(collection.item_title)
            if callable(collection.item_title)
            else collection.item_title,
            "member_done": staticmethod(collection.done)
            if collection.done is not None
            else None,
        }
        cls.item_viewset = type(
            _class_name(cls.member_key, "ItemViewSet"), bases, attrs
        )
        cls.members = []
        cls._routes = []

    @classmethod
    def urls(cls) -> list[URLPattern | URLResolver]:
        """The page, the door for one item, its remove page, and the item
        wizard beneath the door."""
        if cls.url_name is None:
            raise ImproperlyConfigured(
                f"{cls.__name__}.urls() requires url_name to be set."
            )
        item = cls.item_viewset
        assert item is not None
        view = cls.as_view()
        segment = f"<uuid:{cls.member_url_kwarg}>/"
        _start, *run_patterns = item.urls()
        return [
            path("", view, name=cls.url_name),
            path(segment, view, name=f"{cls.url_name}-item"),
            path(f"{segment}remove/", view, name=f"{cls.url_name}-remove"),
            path(segment, include(run_patterns)),
        ]

    # --- the items -------------------------------------------------------

    def get_declaration(self) -> Collection:
        return cast(Collection, super().get_declaration())

    def get_collection_key(self) -> str:
        key = self.get_member_key()
        assert key is not None
        return key

    def get_collection_store(self) -> CollectionStore:
        return cast(CollectionStore, self.get_journey_store())

    def get_item_viewset(self) -> type[ItemViewSet]:
        assert self.item_viewset is not None
        return self.item_viewset

    def get_item_ids(self) -> list[str]:
        return self.get_collection_store().item_ids(self.get_collection_key())

    def get_item_label(self) -> str:
        label = self.get_declaration().label
        return self.get_collection_key() if label is None else label

    def get_item_member(self, item_id: str) -> Member:
        return Member(
            key=item_id,
            viewset=self.get_item_viewset(),
            label=self.get_item_label(),
            reopen_step=self.get_declaration().reopen,
            url_kwargs={self.member_url_kwarg: item_id},
        )

    def get_members(self) -> list[Member]:
        return [self.get_item_member(item_id) for item_id in self.get_item_ids()]

    def get_item(self, item_id: str) -> Member:
        if item_id not in self.get_item_ids():
            raise ItemNotFound(item_id)
        return self.get_item_member(item_id)

    def get_hub(self) -> HubPage:
        return self.get_collection()

    # --- the page --------------------------------------------------------

    def build_member_rows(self) -> list[MemberRow]:
        store = self.get_collection_store()
        return [
            self.build_collection_row(member, store, position)
            for position, member in enumerate(self._vetted_members())
        ]

    def get_collection(self) -> CollectionPage:
        store = self.get_collection_store()
        key = self.get_collection_key()
        rows = tuple(cast("list[CollectionRow]", self.get_member_rows()))
        status = self.get_collection_status(rows, store)
        return CollectionPage(
            key=key,
            url=self.get_page_url(),
            rows=rows,
            status=status,
            status_label=self.get_status_label(status),
            declared_done=store.is_declared_done(key),
            min_items=self.get_declaration().min_items,
        )

    def build_collection_row(
        self, member: Member, store: CollectionStore, position: int
    ) -> CollectionRow:
        item_id = self.item_id_for(member)
        status = self.get_member_status(member, store)
        return CollectionRow(
            member=member,
            status=status,
            title=self.get_item_title(item_id, store, position),
            status_label=self.get_status_label(status),
            url=self.get_member_url(member),
            item_id=item_id,
            position=position,
            remove_url=self.get_item_remove_url(item_id),
        )

    def item_id_for(self, member: Member) -> str:
        return cast(str, member.url_kwargs[self.member_url_kwarg])

    def get_item_title(
        self, item_id: str, store: CollectionStore, position: int
    ) -> StrOrPromise:
        """The cached name the item finished with, or a positional one."""
        title = store.get_item_title(self.get_collection_key(), item_id)
        if title:
            return title
        return self.get_placeholder_title(position)

    def get_placeholder_title(self, position: int) -> StrOrPromise:
        return gettext("%(name)s %(number)d") % {
            "name": self.get_item_name(),
            "number": position + 1,
        }

    def get_item_name(self) -> StrOrPromise:
        item_name = self.get_declaration().item_name
        if item_name is not None:
            return item_name
        key = self.get_collection_key().rsplit(self.key_separator, 1)[-1]
        key = key.replace("_", " ").replace("-", " ")
        return capfirst(key[:-1] if key.endswith("s") else key)

    def get_collection_status(
        self, rows: tuple[CollectionRow, ...], store: CollectionStore
    ) -> str:
        """Complete only when the user has said there are no more, every
        item has finished, and there are at least `min_items`."""
        if not store.is_declared_done(self.get_collection_key()):
            return NOT_STARTED if not rows else INCOMPLETE
        if len(rows) < self.get_declaration().min_items:
            return INCOMPLETE
        if any(not row.is_complete for row in rows):
            return INCOMPLETE
        return COMPLETE

    def get_member_url(self, member: Member) -> str:
        return self.get_item_url(self.item_id_for(member))

    def get_item_url(self, item_id: str) -> str:
        return self._reverse_item("item", item_id)

    def get_item_remove_url(self, item_id: str) -> str:
        return self._reverse_item("remove", item_id)

    def _reverse_item(self, suffix: str, item_id: str) -> str:
        if self.url_name is None:
            raise ImproperlyConfigured(f"Set url_name on {self.__class__.__name__}.")
        return reverse(
            f"{self.url_name}-{suffix}",
            kwargs={**self.get_page_url_kwargs(), self.member_url_kwarg: item_id},
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

    # --- the actions -----------------------------------------------------

    def new_item_id(self) -> str:
        return str(uuid.uuid4())

    def add_item(self) -> str | None:
        """Register a new item and enter it. Registered before entered, so
        a gated collection leaves a listed, removable, not-started row."""
        store = self.get_collection_store()
        key = self.get_collection_key()
        item_id = self.new_item_id()
        store.add_item(key, item_id)
        # Pressing Add *is* the user withdrawing their answer to "any more?".
        store.set_declared_done(key, False)
        return self.enter(self.get_item_member(item_id))

    def declare_done(self) -> HttpResponseBase:
        """The user said there are no more: record it, then submit."""
        self.get_collection_store().set_declared_done(self.get_collection_key(), True)
        return self.submit()

    def remove_item(self, item_id: str) -> HttpResponse:
        """Take an item off the page: its run, its stash, its title, its
        registry entry, in that order, with `item_removed()` between the
        bookkeeping and the registry."""
        store = self.get_collection_store()
        key = self.get_collection_key()
        member = self.get_item_member(item_id)
        self.discard_item_run(member, store)
        store.clear_run(self.full_key(member))
        store.delete_stash(self.full_key(member))
        store.set_item_title(key, item_id, None)
        self.item_removed(item_id, member, store)
        store.remove_item(key, item_id)
        return redirect(self.get_page_url())

    def discard_item_run(self, member: Member, store: CollectionStore) -> None:
        run_id = store.get_run(self.full_key(member))
        if run_id is None:
            return
        try:
            bound_wizard = self.member_viewset(member).inspect(
                self.request, run_id, **self.member_url_kwargs(member)
            )
        except RunNotFound:
            return
        bound_wizard.obliterate()

    def item_removed(
        self, item_id: str, member: Member, store: CollectionStore
    ) -> None:
        """An item is about to leave the registry. Undo whatever finishing
        it did elsewhere."""

    # --- HTTP -------------------------------------------------------------

    def _item_id(self) -> str | None:
        item_id = self.kwargs.get(self.member_url_kwarg)
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
                    f"Set remove_template_name on {name}'s Collection: the page "
                    f"that asks the user to confirm removing an item."
                )
            return [self.remove_template_name]
        return super().get_template_names()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        item_id = self._item_id()
        if item_id is None:
            return super(HubViewSet, self).get(request, *args, **kwargs)
        try:
            member = self.get_item(item_id)
        except ItemNotFound:
            return self.member_unavailable(item_id)
        if self._is_remove():
            return self.render_to_response(self.get_context_data(row=self.row(item_id)))
        url = self.enter(member)
        if url is None:
            return self.member_unavailable(item_id)
        return redirect(url)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        item_id = self._item_id()
        if item_id is not None:
            # Which route, not merely which id: two patterns carry an item
            # and only one of them destroys anything.
            if not self._is_remove():
                return HttpResponseNotAllowed(["GET"])
            try:
                self.get_item(item_id)
            except ItemNotFound:
                return self.member_unavailable(item_id)
            return self.remove_item(item_id)
        form = self.get_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        if form.wants_another:
            url = self.add_item()
            if url is None:
                return redirect(self.get_page_url())
            return redirect(url)
        return self.declare_done()

    def row(self, item_id: str) -> CollectionRow:
        return self.build_collection_row(
            self.get_item_member(item_id),
            self.get_collection_store(),
            self.get_item_ids().index(item_id),
        )
