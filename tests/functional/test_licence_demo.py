"""The licence check, driven without a model.

The demo's claim is that an agent can be handed a photograph, read it, and
fill a form from what it says. A model is what does the reading, and a
test cannot afford one — so this proves everything either side of that:
the scan goes in, comes back out as bytes, the details it yields are
placed, and the run stops at the confirmation for a person.

What is left untested here is the only part that needs a model, which is
deliberate. `examples/scenarios.py` is where that is measured, against a
real one, for money.
"""

from django.core.files.uploadedfile import SimpleUploadedFile

from examples.licence import LicenceCheckViewSet
from gandalf.driver import RunDriver

_SCAN = b"pretend-image-bytes"
_DETAILS = {
    "licence_number": "CARRO806161K99AB",
    "surname": "Carrogan",
    "date_of_birth": "1986-08-16",
    "expires_on": "2031-08-15",
}


def _driver():
    return RunDriver.begin(LicenceCheckViewSet)


def test_an_agent_places_a_photograph_and_reads_it_back(isolated_media_root):
    """The two halves the driver could not do until #66 and #67.

    A file arriving in the conversation is the person's, but placing it in
    the run is the agent's doing — so it lands marked as the agent's, and
    the ordinary "whose answer is this" rule covers a document with no
    special case for it.
    """
    driver = _driver()

    placed = driver.submit(
        {}, files={"scan": SimpleUploadedFile("licence.png", _SCAN, "image/png")}
    )

    assert placed.status == "advanced"
    assert placed.next_step == "details"

    placement = driver.placements()["scan"]
    assert driver.open_file(placement.files["scan"]).read() == _SCAN
    assert placement.metadata == {"unattended": True}


def test_the_run_is_describable_while_it_holds_a_photograph(isolated_media_root):
    """The call every tool makes, on a run with a file in it.

    Before #65 this raised `TypeError` — `cleaned_data` for a `FileField`
    is an open upload — which made this whole demo impossible rather than
    merely awkward. The scan reads back as the reference state holds.
    """
    driver = _driver()
    driver.submit(
        {}, files={"scan": SimpleUploadedFile("licence.png", _SCAN, "image/png")}
    )

    described = driver.describe(json_safe=True)

    assert described.step == "details"
    assert described.answers["scan"]["scan"]["name"] == "licence.png"


def test_the_agent_fills_the_details_and_stops_at_the_confirmation(
    isolated_media_root,
):
    """The handover. Everything the photograph says is fillable; the one
    thing it cannot say is whether the person agrees it was read right."""
    driver = _driver()
    driver.submit(
        {}, files={"scan": SimpleUploadedFile("licence.png", _SCAN, "image/png")}
    )

    filled = driver.submit(_DETAILS)

    assert filled.status == "advanced"
    assert filled.next_step == "confirm"
    assert not driver.describe().complete


def test_a_person_may_correct_what_the_agent_read(isolated_media_root):
    """The reason the confirmation is a person's. A misread character looks
    exactly like a correctly read one, so the run has to stay editable
    after the agent has been over it."""
    driver = _driver()
    driver.submit(
        {}, files={"scan": SimpleUploadedFile("licence.png", _SCAN, "image/png")}
    )
    driver.submit(_DETAILS)

    driver.submit(
        {**_DETAILS, "licence_number": "CARR0806161K99AB"},
        step="details",
        metadata={},
    )

    placement = driver.placements()["details"]
    assert placement.answers["licence_number"] == "CARR0806161K99AB"
    # Recorded as theirs, so the demo's edit rule now protects it from the
    # agent — the correction is the last word, not an invitation to retry.
    assert placement.metadata == {}
