"""Every seam that reads or writes an answer, against every shape that
breaks a naive implementation of one.

A seam here is a place the library asks a step about its answer rather
than reading it off a form or a POST: what it answered, what it refused,
how it lists, how it describes itself, how an answer converts back into a
submission, how an answered step re-renders, how the fold reads it, and
how a summary page shows it.

A shape is a form whose answer and whose POST keys do not line up the
obvious way. Each of the four awkward ones violates a different
assumption, and the plain step is the control — the shape under which a
broken seam still looks like it works. That is the whole reason this file
is a matrix rather than a list of tests: every bug this family has
produced was a seam that had only ever met the control.

Adding a shape means adding a row here and a step to
`ShapeMatrixWizardViewSet`; adding a seam means adding a test, which then
runs against every shape at once.
"""

from __future__ import annotations

from collections.abc import Callable
import datetime
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
import pytest

from gandalf.driver import RunDriver
from tests.testapp.views import ShapeMatrixWizardViewSet


FORMSET_MANAGEMENT = {
    "form-INITIAL_FORMS": "0",
    "form-MIN_NUM_FORMS": "0",
    "form-MAX_NUM_FORMS": "7",
}


def _photo() -> SimpleUploadedFile:
    """A fresh upload each time: a file object is read once."""
    return SimpleUploadedFile(
        "badge.png", b"not-really-a-png", content_type="image/png"
    )


@dataclass(frozen=True)
class Shape:
    """One row of the matrix: a step, what a browser posts to it, and what
    every seam should then say about it."""

    id: str
    step: str
    #: A callable rather than a value: an upload is consumed when it is read.
    post: Callable[[], dict[str, Any]]
    #: What `.answer` must be. A callable when the value cannot be compared
    #: directly — a stored upload is an object, not data.
    answer: Any
    #: The names of the bound fields the answer reads as, in display order.
    fields: list[str]
    #: Fragments the edit render of an answered step must contain.
    refilled: list[str]
    #: A POST this step must refuse, and the error keys it must refuse it with.
    invalid: dict[str, Any]
    error_keys: list[str]
    #: The JSON Schema `type` this step describes itself with.
    schema_type: str
    #: Whether the fold takes this answer. A formset answers with rows, which
    #: `MergeCleanedData` skips deliberately — it has no field names to merge.
    folds: bool = True
    #: What the summary page must show for this step, as a fragment of the
    #: rendered answer text.
    summary_shows: str = ""
    #: Uploads for a driver submission, which take them beside the data.
    driver_files: Callable[[], dict[str, Any]] = field(default=dict)

    def check_answer(self, actual: Any) -> None:
        if callable(self.answer):
            self.answer(actual)
        else:
            assert actual == self.answer


SHAPES = (
    Shape(
        id="plain",
        step="plain",
        post=lambda: {"name": "Ada"},
        answer={"name": "Ada"},
        fields=["name"],
        refilled=['name="name"', 'value="Ada"'],
        invalid={},
        error_keys=["name"],
        schema_type="object",
        summary_shows="Ada",
    ),
    Shape(
        id="multiwidget",
        step="multiwidget",
        post=lambda: {
            "start_date_0": "3",
            "start_date_1": "9",
            "start_date_2": "2026",
        },
        answer={"start_date": datetime.date(2026, 9, 3)},
        fields=["start_date"],
        refilled=[
            'name="start_date_0" value="3"',
            'name="start_date_1" value="9"',
            'name="start_date_2" value="2026"',
        ],
        # The 31st of February: three integers that each clean and cannot be
        # a date, so `compress()` is what refuses it.
        invalid={"start_date_0": "31", "start_date_1": "2", "start_date_2": "2026"},
        error_keys=["start_date"],
        schema_type="object",
        summary_shows="2026",
    ),
    Shape(
        id="ownkeys",
        step="ownkeys",
        post=lambda: {
            "closing_date_day": "3",
            "closing_date_month": "9",
            "closing_date_year": "2026",
        },
        answer={"closing_date": datetime.date(2026, 9, 3)},
        fields=["closing_date"],
        refilled=['name="closing_date_day"', 'value="2026" selected'],
        invalid={
            "closing_date_day": "",
            "closing_date_month": "9",
            "closing_date_year": "2026",
        },
        error_keys=["closing_date"],
        schema_type="object",
        summary_shows="2026",
    ),
    Shape(
        id="prefixed",
        step="prefixed",
        post=lambda: {"contact-email": "ada@example.com"},
        answer={"email": "ada@example.com"},
        fields=["email"],
        refilled=['name="contact-email"', 'value="ada@example.com"'],
        invalid={"contact-email": "not-an-email"},
        error_keys=["email"],
        schema_type="object",
        summary_shows="ada@example.com",
    ),
    Shape(
        id="formset",
        step="formset",
        post=lambda: {
            **FORMSET_MANAGEMENT,
            "form-TOTAL_FORMS": "2",
            "form-0-day": "Monday",
            "form-0-opens": "09:00",
            "form-1-day": "Tuesday",
            "form-1-opens": "10:00",
        },
        answer=[
            {"day": "Monday", "opens": "09:00"},
            {"day": "Tuesday", "opens": "10:00"},
        ],
        fields=["day", "opens", "day", "opens"],
        refilled=[
            'name="form-0-day" value="Monday"',
            'name="form-1-opens" value="10:00"',
        ],
        invalid={
            **FORMSET_MANAGEMENT,
            "form-TOTAL_FORMS": "1",
            "form-0-day": "",
            "form-0-opens": "09:00",
        },
        error_keys=["0-day"],
        schema_type="array",
        folds=False,
        summary_shows="Monday",
    ),
    Shape(
        id="file",
        step="file",
        post=lambda: {"photo": _photo()},
        # A stored upload is an object; only its name is data.
        answer=lambda actual: (
            list(actual) == ["photo"] and actual["photo"].name.endswith("badge.png")
        )
        or pytest.fail(f"expected a stored badge.png, got {actual!r}"),
        fields=["photo"],
        # A browser never re-sends a file input, so the refill is the widget
        # saying what is already held rather than a value attribute.
        refilled=["badge.png"],
        invalid={},
        error_keys=["photo"],
        schema_type="object",
        summary_shows="badge.png",
        driver_files=lambda: {"photo": _photo()},
    ),
)

IDS = [shape.id for shape in SHAPES]


def shapes(**gaps: str):
    """The matrix rows for one seam, with `gaps` naming the cells that seam
    does not handle yet and why.

    A gap is `xfail(strict=True)` rather than a skip or a deletion, so the
    suite stays green while the cell stays *stated*: the day the seam
    learns the shape, the test fails for passing and whoever fixed it is
    told to come and delete the marker. An empty cell nobody can see is
    how this family of bugs got here in the first place.
    """
    return [
        pytest.param(
            shape,
            id=shape.id,
            marks=pytest.mark.xfail(strict=True, reason=gaps[shape.id]),
        )
        if shape.id in gaps
        else pytest.param(shape, id=shape.id)
        for shape in SHAPES
    ]


@pytest.fixture
def answered_run(wizard_driver, isolated_media_root):
    """One run of the matrix wizard with every shape answered."""
    run = wizard_driver("shape-matrix-wizard").start()
    run.post_steps([(shape.step, shape.post()) for shape in SHAPES])
    return run


@pytest.fixture
def driver_for(client, answered_run):
    """A `RunDriver` over the run the browser just answered."""

    def build() -> RunDriver:
        return RunDriver.resume(
            ShapeMatrixWizardViewSet,
            answered_run.run_id,
            session=client.session,
        )

    return build


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_answer_reads_every_shape_back(shape, driver_for):
    """Seam: `RuntimeStep.answer` / `get_answer()`."""
    step = driver_for().run.path.find_step(name=shape.step)

    shape.check_answer(step.answer)


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_errors_is_empty_for_a_valid_answer(shape, driver_for):
    """Seam: `RuntimeStep.errors` / `answer_errors()`. A valid answer
    reports nothing refused — the reading a formset's `[{}]` gets wrong."""
    step = driver_for().run.path.find_step(name=shape.step)

    assert step.errors == {}


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_errors_names_what_a_refused_answer_refused(
    shape, wizard_driver, isolated_media_root
):
    """Seam: `answer_errors()` on the way back, keyed so a caller can say
    which field it was."""
    run = wizard_driver("shape-matrix-wizard").start()
    for earlier in SHAPES:
        if earlier.step == shape.step:
            break
        run.post_step(earlier.step, earlier.post(), follow=True)

    run.post_step(shape.step, shape.invalid, follow=True)

    driver = RunDriver.resume(
        ShapeMatrixWizardViewSet, run.run_id, session=run.driver.client.session
    )
    step = driver.run.path.find_step(name=shape.step)
    assert sorted(step.errors) == sorted(shape.error_keys)


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_answer_fields_lists_the_fields_that_asked(shape, driver_for):
    """Seam: `answer_fields` / `get_answer_fields()` — what a summary page
    iterates."""
    step = driver_for().run.path.find_step(name=shape.step)

    assert [bound.name for bound in step.answer_fields] == shape.fields


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_schema_describes_every_shape(shape, driver_for):
    """Seam: `get_answer_schema()` — what an agent is told the step asks."""
    outline = {
        entry["step"]: entry
        for entry in driver_for().outline()
        if entry["kind"] == "step"
    }

    assert outline[shape.step]["schema"]["type"] == shape.schema_type


@pytest.mark.parametrize(
    "shape",
    shapes(
        file=(
            "answers() hands the stored upload back inside the answer, and "
            "submit() refuses a file in `data` because state is JSON — so the "
            "answer it just gave cannot be handed straight back."
        ),
    ),
)
def test_seam_an_answer_submits_straight_back(shape, driver_for):
    """Seam: `get_submission()` — the inverse. Reading a step and
    submitting what you were handed is the round trip `submit()` promises,
    and it has to survive keys that are not field names."""
    driver = driver_for()
    answer = driver.answers()[shape.step]

    result = driver.submit(answer, step=shape.step, files=shape.driver_files())

    assert result.errors == {}
    assert result.status != "invalid"


@pytest.mark.parametrize(
    "shape",
    shapes(
        file=(
            "the answer reaches the form as `initial`, but ClearableFileInput "
            "shows what is held only for a value with a `url`, and StoredUpload "
            "has none by design — so the page cannot say which file it holds. "
            "The summary page can; this one cannot."
        ),
    ),
)
def test_seam_editing_an_answered_step_refills_it(shape, answered_run):
    """Seam: the edit render — `render_step()` handing the answer to the
    view as `initial`."""
    response = answered_run.get_step(shape.step)

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    for fragment in shape.refilled:
        assert fragment in content, f"{shape.id}: {fragment!r} missing from the refill"


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_the_fold_takes_every_shape_it_can(shape, driver_for):
    """Seam: `run.answers` / `MergeCleanedData`. A formset is skipped on
    purpose — rows carry no field names to merge — and that is the one
    thing the fold must do deliberately rather than by accident."""
    folded = driver_for().run.answers

    if not shape.folds:
        assert not set(folded) & {"day", "opens"}
        return
    step = driver_for().run.path.find_step(name=shape.step)
    for name in step.answer:
        assert name in folded


@pytest.mark.parametrize("shape", SHAPES, ids=IDS)
def test_seam_the_summary_shows_every_shape(shape, answered_run):
    """Seam: the check-your-answers page, which reads a step through
    `answer_fields` and formats what it finds."""
    rows = answered_run.get_step("summary").context["summary"]

    shown = " ".join(str(row.answer) for row in rows if row.step.name == shape.step)
    assert shape.summary_shows in shown
