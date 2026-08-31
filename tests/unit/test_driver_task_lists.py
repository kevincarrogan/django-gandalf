"""A task list driven without a browser.

`RunDriver` drives one run. A journey is several, decided by a page that
knows which are open, which are finished and what the whole thing is
waiting on — and until `JourneyDriver` there was no way to ask any of that
except by rendering the page. The demo did it by hand, reaching into
`get_items()` and `add_item()` from an application toolset, which is the
shape of a gap rather than of a recipe.
"""

import pytest
from django.contrib.sessions.backends.cache import SessionStore

from gandalf.context import WizardContext
from gandalf.driver import (
    ConfirmationRequired,
    JourneyDriver,
    JourneyIncomplete,
    RunDriver,
)
from gandalf.tasklists import (
    COMPLETE,
    NOT_STARTED,
    EntryNotFound,
    EntryUnavailable,
    Link,
    Section,
    TaskList,
    TaskListViewSet,
)
from gandalf.viewsets import DoorRefused
from tests.testapp.readme.ch12_task_list import (
    GrantApplicationViewSet,
    contact as CONTACT,
)
from tests.testapp.readme.ch14_gated import GatedViewSet
from tests.testapp.views import PartyViewSet, SubmitViewSet


@pytest.fixture
def journey():
    return JourneyDriver.begin(
        GrantApplicationViewSet, context=WizardContext(session=SessionStore())
    )


# --- beginning one ----------------------------------------------------------


def test_a_journey_begins_without_a_request(journey):
    """`TaskList.begin()` takes an `HttpRequest`, and a driver has a
    context. The demo bridged that by hand with `context.http_request()`;
    chapter 15 already claimed an agent begins a journey the same way as
    anything else, and this is what makes that true."""
    assert journey.journey_id
    assert journey.url == "/readme/task-list/"


def test_a_journey_can_be_picked_back_up_by_its_id(journey):
    """The handover, one level up from a run: the journey an agent filled
    is the journey the browser opens."""
    journey.section("contact").submit({"full_name": "Ada"})

    again = JourneyDriver.resume(
        GrantApplicationViewSet, journey.journey_id, context=journey.context
    )

    assert again.section("contact").answers()["name"] == {"full_name": "Ada"}


# --- what it can see --------------------------------------------------------


def test_the_outline_is_the_declared_shape_before_anything_exists():
    """`outline_for()` answers without beginning a journey, exactly as
    `RunDriver.outline_for()` answers without beginning a run. Nothing is
    stored by asking what a thing is."""
    outline = JourneyDriver.outline_for(GrantApplicationViewSet)

    assert [entry["key"] for entry in outline] == ["contact", "address"]
    assert [entry["kind"] for entry in outline] == ["section", "section"]


def test_each_section_carries_its_own_wizards_outline():
    """The whole reason to look before starting: what every part of the
    journey will ask, in one read, so the residue can be asked for once."""
    outline = JourneyDriver.outline_for(GrantApplicationViewSet)

    steps = outline[0]["steps"]

    assert [step["step"] for step in steps] == ["name", "email", "review"]
    assert steps[0]["schema"]["properties"]["full_name"]["type"] == "string"


def test_a_group_and_a_list_are_pages_in_their_own_right():
    """An outline is a tree because a task list is: a group holds entries,
    and so does an add-another. What they hold is this again."""
    from tests.testapp.readme.ch15_journey import (
        GrantApplicationViewSet as JourneyViewSet,
    )

    outline = JourneyDriver.outline_for(JourneyViewSet, journey="app-1")
    kinds = {entry["key"]: entry["kind"] for entry in outline}

    assert kinds["budget"] == "add-another"
    assert kinds["supporting"] == "group"
    group = next(entry for entry in outline if entry["key"] == "supporting")
    assert [nested["kind"] for nested in group["entries"]] == ["section", "section"]


def test_a_link_describes_no_steps_because_they_are_not_here():
    """A link names somewhere else. What is over there is not this
    journey's to describe, so it gets neither steps nor entries."""

    class _Elsewhere(TaskList):
        contact = Section(CONTACT)
        elsewhere = Link("readme-task-list", status=lambda request, kwargs: COMPLETE)

    class _Page(TaskListViewSet):
        url_name = "readme-task-list"
        template_name = "testapp/task_list.html"
        section_template_name = "testapp/linear_wizard.html"
        task_list = _Elsewhere

    outline = JourneyDriver.outline_for(_Page)

    link = outline[1]
    assert link["kind"] == "link"
    assert "steps" not in link and "entries" not in link


def test_a_journey_outlines_the_page_it_is_on(journey):
    """`outline()` is `outline_for()` for the journey in hand — the same
    answer, without naming the viewset again."""
    assert journey.outline() == JourneyDriver.outline_for(GrantApplicationViewSet)


def test_the_rows_are_the_page_a_person_would_see(journey):
    assert [(row.key, row.status) for row in journey.rows()] == [
        ("contact", NOT_STARTED),
        ("address", NOT_STARTED),
    ]


def test_a_finished_section_reads_as_complete_on_the_page(journey):
    contact = journey.section("contact", may_finish=True)
    contact.prefill({"name": {"full_name": "Ada"}, "email": {"email": "a@b.com"}})
    contact.submit({"confirmed": True})
    contact.finish()

    assert journey.rows()[0].status == COMPLETE
    assert journey.is_complete is False


def test_a_hidden_section_is_not_a_row_here_either():
    """A hidden entry is gone for the person; a driver's page is the
    person's page."""
    driver = JourneyDriver.begin(
        GatedViewSet, context=WizardContext(session=SessionStore())
    )

    assert [row.key for row in driver.rows()] == ["project", "referees"]


# --- opening one ------------------------------------------------------------


def test_a_section_is_opened_by_naming_its_row(journey):
    """The alternative is what the demo does: know the generated viewset's
    name, and which url kwargs it takes."""
    contact = journey.section("contact")

    assert isinstance(contact, RunDriver)
    assert contact.describe().step == "name"


def test_the_same_section_asked_for_twice_is_the_same_run(journey):
    journey.section("contact").submit({"full_name": "Ada"})

    assert journey.section("contact").describe().step == "email"


def test_a_section_that_cannot_be_started_yet_is_refused():
    """Through the page or through the driver, the row says *Cannot start
    yet* and the door agrees."""
    driver = JourneyDriver.begin(
        GatedViewSet, context=WizardContext(session=SessionStore())
    )

    with pytest.raises(DoorRefused) as refusal:
        driver.section("referees")

    assert refusal.value.reason == EntryUnavailable.BLOCKED


def test_a_key_the_page_does_not_list_is_refused(journey):
    with pytest.raises(EntryNotFound):
        journey.section("nope")


# --- a list that grows ------------------------------------------------------


def _item_ids(driver):
    return [row.item_id for row in driver.items("guests").rows]


@pytest.fixture
def party():
    return JourneyDriver.begin(
        PartyViewSet, context=WizardContext(session=SessionStore())
    )


def test_an_add_another_entry_starts_with_nothing_on_it(party):
    assert _item_ids(party) == []


def test_adding_an_item_hands_back_a_driver_over_it(party):
    """One call, rather than add it, then read the ids, then take the last
    one and hope nothing else added one in between."""
    guest = party.add("guests")

    assert guest.describe().step == "guest"
    assert len(_item_ids(party)) == 1


def test_an_item_can_be_taken_back_off(party):
    party.add("guests")
    (item_id,) = _item_ids(party)

    party.remove("guests", item_id)

    assert _item_ids(party) == []


def test_a_section_is_not_a_list(party):
    """Asking a plain section for its items is a mistake worth naming
    rather than an `AttributeError` from somewhere underneath."""
    with pytest.raises(EntryNotFound, match="not a list"):
        party.items("venue")


# --- ending one -------------------------------------------------------------


def test_a_journey_will_not_be_submitted_without_being_told_it_may(journey):
    """`journey_done()` is the task list's `done()`: it is where the
    irreversible things live, and a driver is the unattended path by
    definition."""
    with pytest.raises(ConfirmationRequired):
        journey.submit()


def test_a_journey_that_is_not_finished_refuses_to_be_submitted(journey):
    """The page refuses its own button until every row is complete, and
    says so on the page. A driver has no page to say it on, so it raises —
    the guard is the same one either way."""
    journey.may_submit = True

    with pytest.raises(JourneyIncomplete):
        journey.submit()


def test_a_finished_journey_submits_and_leaves_a_tombstone():
    """The whole shape, end to end: fill every section, press the page's
    button, and the journey is closed to both doors afterwards."""
    driver = JourneyDriver.begin(
        SubmitViewSet,
        context=WizardContext(session=SessionStore()),
        journey="app-1",
        may_submit=True,
    )
    for key in ("first", "second"):
        section = driver.section(key, may_finish=True)
        section.submit({"name": "Ada"})
        section.finish()

    response = driver.submit()

    assert response.content == b"submitted app-1"
    assert driver.store.is_complete()
    with pytest.raises(DoorRefused):
        driver.section("first")
