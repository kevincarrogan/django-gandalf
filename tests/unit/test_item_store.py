"""Unit coverage for `SessionItemStore` — a collection's registry.

A page's sections are declared, so the store never has to enumerate them. A
collection's items are not: the user grows them, and no reading of runs or
stashes can hand back the list — the stash key space holds only the items that
have *finished*. So the registry is explicit, ordered, and separate, and an
item exists from the moment it is added, which is what lets a half-finished one
still have a row.
"""

from django.contrib.sessions.backends.cache import SessionStore

from gandalf.context import WizardContext
from gandalf.storage import SessionItemStore


class _Session(dict):
    modified = False


class _Context:
    """As much of a `WizardContext` as a session-backed storage reads.

    A storage is built from the walk's environment rather than from a
    request: it reads the session through the context, and says when it
    has changed one.
    """

    def __init__(self, session=None):
        self.session = _Session()
        if session:
            self.session.update(session)

    def session_changed(self):
        # `WizardContext` marks the session and then writes it back when
        # nothing else will. A dict has nowhere to write it back to, so
        # what a storage's caller sees of the call is the mark.
        self.session.modified = True


_PAYLOAD = {"version": 1, "label": "guests", "state": [{"step": {"name": "Ada"}}]}


def test_an_item_added_with_no_response_coming_still_reaches_the_store():
    """The registry is session-scoped even where the runs are not, so this
    is what an agent adding an item depends on: with no request behind the
    context there is no middleware to save the session later, and an item
    written into an unsaved one is an item nobody can list."""
    session = SessionStore()
    session.create()
    store = SessionItemStore(WizardContext(session=session), "default")

    store.add_item("guests", "a")

    reopened = SessionStore(session_key=session.session_key)
    listed = SessionItemStore(WizardContext(session=reopened), "default")
    assert listed.item_ids("guests") == ["a"]


# --- the item registry -----------------------------------------------------


def test_a_collection_that_was_never_started_lists_no_items():
    assert SessionItemStore(_Context(), "default").item_ids("guests") == []


def test_items_are_listed_in_the_order_the_user_added_them():
    context = _Context()
    store = SessionItemStore(context, "default")

    store.add_item("guests", "a")
    store.add_item("guests", "b")

    assert store.item_ids("guests") == ["a", "b"]
    assert context.session.modified is True


def test_adding_an_item_already_listed_does_not_list_it_twice():
    """The page's uniqueness rule holds by construction rather than by check."""
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")

    store.add_item("guests", "a")

    assert store.item_ids("guests") == ["a"]


def test_removing_an_item_keeps_the_order_of_the_rest():
    """The whole reason identity is opaque: nothing renumbers, so a live URL
    for the item after the hole still names the same item."""
    store = SessionItemStore(_Context(), "default")
    for item_id in ("a", "b", "c"):
        store.add_item("guests", item_id)

    store.remove_item("guests", "b")

    assert store.item_ids("guests") == ["a", "c"]


def test_removing_an_item_that_was_never_listed_is_not_an_error():
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")

    store.remove_item("guests", "nope")

    assert store.item_ids("guests") == ["a"]


def test_has_item_answers_without_an_exception_to_catch():
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")

    assert store.has_item("guests", "a") is True
    assert store.has_item("guests", "b") is False


def test_collections_keep_their_own_registries():
    store = SessionItemStore(_Context(), "default")

    store.add_item("guests", "a")
    store.add_item("courses", "b")

    assert store.item_ids("guests") == ["a"]
    assert store.item_ids("courses") == ["b"]


# --- cached titles ---------------------------------------------------------


def test_an_item_that_has_never_finished_has_no_title():
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")

    assert store.get_item_title("guests", "a") is None


def test_a_title_is_cached_per_item_and_read_back_as_a_string():
    """What keeps a collection of thirty items costing thirty dict lookups
    rather than thirty walks."""
    context = _Context()
    store = SessionItemStore(context, "default")
    store.add_item("guests", "a")
    store.add_item("guests", "b")

    store.set_item_title("guests", "a", "Ada Lovelace")

    assert store.get_item_title("guests", "a") == "Ada Lovelace"
    assert store.get_item_title("guests", "b") is None
    assert context.session.modified is True


def test_a_title_lands_on_the_item_it_names_and_no_other():
    """The registry is a list, so titling walks past the items before it."""
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")
    store.add_item("guests", "b")

    store.set_item_title("guests", "b", "Grace Hopper")

    assert store.get_item_title("guests", "a") is None
    assert store.get_item_title("guests", "b") == "Grace Hopper"


def test_a_title_can_be_cleared_for_an_item_whose_answers_were_discarded():
    """Otherwise the row shows a name for an item with nothing behind it."""
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")
    store.set_item_title("guests", "a", "Ada Lovelace")

    store.set_item_title("guests", "a", None)

    assert store.get_item_title("guests", "a") is None


def test_titling_an_item_the_registry_does_not_list_is_not_an_error():
    store = SessionItemStore(_Context(), "default")

    store.set_item_title("guests", "gone", "Ada Lovelace")

    assert store.get_item_title("guests", "gone") is None


def test_removing_an_item_takes_its_title_with_it():
    """Titles ride inside the item entry, so removal cannot orphan one."""
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")
    store.set_item_title("guests", "a", "Ada Lovelace")

    store.remove_item("guests", "a")
    store.add_item("guests", "a")

    assert store.get_item_title("guests", "a") is None


# --- the user's answer -----------------------------------------------------


def test_a_collection_starts_out_with_the_user_having_declared_nothing():
    assert SessionItemStore(_Context(), "default").is_declared_done("guests") is False


def test_the_users_answer_to_add_another_round_trips():
    """Not "are all the items finished" — a different question with a
    different answer."""
    context = _Context()
    store = SessionItemStore(context, "default")

    store.set_declared_done("guests", True)

    assert store.is_declared_done("guests") is True
    assert context.session.modified is True

    store.set_declared_done("guests", False)

    assert store.is_declared_done("guests") is False


# --- composing with a page's bookkeeping ------------------------------------


def test_a_collections_items_and_a_pages_sections_share_one_key_space():
    """An item's run and stash live under an ordinary section key the view
    composes, so the nine inherited methods are untouched."""
    store = SessionItemStore(_Context(), "default")

    store.set_run("guests", "run-1")
    store.set_run("guests:a", "run-2")
    store.put_stash("guests:a", _PAYLOAD)

    assert store.get_run("guests") == "run-1"
    assert store.get_run("guests:a") == "run-2"
    assert store.has_stash("guests") is False
    assert store.get_stash("guests:a") == _PAYLOAD


def test_a_collections_registry_is_the_journeys_own():
    """Two journeys with a collection under the same key are two lists."""
    context = _Context()
    SessionItemStore(context, "app-1").add_item("guests", "a")

    assert SessionItemStore(context, "app-2").item_ids("guests") == []
    assert context.session["gandalf_journeys"]["app-1"]["lists"] == {
        "guests": {"items": [{"id": "a", "title": None}]}
    }


def test_completing_the_journey_takes_the_registry_with_it():
    """A tombstone lists no items — the same tearing-down the sections get."""
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")
    store.set_declared_done("guests", True)

    store.complete()

    assert store.item_ids("guests") == []
    assert store.is_declared_done("guests") is False
    assert store.is_complete() is True


def test_the_registry_is_not_derivable_from_the_stash_keys():
    """`keys()` reports what has finished; the registry reports what exists.
    A half-finished item is in one and not the other, which is exactly why
    the registry has to be written down."""
    store = SessionItemStore(_Context(), "default")
    store.add_item("guests", "a")
    store.add_item("guests", "b")
    store.put_stash("guests:a", _PAYLOAD)

    assert store.keys() == ["guests:a"]
    assert store.item_ids("guests") == ["a", "b"]
