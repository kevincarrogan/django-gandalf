"""A task list declared as a class body, and the viewset that mounts it.

    class GrantApplication(TaskList):
        setup = Section(SetupMember, title="Applying as")
        contact = Section(contact, title="Contact details", reopen="review")
        budget = AddAnother(budget_line, title="Budget", min_items=1)
        supporting = Group(SupportingInformation, title="Supporting information")


    class GrantApplicationViewSet(TaskListViewSet):
        url_name = "apply"
        template_name = "apply/hub.html"
        tasklist = GrantApplication

        def journey_done(self, hub, store): ...

The same split a wizard has: `TaskList` is a value — what the list is —
and `TaskListViewSet` is the view that mounts it and owns what needs a
request: the page, its URL, the journey's ending. A value can be asked
things a view should not be: `GrantApplication.begin(request)` starts a
journey from anywhere.

The attribute name is the row's key; the body's order is the page's order,
the way a form's fields are. A row carries *facts* — a title, where a
finished section re-opens — and the thing in its slot carries *behaviour*:
a `Wizard`, which the library wraps in a `MemberViewSet`, or your own
`MemberViewSet` subclass when the section has something to do when it
finishes (`run_done()`) or a reason not to be open yet (`blocked()`,
`hidden()`). Nothing about the task list changes between the two — the
same rule a wizard has for a `Form` and a `FormView`.
"""

from __future__ import annotations

from typing import Any, Callable

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest

from gandalf.collections import Collection
from gandalf.hubs import Hub, HubViewSet, Journey, MemberDeclaration, WizardLike
from gandalf.types import StrOrPromise

__all__ = ["AddAnother", "Group", "Link", "Section", "TaskList", "TaskListViewSet"]


class Row:
    """One row of a task list. The subclasses say what kind."""

    def declare(self, key: str) -> MemberDeclaration:
        raise NotImplementedError


class Section(Row):
    """A wizard the user finishes on its own and can come back to. `wizard`
    is a `Wizard`, or a `MemberViewSet` subclass with the section's
    behaviour on it."""

    def __init__(
        self,
        wizard: WizardLike,
        /,
        *,
        title: StrOrPromise | None = None,
        reopen: str | None = None,
        label: str | None = None,
    ) -> None:
        self.wizard = wizard
        self.title = title
        self.reopen = reopen
        self.label = label

    def declare(self, key: str) -> MemberDeclaration:
        return MemberDeclaration(
            "wizard",
            key,
            title=self.title,
            wizard=self.wizard,
            reopen=self.reopen,
            label=self.label,
        )


class AddAnother(Row):
    """A list the user grows, one run of `wizard` per item. Takes the
    `Collection` keyword arguments, or a ready-made `Collection`."""

    def __init__(
        self,
        wizard: WizardLike | Collection,
        /,
        *,
        title: StrOrPromise | None = None,
        **options: Any,
    ) -> None:
        self.collection = (
            wizard if isinstance(wizard, Collection) else Collection(wizard, **options)
        )
        self.title = title

    def declare(self, key: str) -> MemberDeclaration:
        return MemberDeclaration(
            "collection", key, title=self.title, collection=self.collection
        )


class Group(Row):
    """A task list within this one: its sections are keyed under this row's
    key in the same journey, and its Continue returns here."""

    def __init__(
        self, tasklist: type[TaskList], /, *, title: StrOrPromise | None = None
    ) -> None:
        self.tasklist = tasklist
        self.title = title

    def declare(self, key: str) -> MemberDeclaration:
        return MemberDeclaration("hub", key, title=self.title, hub=self.tasklist.hub)


class Link(Row):
    """A row that links somewhere the task list does not run, with `status`
    deciding what the row says of it."""

    def __init__(
        self,
        url_name: str,
        /,
        *,
        title: StrOrPromise | None = None,
        status: Callable[[HttpRequest, dict[str, Any]], str] | None = None,
    ) -> None:
        self.url_name = url_name
        self.title = title
        self.status = status

    def declare(self, key: str) -> MemberDeclaration:
        return MemberDeclaration(
            "link", key, title=self.title, url_name=self.url_name, status=self.status
        )


class TaskList:
    """What a task list is: its rows, in order. A value, not a view.

    `template_name` and `member_template_name` may be set here for a list
    that has no viewset of its own — a `Group` — and are the viewset's to
    set otherwise.
    """

    #: The page this list renders with, when it is a group.
    template_name: str | None = None
    #: The template its wizard sections render with, unless theirs.
    member_template_name: str | None = None
    #: The rows this class and its bases declare, in definition order.
    rows: dict[str, Row] = {}
    #: The equivalent `Hub` declaration, for the engine.
    hub: Hub = Hub()
    #: The nested lists, by row key.
    groups: dict[str, type[TaskList]] = {}
    #: The viewset that mounts this list, once one does.
    viewset: type[TaskListViewSet] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own = {name: row for name, row in cls.__dict__.items() if isinstance(row, Row)}
        cls.rows = {**cls.rows, **own}
        cls.groups = {
            key: row.tasklist for key, row in cls.rows.items() if isinstance(row, Group)
        }
        hub = Hub()
        for key, row in cls.rows.items():
            hub = hub._with(row.declare(key))
        configuration = {
            name: value
            for name in ("template_name", "member_template_name")
            if (value := getattr(cls, name)) is not None
        }
        cls.hub = hub.configure(**configuration)
        cls.viewset = None

    @classmethod
    def mounted(cls) -> type[TaskListViewSet]:
        if cls.viewset is None:
            raise ImproperlyConfigured(
                f"{cls.__name__} is not mounted: no TaskListViewSet declares "
                f"tasklist = {cls.__name__}, so it has no page to begin a journey on."
            )
        return cls.viewset

    @classmethod
    def begin(
        cls, request: HttpRequest, journey: str | None = None, **url_kwargs: Any
    ) -> Journey:
        """Begin a journey on this list — see `HubViewSet.begin()`:

        journey = GrantApplication.begin(request)
        journey.finish("setup", bound_wizard)
        return redirect(journey.url)
        """
        return cls.mounted().begin(request, journey, **url_kwargs)


class TaskListViewSet(HubViewSet):
    """The view that mounts a `TaskList`: set `tasklist` and `url_name`,
    and it is a `HubViewSet` over the list's rows — the page, its hooks,
    the URL tree beneath it, and the journey's ending."""

    tasklist: type[TaskList] | None = None
    declaration_name = "tasklist"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A root viewset is the list's way into a journey; a group's page
        # (built below, with a member_key) is reached only through its root.
        if cls.tasklist is not None and cls.member_key is None:
            cls.tasklist.viewset = cls

    @classmethod
    def declaration(cls) -> Hub | None:
        return None if cls.tasklist is None else cls.tasklist.hub

    @classmethod
    def build_nested_hub(
        cls, declaration: MemberDeclaration, full_key: str, url_name: str
    ) -> type[HubViewSet]:
        """A group's page is a subclass of this one — its hooks apply — over
        the group's own rows and template."""
        assert cls.tasklist is not None
        group = cls.tasklist.groups[declaration.key]
        attrs = {
            **cls.scoped_attrs(url_name),
            "tasklist": group,
            "member_key": full_key,
            "member_template_name": group.member_template_name
            or cls.member_template_name,
            "template_name": group.template_name or cls.template_name,
        }
        return type(f"{group.__name__}ViewSet", (cls,), attrs)
