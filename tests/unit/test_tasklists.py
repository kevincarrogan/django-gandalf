"""A task list declared as a class body: the rows become the hub's members
in body order, and the row attributes leave the class so they cannot shadow
the view."""

import pytest
from django.views import View

from gandalf.hubs import COMPLETE, HubViewSet, MemberViewSet
from gandalf.tasklists import AddAnother, Group, Link, Row, Section, TaskList
from gandalf.wizard import Wizard
from tests.testapp.forms import FirstStepForm

FIRST = Wizard().step(FirstStepForm, name="first")


class _Supporting(TaskList):
    template_name = "testapp/nested_hub.html"

    referees = Section(FIRST, title="Referees")


class _Application(TaskList):
    template_name = "testapp/hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-apply"

    setup = Section(FIRST, title="Applying as")
    guests = AddAnother(FIRST, item_name="Guest", item_title=("first", "name"))
    supporting = Group(_Supporting, title="Supporting information")
    payment = Link("readme-hub", title="Pay", status=lambda request, kwargs: COMPLETE)


def test_the_rows_become_members_in_body_order():
    assert [member.key for member in _Application.members] == [
        "setup",
        "guests",
        "supporting",
        "payment",
    ]
    assert [row.key for row in _Application.hub.members] == list(_Application.rows)


def test_a_row_named_like_a_view_method_does_not_shadow_it():
    """`setup` is also `View.setup()`; the row is a key, not an attribute."""
    assert _Application.setup is View.setup
    assert "setup" in _Application.rows


def test_a_group_is_its_own_class_and_a_subclass_of_its_root():
    nested = _Application.viewset_for("supporting")

    assert issubclass(nested, _Supporting)
    assert issubclass(nested, _Application)
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
        url_name = "readme-hub"
        template_name = "testapp/hub.html"
        member_template_name = "testapp/linear_wizard.html"

        gated = Section(_Gated, title="Gated")

    assert issubclass(_List.viewset_for("gated"), _Gated)


def test_an_add_another_row_takes_a_ready_made_collection():
    from gandalf.collections import Collection

    row = AddAnother(Collection(FIRST, item_name="Guest"), title="Guests")

    assert row.declare("guests").collection.item_name == "Guest"


def test_a_link_row_is_a_member_with_no_viewset():
    (link,) = [member for member in _Application.members if member.key == "payment"]

    assert link.viewset is None
    assert link.url_name == "readme-hub"


def test_a_bare_row_declares_nothing():
    with pytest.raises(NotImplementedError):
        Row().declare("nothing")


def test_a_task_list_is_a_hub_viewset():
    assert issubclass(TaskList, HubViewSet)
