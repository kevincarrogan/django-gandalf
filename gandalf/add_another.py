"""Add another: a list the user grows, one wizard run per item.

An add-another page is a task list whose entries are *built* rather than
declared — one per id in an ordered registry the user grows — so
everything a task list does applies unchanged: the status derivation, the
resume-before-reopen door, the guarantee that no row ever links a bare run
URL. What it adds is the page pattern itself: a list of what has been added
with **Change** and **Remove** on each row, an **Add another** question,
and one item wizard behind all of them.

Declared as an entry of a task list —

    class GrantApplication(TaskList):
        budget = AddAnother(
            budget_line, title="Budget", item_title="item", min_items=1, reopen_at="review"
        )

— which mounts it beneath the page, rendering with the page's
`add_another_template_name` and `remove_template_name`; or mounted on its
own:

    class VehiclesViewSet(AddAnotherViewSet):
        url_name = "vehicles"
        key = "vehicles"
        add_another = AddAnother(vehicle, item_title="registration")
        template_name = "fleet/vehicles.html"
        remove_template_name = "fleet/remove_vehicle.html"
        task_list_url_name = "quote"   # where Continue goes

Completeness is declared, not derived: no reading of storage can say
whether the user has more to add, so the page asks, and the answer is kept
in the store beside the registry. An item is a uuid, never a position:
remove one from the middle and the rest keep their ids, their URLs and
their answers.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
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
from django.urls import URLPattern, URLResolver, include, path, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext, gettext_lazy as _

from gandalf import tree
from gandalf.wizard import ConfiguredWizard, Wizard, declared_step_fields
from gandalf.runtime import Run
from gandalf.storage import RunNotFound
from gandalf.tasklists import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    EntryStatus,
    AddAnother,
    Entry,
    Row,
    Section,
    SectionViewSet,
    TaskListPage,
    TaskListViewSet,
    class_name_for,
)
from gandalf.types import ItemStore, JourneyStore, StrOrPromise
from gandalf.viewsets import RunUnavailable

__all__ = [
    "BLOCKED",
    "COMPLETE",
    "INCOMPLETE",
    "NOT_STARTED",
    "AddAnotherForm",
    "AddAnotherPage",
    "AddAnotherViewSet",
    "ItemNotFound",
    "ItemRow",
    "ItemViewSet",
]


class ItemNotFound(LookupError):
    """Raised when an id names no item of this list."""


class AddAnotherForm(forms.Form):
    """The one question an add-another page asks. Two submit buttons carry
    the answer, so the field needs no widget of its own on the page."""

    add_another = forms.ChoiceField(
        label=_("Do you want to add another?"),
        choices=[("yes", _("Yes")), ("no", _("No"))],
        widget=forms.RadioSelect,
        error_messages={"required": _("Select yes if you want to add another")},
    )

    @property
    def wants_another(self) -> bool:
        return bool(self.cleaned_data["add_another"] == "yes")


# --- what the page renders ---------------------------------------------------


@dataclass(frozen=True)
class ItemRow(Row):
    """One item: a row that also knows its id, its position, and where to
    remove it."""

    item_id: str = ""
    position: int = 0
    remove_url: str = ""


@dataclass(frozen=True)
class AddAnotherPage(TaskListPage):
    """The list as rendered: its rows, and whether the user has said there
    are no more. `status` is derived from both."""

    rows: tuple[ItemRow, ...]
    key: str
    url: str
    declared_done: bool
    min_items: int

    @property
    def is_empty(self) -> bool:
        return not self.rows


# --- the item wizard, as declared --------------------------------------------


def item_wizard(entry: AddAnother) -> Wizard | ConfiguredWizard | None:
    """The entry's item wizard as a declaration, or None when there is none
    to read: an `ItemViewSet` subclass in the slot that builds its wizard
    per request."""
    wizard: Any = entry.wizard
    if isinstance(wizard, type):
        wizard = getattr(wizard, "wizard", None)
    return cast("Wizard | ConfiguredWizard | None", wizard)


def first_step_label(entry: AddAnother) -> StrOrPromise | None:
    """The `label` of the item wizard's first step, if it has one."""
    wizard = item_wizard(entry)
    nodes = [] if wizard is None else list(tree.iter_nodes(wizard.tree))
    steps = [node for node in nodes if isinstance(node, tree.Step)]
    if not steps:
        return None
    return (steps[0].context or {}).get("label")


# --- one item ------------------------------------------------------------------


class ItemViewSet(SectionViewSet):
    """The viewset an add-another page runs one item with. Built by
    `AddAnotherViewSet` from the entry and mounted under `<uuid:item>/`
    beneath the page, so one class serves every row. A `Section`-style
    subclass in the entry's slot carries an item's behaviour — `run_done()`
    for saving it, `item_removed()` for undoing that."""

    list_key: str | None = None
    item_url_kwarg = "item"
    item_title: Any = None

    def get_list_key(self) -> str:
        if self.list_key is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} collects items for no list."
            )
        return self.list_key

    def get_item_id(self) -> str:
        item_id = self.kwargs.get(self.item_url_kwarg)
        if item_id is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} is not mounted under an item segment, so no request "
                f"can say which item it is answering."
            )
        return str(item_id)

    def get_key(self) -> str:
        return self.compose_key(self.get_list_key(), self.get_item_id())

    def default_label(self) -> str:
        """Items share the list's label: a per-item id would never match
        anything on the way back in."""
        return self.get_list_key()

    def get_journey_store(self) -> ItemStore:
        return cast(ItemStore, super().get_journey_store())

    def get_item_title(self, run: Run) -> str:
        """The name this item goes by on the page, read off the finished
        run: the `item_title` field's answer, or its callable's return. A
        field on a step that is not on the route the user took names
        nothing, and the page falls back to a positional name rather than
        inventing one."""
        if self.item_title is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} cannot name its items. Declare the AddAnother with "
                f"item_title=<field name>, or a callable of the finished run."
            )
        if callable(self.item_title):
            return str(self.item_title(run))
        for step in run.path:
            answer = step.answer
            # A step whose answer is not a mapping declares no field to be
            # named by — `check_item_title` refuses one at configure time —
            # so it simply contributes no candidate here.
            if isinstance(answer, Mapping) and self.item_title in answer:
                return str(answer[self.item_title])
        return ""

    def run_recorded(self, run: Run, store: JourneyStore, key: str) -> None:
        title = self.get_item_title(run)
        cast(ItemStore, store).set_item_title(
            self.get_list_key(), self.get_item_id(), title or None
        )

    def item_removed(self, store: ItemStore) -> None:
        """This item is about to leave the list. Undo whatever finishing it
        did elsewhere; `self.get_item_id()` says which."""

    def get_task_list_url_kwargs(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.get_url_kwargs().items()
            if key != self.item_url_kwarg
        }

    def run_unavailable(self, run: Run, reason: RunUnavailable) -> HttpResponseBase:
        return redirect(self.get_task_list_url())

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """An item that is not on the registry — removed, or never added —
        has no page to be on, whatever run its URL names."""
        store = self.get_journey_store()
        if not store.has_item(self.get_list_key(), self.get_item_id()):
            return self.item_unavailable()
        return super().dispatch(request, *args, **kwargs)

    def item_unavailable(self) -> HttpResponseBase:
        return redirect(self.get_task_list_url())


# --- the page ----------------------------------------------------------------


class AddAnotherViewSet(TaskListViewSet):
    """The page listing an `AddAnother`'s items, and everything done to it.

    A task list whose entries are the registry's items. `key` is the key
    the registry lives under — the full key, when the list is an entry of
    a task list, which is how a task list builds it. Set `add_another`,
    `url_name` and `key` on a root; an entry gets them from its page.
    """

    add_another: AddAnother | None = None
    #: The generated `ItemViewSet`, for a driver that addresses an item.
    item_viewset: type[ItemViewSet] | None = None
    page_context_name: str | None = None
    #: The door segment is an item's id, a uuid rather than a slug — which
    #: is what lets `remove/` be a safe sibling of it.
    entry_url_kwarg = "item"
    items_context_name = "items"
    form_class = AddAnotherForm

    @classmethod
    def declared_entries(cls) -> dict[str, Entry] | None:
        return None if cls.add_another is None else {}

    @classmethod
    def materialise(cls) -> None:
        entry = cls.add_another
        assert entry is not None
        if cls.key is None:
            raise ImproperlyConfigured(
                f"{cls.__name__} has no list to show. Set {cls.__name__}.key "
                f"to the key its items are registered under."
            )
        cls.check_item_title(entry)
        item_url_name = f"{cls.url_name}-item"
        bases = cls.wizard_bases(entry.wizard, ItemViewSet)
        attrs = {
            **cls.scoped_attrs(item_url_name),
            **cls.wizard_attrs(entry.wizard, bases),
            "list_key": cls.key,
            "label": entry.label,
            "item_title": staticmethod(entry.item_title)
            if callable(entry.item_title)
            else entry.item_title,
        }
        cls.item_viewset = type(class_name_for(cls.key, "ItemViewSet"), bases, attrs)
        cls.entries = []
        cls._routes = []

    @classmethod
    def check_item_title(cls, entry: AddAnother) -> None:
        """Refuse an `item_title` field that no step of the item wizard
        declares, or that two of them do — the second would be answered by
        whichever step came first on the route, silently. Skipped for a
        wizard the declaration cannot see: one grown by `.expand()`, one a
        viewset builds per request, or one whose step view chooses its form
        class per request."""
        field = entry.item_title
        if not isinstance(field, str):
            return
        wizard = item_wizard(entry)
        if wizard is None:
            return
        fields = declared_step_fields(wizard)
        if fields is None or any(declared is None for declared in fields.values()):
            return
        declaring = [
            name
            for name, declared in fields.items()
            if declared is not None and field in declared
        ]
        if len(declaring) == 1:
            return
        name = cls.__name__
        if not declaring:
            raise ImproperlyConfigured(
                f"{name} names its items by {field!r}, a field no step of its "
                f"item wizard declares."
            )
        raise ImproperlyConfigured(
            f"{name} names its items by {field!r}, which steps "
            f"{', '.join(declaring)} all declare. Name them with a callable "
            f"of the finished run instead."
        )

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
        segment = f"<uuid:{cls.entry_url_kwarg}>/"
        _start, *run_patterns = item.urls()
        return [
            path("", view, name=cls.url_name),
            path(segment, view, name=f"{cls.url_name}-item"),
            path(f"{segment}remove/", view, name=f"{cls.url_name}-remove"),
            path(segment, include(run_patterns)),
        ]

    # --- the items -------------------------------------------------------

    def get_declaration(self) -> AddAnother:  # type: ignore[override]
        if self.add_another is None:
            name = self.__class__.__name__
            raise ImproperlyConfigured(
                f"{name} has no items to list. Set {name}.add_another to an "
                f"AddAnother entry."
            )
        return self.add_another

    def get_list_key(self) -> str:
        key = self.get_key()
        assert key is not None
        return key

    def get_store(self) -> ItemStore:
        return cast(ItemStore, self.get_journey_store())

    def get_item_viewset(self) -> type[ItemViewSet]:
        assert self.item_viewset is not None
        return self.item_viewset

    def get_item_ids(self) -> list[str]:
        return self.get_store().item_ids(self.get_list_key())

    def get_item_label(self) -> str:
        label = self.get_declaration().label
        return self.get_list_key() if label is None else label

    def get_item_entry(self, item_id: str) -> Entry:
        return Section(
            self.get_item_viewset(),
            label=self.get_item_label(),
            reopen_at=self.get_declaration().reopen_at,
            key=item_id,
            viewset=self.get_item_viewset(),
            url_kwargs={self.entry_url_kwarg: item_id},
        )

    def get_entries(self) -> list[Entry]:
        self.get_declaration()
        return [self.get_item_entry(item_id) for item_id in self.get_item_ids()]

    def get_item(self, item_id: str) -> Entry:
        if item_id not in self.get_item_ids():
            raise ItemNotFound(item_id)
        return self.get_item_entry(item_id)

    def get_page(self) -> TaskListPage:
        return self.get_items()

    # --- the page --------------------------------------------------------

    def build_rows(self) -> list[Row]:
        store = self.get_store()
        return [
            self.build_item_row(entry, store, position)
            for position, entry in enumerate(self._vetted_entries())
        ]

    def get_items(self) -> AddAnotherPage:
        store = self.get_store()
        key = self.get_list_key()
        rows = tuple(cast("list[ItemRow]", self.get_rows()))
        status = self.get_items_status(rows, store)
        return AddAnotherPage(
            key=key,
            url=self.get_page_url(),
            rows=rows,
            status=status,
            status_label=self.get_status_label(status),
            declared_done=store.is_declared_done(key),
            min_items=self.get_declaration().min_items,
        )

    def build_item_row(self, entry: Entry, store: ItemStore, position: int) -> ItemRow:
        item_id = self.item_id_for(entry)
        status = self.get_entry_status(entry, store)
        return ItemRow(
            entry=entry,
            status=status,
            title=self.get_item_title(item_id, store, position),
            status_label=self.get_status_label(status),
            url=self.get_entry_url(entry),
            item_id=item_id,
            position=position,
            remove_url=self.get_item_remove_url(item_id),
        )

    def item_id_for(self, entry: Entry) -> str:
        return cast(str, entry.url_kwargs[self.entry_url_kwarg])

    def get_item_title(
        self, item_id: str, store: ItemStore, position: int
    ) -> StrOrPromise:
        """The cached name the item finished with, or a positional one."""
        title = store.get_item_title(self.get_list_key(), item_id)
        if title:
            return title
        return self.get_placeholder_title(position)

    def get_placeholder_title(self, position: int) -> StrOrPromise:
        return gettext("%(name)s %(number)d") % {
            "name": self.get_item_name(),
            "number": position + 1,
        }

    def get_item_name(self) -> StrOrPromise:
        """What an unfinished item is called: the declared `item_name`, else
        the item wizard's first step label, else the key made singular."""
        declaration = self.get_declaration()
        if declaration.item_name is not None:
            return declaration.item_name
        label = first_step_label(declaration)
        if label is not None:
            return label
        key = self.get_list_key().rsplit(self.key_separator, 1)[-1]
        key = key.replace("_", " ").replace("-", " ")
        return capfirst(key[:-1] if key.endswith("s") else key)

    def get_items_status(
        self, rows: tuple[ItemRow, ...], store: ItemStore
    ) -> EntryStatus:
        """Complete only when the user has said there are no more, every
        item has finished, and there are at least `min_items`."""
        if not store.is_declared_done(self.get_list_key()):
            return NOT_STARTED if not rows else INCOMPLETE
        if len(rows) < self.get_declaration().min_items:
            return INCOMPLETE
        if any(not row.is_complete for row in rows):
            return INCOMPLETE
        return COMPLETE

    def get_entry_url(self, entry: Entry) -> str:
        return self.get_item_url(self.item_id_for(entry))

    def get_item_url(self, item_id: str) -> str:
        return self._reverse_item("item", item_id)

    def get_item_remove_url(self, item_id: str) -> str:
        return self._reverse_item("remove", item_id)

    def _reverse_item(self, suffix: str, item_id: str) -> str:
        if self.url_name is None:
            raise ImproperlyConfigured(f"Set url_name on {self.__class__.__name__}.")
        return reverse(
            f"{self.url_name}-{suffix}",
            kwargs={**self.get_page_url_kwargs(), self.entry_url_kwarg: item_id},
        )

    def get_form_class(self) -> type[AddAnotherForm]:
        return self.form_class

    def get_form(self, data: Any = None) -> AddAnotherForm:
        return self.get_form_class()(data=data)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context[self.items_context_name] = self.get_items()
        context.setdefault("form", self.get_form())
        return context

    # --- the actions -----------------------------------------------------

    def new_item_id(self) -> str:
        return str(uuid.uuid4())

    def add_item(self) -> str | None:
        """Register a new item and enter it. Registered before entered, so
        a gated list leaves a listed, removable, not-started row."""
        store = self.get_store()
        key = self.get_list_key()
        item_id = self.new_item_id()
        store.add_item(key, item_id)
        # Pressing Add *is* the user withdrawing their answer to "any more?".
        store.set_declared_done(key, False)
        return self.enter(self.get_item_entry(item_id))

    def declare_done(self) -> HttpResponseBase:
        """The user said there are no more: record it, then submit."""
        self.get_store().set_declared_done(self.get_list_key(), True)
        return self.submit()

    def remove_item(self, item_id: str) -> HttpResponse:
        """Take an item off the page: its run, its stash, its title, its
        registry entry, in that order, with the item's own `item_removed()`
        between the bookkeeping and the registry."""
        store = self.get_store()
        key = self.get_list_key()
        entry = self.get_item_entry(item_id)
        self.discard_item_run(entry, store)
        store.clear_run(self.full_key(entry))
        store.delete_stash(self.full_key(entry))
        store.set_item_title(key, item_id, None)
        item = self.get_item_viewset()()
        item.setup(self.request, **self.entry_url_kwargs(entry))
        item.item_removed(store)
        store.remove_item(key, item_id)
        return redirect(self.get_page_url())

    def discard_item_run(self, entry: Entry, store: ItemStore) -> None:
        run_id = store.get_run(self.full_key(entry))
        if run_id is None:
            return
        try:
            run = self.entry_viewset(entry).inspect(
                self.request, run_id, **self.entry_url_kwargs(entry)
            )
        except RunNotFound:
            return
        run.obliterate()

    # --- HTTP -------------------------------------------------------------

    def _item_id(self) -> str | None:
        item_id = self.kwargs.get(self.entry_url_kwarg)
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
                    f"Set remove_template_name on {name}, or on the task list "
                    f"viewset that builds it: the page that asks the user to "
                    f"confirm removing an item."
                )
            return [self.remove_template_name]
        return super().get_template_names()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        item_id = self._item_id()
        if item_id is None:
            return super(TaskListViewSet, self).get(request, *args, **kwargs)
        try:
            entry = self.get_item(item_id)
        except ItemNotFound:
            return self.entry_unavailable(item_id)
        if self._is_remove():
            return self.render_to_response(self.get_context_data(row=self.row(item_id)))
        url = self.enter(entry)
        if url is None:
            return self.entry_unavailable(item_id)
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
                return self.entry_unavailable(item_id)
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

    def row(self, item_id: str) -> ItemRow:
        return self.build_item_row(
            self.get_item_entry(item_id),
            self.get_store(),
            self.get_item_ids().index(item_id),
        )
