from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from django import forms
from django.views.generic.edit import FormView

from gandalf.types import Answer, Submission, WizardRequest


if TYPE_CHECKING:
    # Imported for the annotation only: `gandalf.summary` is built on this
    # module, so the dependency runs one way at runtime.
    from gandalf.summary import RowSpec

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

    #: How this step's answers read on a check-your-answers page: a
    #: sequence of `gandalf.summary` specs about *this* step's fields, so
    #: there is no step name to key them by. A review page overrides what it
    #: wants said differently, in its own `summary_overrides`, and inherits
    #: the rest.
    summary_rows: Sequence[RowSpec] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Check a step view's own specs when its class body runs.

        The two things a list of specs can say wrong knowing nothing but
        itself — a field claimed twice, two specs naming no fields — need no
        run, no request and no form to decide, so waiting for someone to
        open the summary page to say so is waiting for no reason. What is
        decided per request is checked per request, in the summary page.
        """
        super().__init_subclass__(**kwargs)
        if not cls.summary_rows:
            # Nothing to contradict, and nothing to import: this runs for
            # every step view in a project, `FormSetStepView` included —
            # which is defined while `gandalf.summary` is still importing
            # this module, so reaching for it here would be circular.
            return
        # Imported inside the guard for that reason: `gandalf.summary` is
        # built on this module, so the dependency runs one way at runtime.
        from gandalf.summary import check_row_specs

        check_row_specs(cls.summary_rows, f"{cls.__name__}.summary_rows")

    def get_summary_row_specs(self) -> Sequence[RowSpec]:
        """How this step's answers read, for a summary page to start from.

        The step is the thing that knows an address is an address, and a
        review page listing every awkward step by name is a page carrying
        knowledge it did not generate.

        The view rather than the form, deliberately. A `forms.Form` is a
        Django object shared with everything else that asks it — the admin,
        a serializer, another app's view — and a Gandalf attribute on it is
        this library squatting in a namespace it does not own. It is also a
        form knowing about a page it never renders. A step view is the seam
        every other reading already comes through, and one shared between
        wizards travels exactly as well as a shared form would.

        Override to decide per request; the summary page has the last word
        either way.
        """
        return self.summary_rows

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
        convert in between.

        Two renamings stand between an answer and a submission, and a
        plain form has neither, which is why it is easy to write this as
        though there were none. A prefix renames every key the step posts.
        A widget may post under keys that are not the field's name at all,
        which is what any `MultiWidget` does — one date field, three boxes,
        and `start_date` naming none of them. Asked of the form, so that
        both are read off the object that actually names them.

        Override beside a form object whose answer is not a submission. It
        is the one direction the other four hooks do not cover: they all
        describe what a step holds, and this is how something gets *into*
        it.
        """
        return _as_submission(self.get_form(), self.get_prefix(), answer)


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
        template can say, `SummaryMixin.build_summary_rows()`. What
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
        # A row repeats a form, so a composite widget inside one is
        # renamed by the row *and* by itself. The fields come from
        # `empty_form` because a row's answer says what was filled in,
        # not what asked for it.
        row_fields = getattr(formset.empty_form, "fields", {})
        for index, row in enumerate(answer):
            for name, value in row.items():
                submission.update(
                    _widget_submission(
                        row_fields.get(name), f"{prefix}-{index}-{name}", value
                    )
                )
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
        return _as_submission(view.get_form(), view.get_prefix(), answer)
    return cast("Submission", writer(answer))


def _widget_submission(field: Any, html_name: str, value: Any) -> Submission:
    """One answered field as the POST keys that would have carried it.

    A widget owns the shape of its own POST, and Django states that in one
    direction only: `value_from_datadict()` is how a widget reads what it
    was sent, and there is no mirror of it because nothing in Django ever
    needs to *write* a POST. A wizard does — an answer read back out has to
    be submittable again — so the mirror is named here, and a widget that
    lays its keys out its own way says so with `value_to_datadict(name,
    value)`.

    A `MultiWidget` needs no such method, because Django already states its
    layout: its parts come from `decompress()`, under the suffixes in
    `widgets_names`. That covers `SplitDateTimeField` and every three-box
    date field built the ordinary way. What it cannot cover is a widget
    that invents a scheme — Django's own `SelectDateWidget` is not a
    `MultiWidget` at all and names its keys `_year`, `_month` and `_day` —
    and that is what the hook is for.

    Anything else posts one value under the field's own name, which is the
    shape that always worked and the reason the other two went unnoticed.
    """
    widget = getattr(field, "widget", None)
    writer = getattr(widget, "value_to_datadict", None)
    if writer is not None:
        return dict(writer(html_name, value))
    if isinstance(widget, forms.MultiWidget):
        # `widgets_names` and `decompress()` are a `MultiWidget`'s own public
        # layout, and have been since Django 4.0; django-stubs carries
        # neither faithfully, so the reads are cast rather than guarded.
        composite = cast("Any", widget)
        return {
            f"{html_name}{suffix}": part
            for suffix, part in zip(
                composite.widgets_names, composite.decompress(value)
            )
        }
    return {html_name: value}


def _as_submission(form: Any, prefix: str | None, answer: Answer) -> Submission:
    """A form's answer as the POST that would have produced it.

    The two renamings, in the order a browser applies them: the prefix
    names the field, and the widget names its inputs under that. A key the
    form has no field for is left under its own name — a value `clean()`
    derived is still part of the answer, and the step that put it there is
    the one that knows what to do with it.
    """
    fields = getattr(form, "fields", {})
    submission: Submission = {}
    for name, value in cast("dict[str, Any]", answer).items():
        html_name = name if prefix is None else f"{prefix}-{name}"
        submission.update(_widget_submission(fields.get(name), html_name, value))
    return submission


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
