import pytest

from gandalf.escapes import Advance, Escape, Obliterate, Park
from gandalf.runtime import Cursor


@pytest.mark.parametrize("escape_class", [Park, Advance, Obliterate])
def test_every_escape_is_catchable_as_the_base_class(escape_class):
    with pytest.raises(Escape):
        raise escape_class("/elsewhere/")


def test_escape_carries_the_redirect_target():
    escape = Escape("/elsewhere/")

    assert escape.to == "/elsewhere/"
    assert escape.redirect_args == ()
    assert escape.redirect_kwargs == {}
    assert escape.permanent is False


def test_escape_carries_redirect_arguments():
    escape = Park("account-detail", "ada", permanent=True, section="billing")

    assert escape.to == "account-detail"
    assert escape.redirect_args == ("ada",)
    assert escape.redirect_kwargs == {"section": "billing"}
    assert escape.permanent is True


def test_cursor_finds_the_escape_recorded_for_a_step():
    declaration = object()
    escape = Park("/elsewhere/")
    cursor = Cursor(node=None, state=None, escapes=((declaration, escape),))

    assert cursor.escape_for(declaration) is escape


def test_cursor_has_no_escape_for_an_unrecorded_step():
    cursor = Cursor(node=None, state=None, escapes=((object(), Park("/a/")),))

    assert cursor.escape_for(object()) is None


def test_cursor_has_no_escapes_by_default():
    cursor = Cursor(node=None, state=None)

    assert cursor.escapes == ()
