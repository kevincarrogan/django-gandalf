"""A task list declared as a class body: the rows become the hub's members
in body order; a viewset mounts the list and registers as its way in."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf.hubs import COMPLETE, HubViewSet, MemberViewSet
from gandalf.tasklists import (
    AddAnother,
    Group,
    Link,
    Row,
    Section,
    TaskList,
    TaskListViewSet,
)
from gandalf.wizard import Wizard
from tests.testapp.forms import FirstStepForm

FIRST = Wizard().step(FirstStepForm, name="first")


class _Supporting(TaskList):
    template_name = "testapp/nested_hub.html"

    referees = Section(FIRST, title="Referees")


class _Application(TaskList):
    setup = Section(FIRST, title="Applying as")
    guests = AddAnother(FIRST, item_name="Guest", item_title=("first", "name"))
    supporting = Group(_Supporting, title="Supporting information")
    payment = Link("readme-hub", title="Pay", status=lambda request, kwargs: COMPLETE)


class _ApplicationViewSet(TaskListViewSet):
    template_name = "testapp/hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-apply"
    tasklist = _Application


def test_the_rows_become_members_in_body_order():
    assert list(_Application.rows) == ["setup", "guests", "supporting", "payment"]
    assert [member.key for member in _ApplicationViewSet.members] == list(
        _Application.rows
    )


def test_a_row_stays_readable_on_the_declaration():
    """A value, not a view: nothing for `setup` to shadow."""
    assert isinstance(_Application.setup, Section)
    assert _Application.setup.title == "Applying as"


def test_a_group_page_is_a_subclass_of_its_root_over_the_groups_rows():
    nested = _ApplicationViewSet.viewset_for("supporting")

    assert issubclass(nested, _ApplicationViewSet)
    assert nested.tasklist is _Supporting
    assert nested.template_name == "testapp/nested_hub.html"
    assert nested.member_key == "supporting"
    assert nested.viewset_for("referees").member_key == "supporting:referees"


def test_a_section_may_be_a_member_viewset_with_its_own_behaviour():
    class _Gated(MemberViewSet):
        wizard = FIRST

        @classmethod
        def blocked(cls, store):
            return True

    class _List(TaskList):
        gated = Section(_Gated, title="Gated")

    class _ListViewSet(TaskListViewSet):
        url_name = "readme-hub"
        template_name = "testapp/hub.html"
        member_template_name = "testapp/linear_wizard.html"
        tasklist = _List

    assert issubclass(_ListViewSet.viewset_for("gated"), _Gated)


def test_an_add_another_row_takes_a_ready_made_collection():
    from gandalf.collections import Collection

    row = AddAnother(Collection(FIRST, item_name="Guest"), title="Guests")

    assert row.declare("guests").collection.item_name == "Guest"


def test_a_link_row_is_a_member_with_no_viewset():
    (link,) = [m for m in _ApplicationViewSet.members if m.key == "payment"]

    assert link.viewset is None
    assert link.url_name == "readme-hub"


def test_a_bare_row_declares_nothing():
    with pytest.raises(NotImplementedError):
        Row().declare("nothing")


def test_a_task_list_viewset_is_a_hub_viewset():
    assert issubclass(TaskListViewSet, HubViewSet)


def test_mounting_a_list_registers_the_way_into_it():
    assert _Application.viewset is _ApplicationViewSet
    # A group's page is reached through its root, not registered as a way in.
    assert _Supporting.viewset is None


def test_a_list_begins_a_journey_through_its_viewset(rf):
    request = rf.get("/")
    request.session = {}

    journey = _Application.begin(request, journey="app-1")

    assert journey.url == "/readme/apply/app-1/"


def test_an_unmounted_list_cannot_begin_a_journey(rf):
    class _Loose(TaskList):
        only = Section(FIRST)

    with pytest.raises(ImproperlyConfigured, match="not mounted"):
        _Loose.begin(rf.get("/"))


def test_a_viewset_without_a_list_is_misconfigured(rf):
    class _Empty(TaskListViewSet):
        url_name = "readme-hub"
        template_name = "testapp/hub.html"

    request = rf.get("/readme/hub/")
    request.session = {}
    view = _Empty()
    view.setup(request)

    with pytest.raises(ImproperlyConfigured, match="tasklist"):
        view.get_members()
