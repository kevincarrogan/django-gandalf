from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from django import forms
from django.views.generic.edit import FormView

from gandalf.types import Answer, Submission, WizardRequest


if TYPE_CHECKING:
    # `FormView` is generic to type checkers but not at runtime — it carries
    # no `__class_getitem__` in any supported Django — so the parameter is
    # supplied only where it is read. `BaseForm` rather than `Form` so that
    # `ModelForm` steps type-check too.
    _StepFormViewBase = FormView[forms.BaseForm]

    #: The view class behind a step: `StepFormView`, a plain Django
    #: `FormView` subclass a step declared for itself, or one this module
    #: generated for a bare `Form`.
    StepViewClass: TypeAlias = type[FormView[Any]]

    #: What `.step()` accepts: a form to generate a view for, or a view
    #: that brings its own.
    StepDeclaration: TypeAlias = "type[forms.Form] | StepViewClass"
else:
    _StepFormViewBase = FormView


class StepFormView(_StepFormViewBase):
    """Base class for a step that brings its own view.

    A step view is dispatched as an ordinary Django view, but the wizard
    reads only the *status code* of its response — a 3xx means "this answer
    stands, carry on" — and then discards the response. The success URL is
    therefore never followed, and every step view ends up writing the same
    no-op redirect back onto itself. This class writes it once.

    Subclass it in place of Django's `FormView` when a step needs view-level
    behaviour, and give it a `template_name` (the viewset's default only
    reaches the views Gandalf generates):

        from gandalf.form_views import StepFormView


        class BillingStepView(StepFormView):
            form_class = BillingForm
            template_name = "billing/step.html"

            def get_initial(self):
                ...

    Nothing else changes: it is a plain `FormView`, so it keeps its own
    configuration and can be mounted as a standalone view outside the
    wizard — override `get_success_url()` there to go somewhere real.
    """

    #: Narrowed from `View.request`: a step view is dispatched inside a
    #: wizard, which is what puts `request.run` there. A `StepFormView`
    #: mounted standalone (see below) is handed a plain request and simply
    #: has no run to read.
    request: WizardRequest

    # Restated from `FormMixin` so the class is concrete about what a step's
    # form may be. Inherited, it is a variable of the generic parameter, and
    # assigning it through the class — as `form_view_factory` does — is
    # ambiguous to a type checker.
    form_class: type[forms.BaseForm] | None = None

    def get_success_url(self) -> str:
        return self.request.path

    #: Whether validating this step *performs* the check it describes —
    #: proving a one-time code, authorising a card, claiming a reference.
    #: `False` for the overwhelming majority of steps, whose `clean()` is a
    #: pure function of what was submitted.
    #:
    #: Declared rather than derived because only the step knows: a
    #: `clean()` that reaches out is indistinguishable from one that does
    #: not until it has already reached. It is the dry-run half of
    #: `run.proof()`, which is the durable half — a step that needs one
    #: almost certainly wants this too.
    #:
    #: What reads it is `RunDriver.check()`, which reports such a step as
    #: `unchecked` rather than spending what it was asked about. Nothing on
    #: the HTTP path is affected: a real submission performs the check, as
    #: it must.
    consumes_what_it_checks: bool = False

    def get_answer_errors(self, form: Any) -> dict[str, list[dict[str, Any]]]:
        """What this step refused, by field name, in `get_json_data()` shape.

        Empty when the step is satisfied — callers read the emptiness, not
        the underlying attribute, which is the whole point of asking here.
        `BaseForm.errors` answers both questions at once because an
        `ErrorDict` is falsy when empty; a formset's is a *list* of one
        entry per row and is truthy even when every row is valid, so a
        caller testing it directly concludes the opposite of the truth.

        Override alongside a form object that is not a `BaseForm`, so that
        the driver, and anything else asking whether this step is settled,
        gets an answer from the step rather than from a Django attribute it
        has assumed the shape of.
        """
        return cast(
            "dict[str, list[dict[str, Any]]]",
            form.errors.get_json_data(),
        )

    def get_answer(self, form: Any) -> Any:
        """What this step was answered with.

        A mapping of field name to cleaned value for a form, and whatever
        shape suits an object that is not one — a formset answers with a
        list of one mapping per row. Everything reading a run's answers
        goes through here, so a step's answer has one shape rather than a
        shape per reader.
        """
        return form.cleaned_data

    def get_answer_fields(self, form: Any) -> Iterable[Any]:
        """The bound fields this step's answer reads as, in display order.

        A `BaseForm` yields its own, which is what a summary page lists.
        Override beside a form object that is not one, so that the page
        shows the answers rather than iterating something that is not a
        bound field at all.
        """
        return list(form)

    def get_answer_schema(self, form: Any) -> dict[str, Any]:
        """This step as a JSON Schema — what an agent is told it asks.

        Override beside a form object `form_json_schema()` cannot read: it
        walks `form.fields`, which only a `BaseForm` has.
        """
        # Imported here rather than at module scope: `gandalf.driver` is
        # built on top of this module, and the schema vocabulary lives with
        # the driver that publishes it.
        from gandalf.driver import form_json_schema

        return form_json_schema(form)

    def get_submission(self, answer: Answer) -> Submission:
        """`answer` as the POST that would have produced it.

        The inverse of `get_answer()`, and what lets a caller read a step,
        change one field and submit it straight back with nothing to
        convert in between. A form's answer is already the shape a browser
        posts — field name to value — so this only puts the step's prefix
        around it.

        Override beside a form object whose answer is not a submission. It
        is the one direction the other four hooks do not cover: they all
        describe what a step holds, and this is how something gets *into*
        it.
        """
        return _under_prefix(self.get_prefix(), answer)


class FormSetStepView(StepFormView):
    """A step whose form object is a formset rather than a form.

    `FormView` builds a formset from `data`, `files`, `initial` and `prefix`
    exactly as it builds a form, so a formset step needs no special handling
    to be *served* — that much works with a plain `StepFormView`. What it
    needs is somewhere to say how the reads a formset answers differently
    should be read, and this is that place:

        from gandalf.form_views import FormSetStepView


        class OpeningHoursStepView(FormSetStepView):
            form_class = OpeningHoursFormSet
            template_name = "hours/step.html"

    A row's errors are keyed by the row's index and the field name —
    `"0-email"` — because `"email"` names nothing when several people are
    being asked at once. Errors belonging to the formset itself rather than
    to any row (`min_num`, `max_num`, a `clean()` on the formset) keep
    Django's own `__all__`.
    """

    def get_answer_errors(self, form: Any) -> dict[str, list[dict[str, Any]]]:
        errors: dict[str, list[dict[str, Any]]] = {}
        for index, row in enumerate(form.errors):
            for field, messages in row.get_json_data().items():
                errors[f"{index}-{field}"] = messages
        non_form = form.non_form_errors()
        if non_form:
            errors["__all__"] = non_form.get_json_data()
        return errors

    def get_answer(self, form: Any) -> Any:
        """Each row's own cleaned data, in the order they were entered.

        Read off the rows rather than off the formset, which is the same
        list when everything validated — `BaseFormSet.cleaned_data` *is*
        each row's — and the only reading that survives when something did
        not. A formset refuses `cleaned_data` outright unless the whole
        thing is valid, and a run parked on a rejected submission is
        exactly the state anything reading a run is most likely to meet:
        the walk keeps what was rejected so the errors can be re-reported
        until a valid answer replaces them.

        A row that failed carries what it managed to clean, which is what
        a plain form does too.
        """
        return [row.cleaned_data for row in form.forms]

    def get_answer_fields(self, form: Any) -> Iterable[Any]:
        """Every row's fields, row by row, in the order they were entered.

        A formset declares no fields at step level — they belong to each of
        the n rows it repeats — so iterating it yields *forms*, and a page
        listing them would be listing the wrong objects. Flattening the rows
        is plain rather than pretty, and deliberately so: what three
        organisers should read like on a check-your-answers page is the
        page's decision, made with `summary.Render` or, past what a
        template can say, `SummaryMixin.build_summary_row()`. What
        it must not do is show nothing, because then the answers cannot be
        checked and nobody can see that they are missing.
        """
        return [bound_field for row in form for bound_field in row]

    def get_answer_schema(self, form: Any) -> dict[str, Any]:
        """An array of rows, rather than an object of fields.

        The row schema comes from `empty_form`, which is the unbound row
        the formset would render next, so it describes what a row *asks*
        rather than what any particular row was answered with. `minItems`
        is stated only when the formset actually enforces `min_num` —
        `validate_min` off means the rows are rendered, not required.
        """
        # Imported here for the reason `StepFormView.get_answer_schema` is.
        from gandalf.driver import form_json_schema

        schema: dict[str, Any] = {
            "type": "array",
            "items": form_json_schema(form.empty_form),
        }
        if form.validate_min:
            schema["minItems"] = form.min_num
        if form.validate_max:
            schema["maxItems"] = form.max_num
        return schema

    def get_submission(self, answer: Answer) -> Submission:
        """Rows as the management form and n prefixed rows a browser sends.

        A formset's answer is the one that does not already read as a
        submission: `[{"day": "Monday"}, ...]` says nothing about
        `TOTAL_FORMS`, and until this a caller reading a formset step back
        could not submit what it had just been handed. The counts come from
        the unbound formset, so they are the ones this step would have
        rendered.

        A mapping is passed through unchanged. That is what a browser
        posted and what the HTTP path stores, so it is a submission
        already; rows are the addition rather than the replacement.
        """
        if not isinstance(answer, list):
            return super().get_submission(answer)
        # `get_form()` is typed as the `BaseForm` a step usually holds; on
        # this class it is the formset the counts come from.
        formset = cast("Any", self.get_form())
        prefix = formset.prefix
        submission: Submission = {
            f"{prefix}-TOTAL_FORMS": str(len(answer)),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": str(formset.min_num),
            f"{prefix}-MAX_NUM_FORMS": str(formset.max_num),
        }
        for index, row in enumerate(answer):
            for name, value in row.items():
                submission[f"{prefix}-{index}-{name}"] = value
        return submission


def answer_errors(view: Any, form: Any) -> dict[str, list[dict[str, Any]]]:
    """What a step refused, by field name, empty when it is settled.

    Asked of the step's view, because only the view knows what kind of
    object its `get_form()` returned. A step declared with a bare Django
    `FormView` rather than a `StepFormView` carries no `get_answer_errors`,
    has no say, and gets the `BaseForm` reading.

    The one place this fallback is spelled out: every reader that has a
    view and a form in hand goes through here, so "a step with no say gets
    the form's own answer" is a rule rather than a habit.
    """
    reader = getattr(view, "get_answer_errors", None)
    if reader is None:
        return cast("dict[str, list[dict[str, Any]]]", form.errors.get_json_data())
    return cast("dict[str, list[dict[str, Any]]]", reader(form))


def answer_submission(view: Any, answer: Answer) -> Submission:
    """`answer` as the POST that would have produced it.

    `answer_errors()`'s counterpart on the way in, and the same rule: a
    step declared with a bare Django `FormView` carries no
    `get_submission`, has no say, and gets the plain reading — its answer
    is already a mapping of field name to value, under the view's prefix.
    """
    writer = getattr(view, "get_submission", None)
    if writer is None:
        return _under_prefix(view.get_prefix(), answer)
    return cast("Submission", writer(answer))


def _under_prefix(prefix: str | None, answer: Answer) -> Submission:
    """A form's answer is the shape a browser posts; this is the only thing
    between the two, and both the hook and its fallback use it."""
    if prefix is None:
        return cast("Submission", answer)
    return {
        f"{prefix}-{name}": value
        for name, value in cast("dict[str, Any]", answer).items()
    }


def form_view_factory(
    form_class: type[forms.Form], *, template_name: str
) -> type[StepFormView]:
    form_name = form_class.__name__

    class GeneratedFormView(StepFormView):
        pass

    GeneratedFormView.form_class = form_class
    GeneratedFormView.template_name = template_name
    GeneratedFormView.__module__ = form_class.__module__
    GeneratedFormView.__name__ = f"{form_name}View"
    GeneratedFormView.__qualname__ = GeneratedFormView.__name__

    return GeneratedFormView
