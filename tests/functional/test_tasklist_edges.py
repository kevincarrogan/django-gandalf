"""The task list's edges over the real app: what a declaration is as a
value, what a page refuses, and what a journey looks like from outside a
request. Each of these is one branch the README's flows never take."""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from gandalf.context import WizardContext
from gandalf.driver import RunDriver
from gandalf.tasklists import (
    SectionViewSet,
    COMPLETE,
    AddAnother,
    Entry,
    EntryNotFound,
    Link,
    Section,
    TaskList,
    TaskListViewSet,
)
from gandalf.testing import stored_items
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard
from tests.testapp.forms import FirstStepForm
from tests.testapp.readme.ch12_task_list import GrantApplication, contact
from tests.testapp.readme.ch15_journey import (
    ApplicationStartViewSet,
    GrantApplication as Application,
    GrantApplicationViewSet,
)
from tests.testapp.views import GuestsViewSet, ScenarioViewSet

FIRST = Wizard().step(FirstStepForm, name="first")


# --- an entry as a value ---------------------------------------------------------


def test_entries_are_values():
    """Equal by kind, facts and key; hashable; readable."""
    pay = Link("readme-task-list", title="Pay", status=lambda r, k: COMPLETE)

    assert Section(contact, title="A") == Section(contact, title="A")
    assert Section(contact).bound("a") != Section(contact).bound("b")
    assert Section(contact) != pay
    assert (Section(contact) == "not an entry") is False
    assert len({Section(contact).bound("a"), Section(contact).bound("a")}) == 1
    assert repr(pay.bound("pay")) == (
        f"Link(title='Pay', url_name='readme-task-list', status={pay.status!r}, key='pay')"
    )
    assert pay.replace(title="Pay now").url_name == "readme-task-list"
    assert AddAnother(FIRST, min_items=1).replace(min_items=2).min_items == 2


def test_a_kind_of_entry_the_page_cannot_list_is_refused():
    class _Odd(Entry):
        pass

    class _List(TaskList):
        odd = _Odd()

    with pytest.raises(ImproperlyConfigured, match="_Odd is not a kind of entry"):

        class _Page(TaskListViewSet):
            url_name = "readme-task-list"
            task_list = _List


def test_a_plain_wizard_viewset_in_the_slot_is_made_a_section():
    """Rung two with something that is not yet a SectionViewSet: the page
    puts the section behaviour in front of it."""

    class _Plain(WizardViewSet):
        wizard = FIRST
        template_name = "testapp/linear_wizard.html"

    class _List(TaskList):
        plain = Section(_Plain)

    class _Page(TaskListViewSet):
        url_name = "readme-task-list"
        template_name = "testapp/task_list.html"
        task_list = _List

    viewset = _Page.viewset_for("plain")
    assert issubclass(viewset, _Plain)
    assert viewset.key == "plain"
    with pytest.raises(EntryNotFound):
        _Page.viewset_for("nope")


# --- one list, one page -----------------------------------------------------------


def test_an_explicit_key_is_the_url_segment(client):
    """Chapter 14's `match_funding` attribute is mounted at /match-funding/."""
    assert reverse("readme-gated-match-funding").endswith("/match-funding/")


def test_a_reopen_at_naming_no_declared_step_is_refused():
    class _Typo(TaskList):
        contact = Section(contact, reopen_at="reveiw")

    with pytest.raises(ImproperlyConfigured, match="re-opens at 'reveiw'"):

        class _TypoPage(GrantApplicationViewSet):
            url_name = "readme-typo"
            task_list = _Typo


def test_a_reopen_at_on_a_per_request_wizard_cannot_be_checked():
    """A section viewset that builds its wizard in get_wizard() has no
    declaration to check against, so the name is taken on trust."""

    class _PerRequest(SectionViewSet):
        def get_wizard(self, run):
            return contact

    class _Trusted(TaskList):
        contact = Section(_PerRequest, reopen_at="anything")

    class _TrustedPage(GrantApplicationViewSet):
        url_name = "readme-trusted"
        task_list = _Trusted

    (entry,) = _TrustedPage.entries
    assert entry.reopen_at == "anything"


def _rows_of(rf, client, page_class, **kwargs):
    request = rf.get("/")
    request.session = client.session
    view = page_class()
    view.setup(request, **kwargs)
    return view.get_rows()


def test_a_link_reporting_a_status_the_page_cannot_label_says_so(rf, client):
    """A link's status is arbitrary code and every row gets a label, so a
    status outside the four is refused by name rather than taking the whole
    page down with a KeyError."""

    class _Odd(TaskList):
        pay = Link("readme-task-list", status=lambda request, kwargs: "half-done")

    class _OddPage(TaskListViewSet):
        url_name = "odd-status-page"
        task_list = _Odd

    with pytest.raises(ImproperlyConfigured, match="half-done"):
        _rows_of(rf, client, _OddPage)


def test_a_link_pointing_at_a_url_that_does_not_reverse_names_the_entry(rf, client):
    """Otherwise every row on the page dies of one entry's NoReverseMatch,
    with nothing to say which declaration is wrong."""

    class _Broken(TaskList):
        pay = Link("no-such-url-name", status=lambda request, kwargs: COMPLETE)

    class _BrokenPage(TaskListViewSet):
        url_name = "broken-link-page"
        task_list = _Broken

    with pytest.raises(ImproperlyConfigured, match="no-such-url-name"):
        _rows_of(rf, client, _BrokenPage)


def test_two_entries_under_one_key_are_refused():
    with pytest.raises(ImproperlyConfigured, match="two entries under the key 'pay'"):

        class _Clash(TaskList):
            pay = Section(contact)
            pay_again = Section(contact, key="pay")


def test_a_second_page_for_one_list_is_refused():
    with pytest.raises(ImproperlyConfigured, match="already mounted"):

        class _Second(TaskListViewSet):
            url_name = "readme-gated"
            task_list = GrantApplication


def test_a_refinement_of_the_mounting_page_is_the_same_page():
    """A subclass — swapping a store, say — mounts nothing new."""

    class _Refined(ScenarioViewSet):
        url_name = "readme-gated"

    assert ScenarioViewSet.task_list.viewset is ScenarioViewSet


def test_an_unmounted_list_cannot_begin_a_journey(rf):
    class _Loose(TaskList):
        only = Section(FIRST)

    with pytest.raises(ImproperlyConfigured, match="not mounted"):
        _Loose.begin(rf.get("/"))


# --- a journey from outside a request ------------------------------------------------


def test_a_journey_on_a_one_per_session_list_has_no_id_in_its_url(client):
    request = client.get(reverse("scenario-task-list")).wsgi_request

    journey = ScenarioViewSet.begin(request)

    assert journey.url == reverse("scenario-task-list")
    assert journey.store.keys() == []


def test_a_journeys_store_is_the_lists_store(client):
    request = client.get(reverse("scenario-task-list")).wsgi_request

    journey = GrantApplicationViewSet.begin(request, journey="app-1")

    assert journey.store.keys() == []
    assert journey.url == reverse("readme-apply", kwargs={"journey": "app-1"})


def test_a_one_per_session_journeys_store_is_the_one_the_page_reads(client):
    """`begin()` makes an id up when it is not given one, and a page with
    no `<journey>` segment has nowhere to put it — it reads a fixed key
    instead. So the made-up id named a store nothing else would ever look
    in: `journey.store` was empty for ever, and anything written through it
    was invisible to the page it was written for.

    The id a journey reports is the one its page will actually read.
    """
    request = client.get(reverse("scenario-task-list")).wsgi_request

    journey = ScenarioViewSet.begin(request)
    journey.store.data["amount"] = 10

    page = ScenarioViewSet()
    page.setup(request, **journey.page_kwargs)

    assert journey.id == page.get_journey()
    assert page.get_journey_store().data["amount"] == 10


def test_a_journey_begins_on_a_context_with_no_request(client):
    """`begin()` takes a request, and a management command or an agent has
    none. An id, a record keyed by it and a URL to the page are the whole
    of a journey, and not one of the three is HTTP — so the door that
    insisted on a request was asking for something it never used, and the
    driver got past it by fabricating one.

    Seeded here rather than merely begun, because that is what a caller
    with no browser is for: the fact the setup wizard exists to ask for,
    known already and written instead. The browser picks up an application
    whose governing-document section is already listed.
    """
    context = WizardContext(session=client.session)

    journey = GrantApplicationViewSet.begin_for(context, "app-7")
    journey.store.data["applying_as"] = "organisation"

    assert journey.id == "app-7"
    assert journey.url == reverse("readme-apply", kwargs={"journey": "app-7"})
    supporting = client.get(journey.url + "supporting/")
    assert supporting.status_code == HTTPStatus.OK
    assert "Governing document" in supporting.content.decode()


def test_a_journey_hides_a_section_a_request_less_caller_ruled_out(client):
    """The other half of the same seed: written *individual*, and the
    section is gone rather than merely begun-and-empty. Proves the page is
    reading the record the context wrote, not defaulting to the same
    answer by luck."""
    context = WizardContext(session=client.session)

    journey = GrantApplicationViewSet.begin_for(context, "app-8")
    journey.store.data["applying_as"] = "individual"

    supporting = client.get(journey.url + "supporting/")
    assert "Governing document" not in supporting.content.decode()


def test_a_journey_records_a_section_finished_with_no_request(client):
    """`finish()` is the one thing on a journey that genuinely needs a
    request — recording a section dispatches a Django view, and a Django
    view takes one. It builds one the way every other driven dispatch
    does rather than refusing a caller that got this far without one."""
    context = WizardContext(session=client.session)
    driver = RunDriver.begin(ApplicationStartViewSet, context=context)
    driver.submit({"applying_as": "organisation"})

    journey = Application.begin_for(context, "app-9")
    journey.finish("setup", driver.run)

    assert journey.store.has_stash("setup")
    assert journey.store.data["applying_as"] == "organisation"


# --- pages that cannot reverse themselves -------------------------------------------


def test_a_page_without_a_url_name_cannot_reverse_itself_or_a_door(rf):
    class _Nameless(TaskListViewSet):
        template_name = "testapp/task_list.html"

    view = _Nameless()
    view.setup(rf.get("/"))

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        view.get_page_url()
    with pytest.raises(ImproperlyConfigured, match="entry_url_name"):
        view.get_entry_url(Section(FIRST).bound("first"))


def test_an_add_another_page_without_a_url_name_cannot_reverse_an_item(rf):
    class _Nameless(GuestsViewSet):
        url_name = None

        def get_page_url(self):
            return "/"

    view = _Nameless()
    view.setup(rf.get("/"))

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        view.get_item_url("11111111-1111-1111-1111-111111111111")


# --- the door, asked directly about a group --------------------------------------------


def test_entering_a_group_is_its_page(client):
    """A group's segment is its page, so the door never sees it over HTTP;
    asked directly, it answers with the page."""
    response = client.get(reverse("readme-apply-start"), follow=True)
    run_url = response.redirect_chain[-1][0]
    journey = client.post(run_url, {"applying_as": "individual"})["Location"]
    journey = journey.rstrip("/").rsplit("/", 1)[-1]
    request = client.get(
        reverse("readme-apply", kwargs={"journey": journey})
    ).wsgi_request
    view = GrantApplicationViewSet()
    view.setup(request, journey=journey)

    url = view.enter(view.get_entry("supporting"))

    assert url == reverse("readme-apply-supporting", kwargs={"journey": journey})


# --- an item named by a callable --------------------------------------------------------


def test_an_item_can_be_named_by_a_callable_of_its_run(client):
    page = reverse("titled-guests")
    step_url = client.post(page, {"add_another": "yes"})["Location"]
    response = client.post(step_url, {"name": "ada", "dietary_requirements": ""})
    client.post(response["Location"], {})

    (item_id,) = stored_items(client, "titled-guests")
    (row,) = client.get(page).context["items"].rows
    assert (row.item_id, str(row.title)) == (item_id, "ADA")
    assert client.get(page).status_code == HTTPStatus.OK
    assert WizardContext.from_request(client.get(page).wsgi_request) is not None
