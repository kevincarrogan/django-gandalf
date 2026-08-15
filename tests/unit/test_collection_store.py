"""Unit coverage for `SessionCollectionStore` — a collection's registry.

A hub's sections are declared, so the store never has to enumerate them. A
collection's items are not: the user grows them, and no reading of runs or
stashes can hand back the list — the stash key space holds only the items that
have *finished*. So the registry is explicit, ordered, and separate, and an
item exists from the moment it is added, which is what lets a half-finished one
still have a row.
"""

from gandalf.storage import SessionCollectionStore


class _Session(dict):
    modified = False


class _Request:
    def __init__(self, session=None):
        self.session = _Session()
        if session:
            self.session.update(session)


_PAYLOAD = {"version": 1, "label": "guests", "state": [{"step": {"name": "Ada"}}]}


# --- the item registry -----------------------------------------------------


def test_a_collection_that_was_never_started_lists_no_items():
    assert SessionCollectionStore(_Request()).item_ids("guests") == []


def test_items_are_listed_in_the_order_the_user_added_them():
    request = _Request()
    store = SessionCollectionStore(request)

    store.add_item("guests", "a")
    store.add_item("guests", "b")

    assert store.item_ids("guests") == ["a", "b"]
    assert request.session.modified is True


def test_adding_an_item_already_listed_does_not_list_it_twice():
    """The hub's uniqueness rule holds by construction rather than by check."""
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")

    store.add_item("guests", "a")

    assert store.item_ids("guests") == ["a"]


def test_removing_an_item_keeps_the_order_of_the_rest():
    """The whole reason identity is opaque: nothing renumbers, so a live URL
    for the item after the hole still names the same item."""
    store = SessionCollectionStore(_Request())
    for item_id in ("a", "b", "c"):
        store.add_item("guests", item_id)

    store.remove_item("guests", "b")

    assert store.item_ids("guests") == ["a", "c"]


def test_removing_an_item_that_was_never_listed_is_not_an_error():
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")

    store.remove_item("guests", "nope")

    assert store.item_ids("guests") == ["a"]


def test_has_item_answers_without_an_exception_to_catch():
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")

    assert store.has_item("guests", "a") is True
    assert store.has_item("guests", "b") is False


def test_collections_keep_their_own_registries():
    store = SessionCollectionStore(_Request())

    store.add_item("guests", "a")
    store.add_item("courses", "b")

    assert store.item_ids("guests") == ["a"]
    assert store.item_ids("courses") == ["b"]


# --- cached titles ---------------------------------------------------------


def test_an_item_that_has_never_finished_has_no_title():
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")

    assert store.get_item_title("guests", "a") is None


def test_a_title_is_cached_per_item_and_read_back_as_a_string():
    """What keeps a collection of thirty items costing thirty dict lookups
    rather than thirty walks."""
    request = _Request()
    store = SessionCollectionStore(request)
    store.add_item("guests", "a")
    store.add_item("guests", "b")

    store.set_item_title("guests", "a", "Ada Lovelace")

    assert store.get_item_title("guests", "a") == "Ada Lovelace"
    assert store.get_item_title("guests", "b") is None
    assert request.session.modified is True


def test_a_title_lands_on_the_item_it_names_and_no_other():
    """The registry is a list, so titling walks past the items before it."""
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")
    store.add_item("guests", "b")

    store.set_item_title("guests", "b", "Grace Hopper")

    assert store.get_item_title("guests", "a") is None
    assert store.get_item_title("guests", "b") == "Grace Hopper"


def test_a_title_can_be_cleared_for_an_item_whose_answers_were_discarded():
    """Otherwise the row shows a name for an item with nothing behind it."""
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")
    store.set_item_title("guests", "a", "Ada Lovelace")

    store.set_item_title("guests", "a", None)

    assert store.get_item_title("guests", "a") is None


def test_titling_an_item_the_registry_does_not_list_is_not_an_error():
    store = SessionCollectionStore(_Request())

    store.set_item_title("guests", "gone", "Ada Lovelace")

    assert store.get_item_title("guests", "gone") is None


def test_removing_an_item_takes_its_title_with_it():
    """Titles ride inside the item entry, so removal cannot orphan one."""
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")
    store.set_item_title("guests", "a", "Ada Lovelace")

    store.remove_item("guests", "a")
    store.add_item("guests", "a")

    assert store.get_item_title("guests", "a") is None


# --- the user's answer -----------------------------------------------------


def test_a_collection_starts_out_with_the_user_having_declared_nothing():
    assert SessionCollectionStore(_Request()).is_declared_done("guests") is False


def test_the_users_answer_to_add_another_round_trips():
    """Not "are all the items finished" — a different question with a
    different answer."""
    request = _Request()
    store = SessionCollectionStore(request)

    store.set_declared_done("guests", True)

    assert store.is_declared_done("guests") is True
    assert request.session.modified is True

    store.set_declared_done("guests", False)

    assert store.is_declared_done("guests") is False


# --- composing with a hub's bookkeeping ------------------------------------


def test_a_collections_items_and_a_hubs_sections_share_one_key_space():
    """An item's run and stash live under an ordinary section key the view
    composes, so the nine inherited methods are untouched."""
    store = SessionCollectionStore(_Request())

    store.set_run("guests", "run-1")
    store.set_run("guests:a", "run-2")
    store.put_stash("guests:a", _PAYLOAD)

    assert store.get_run("guests") == "run-1"
    assert store.get_run("guests:a") == "run-2"
    assert store.has_stash("guests") is False
    assert store.get_stash("guests:a") == _PAYLOAD


def test_the_registry_is_not_derivable_from_the_stash_keys():
    """`keys()` reports what has finished; the registry reports what exists.
    A half-finished item is in one and not the other, which is exactly why
    the registry has to be written down."""
    store = SessionCollectionStore(_Request())
    store.add_item("guests", "a")
    store.add_item("guests", "b")
    store.put_stash("guests:a", _PAYLOAD)

    assert store.keys() == ["guests:a"]
    assert store.item_ids("guests") == ["a", "b"]
