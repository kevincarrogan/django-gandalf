# Chapter 6 — The summary: check your answers

Before an application goes anywhere, the applicant should see what they said
and be able to change it. This chapter adds an address and a review step.

### Editing is a link

Because every step has its own URL, an "edit" affordance is just a link. GET a
completed step's URL to render it pre-filled; POST the changed answer back to
it to place it there. Editing is not a separate operation — putting an answer
at a step works the same whether or not it already had one.

The promise is that changing an answer costs the user only as much of the
wizard as the change actually invalidates — usually nothing. A trivial edit
lands straight back on the summary; an edit that flips a branch parks only at
the steps that now need attention, then fast-forwards through every
still-valid answer. Nothing downstream is lost to a typo, because an invalid
edit is kept and re-rendered with its errors while the sealed tail is carried
verbatim.

For an explicit in-page back link, any step template can reach
`request.wizard.back_url` (the previous step's URL, branch-aware; `None` on
the first step) and `request.wizard.run_url` (a "return to where I was" link):

```django
{% if request.wizard.back_url %}
  <a href="{{ request.wizard.back_url }}">Back</a>
{% endif %}
```

### The summary page

> **Optional module.** `gandalf.summary` reads a run's answers back for
> display; nothing in the core depends on it.

A "check your answers" step asks the same three questions of every answer —
what is it called, what does it say, and where do I go to change it — so
`SummaryMixin` answers them once. Mix it into the step's `FormView` and the
template gets a `summary` list, one row per answered step:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Group, Hide, SummaryMixin


class ConfirmForm(forms.Form):
    """No fields at all. The button *is* the confirmation."""


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


class AddressReviewStepView(ReviewStepView):
    summary_fields = {
        "address": [
            Group("line_1", "line_2", "town", "postcode"),
            Hide("lookup_token"),
        ],
    }


def with_contact_and_review(wizard):
    """The tail every chapter from here shares."""
    return (
        wizard.step(EmailForm, name="contact", label="Email")
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class ReviewedApplicationViewSet(WizardViewSet):
    url_name = "readme-review"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact_and_review(
        ch02.applicant(organisation=ch04.organisation_details)
    )
```

```django
<h1>Check your answers</h1>
<dl>
  {% for row in summary %}
    <dt>{{ row.label }}</dt>
    <dd>
      {% for field in row.fields %}
        <span>{% if field.label %}{{ field.label }}: {% endif %}{{ field.value }}</span>
      {% endfor %}
      <a href="{{ row.url }}">Change {{ row.label }}</a>
    </dd>
  {% endfor %}
</dl>
<form method="post">
  {% csrf_token %}
  <button type="submit">Confirm and continue</button>
</form>
```

`ConfirmForm` has no fields — a required checkbox beside a Confirm button
asks the same question twice while giving the user a way to get it wrong.
Gandalf reads a submission, not a field: an empty submission is still a
submission, and only a missing entry (`{"step": null}`) is a hole.

The rows come from `request.wizard.path`, so they are the answers on the
run's resolved route, in walk order, with the selected arm inlined — never the
step doing the summarising, and never an answer left behind in a dormant arm.
Each row carries `label` (the step's `label` context, else its name made
readable), `fields`, `url`, `name`, the `step` it came from, and its `form`;
each field carries `label`, `value`, `parts`, `name`, and the `bound_field`
the value came from.

**Values are display text, not stored data.** A choice shows its label — the
first row reads *An individual*, not `individual` — a boolean shows Yes/No,
dates take the active locale's format, an upload shows its filename, and an
unanswered optional field is blank rather than "None".

### Shaping a row

One field per answer suits most steps and not all of them: an address is five
answers and one line. `summary_fields`, keyed by step name, says so — `Group`
shows several of a step's fields as one answer, `Hide` shows none of them.
Fields no spec names keep a line of their own. A group takes the place of the
first of its fields, so the row still reads in form order, and empty answers
drop out, so a blank second line does not leave `", ,"` in the middle. A
group's `label=` is optional because a step whose every field is grouped is
already named by its row; `field.parts` is what `field.value` was joined
from, for a template that wants an address as lines.

A key naming a step the wizard does not declare raises `ImproperlyConfigured`,
because a renamed step would otherwise take its shaping with it — which is
why the address spec lives on `AddressReviewStepView` and the plain
`ReviewStepView` is what chapters without an address use. The check is
against what the wizard *declares*, so a key naming a step on the arm not
taken is fine.

### Every decision is a hook

Override on the view, deferring to `super()` for the cases you do not
special-case:

| Hook | Decides |
| --- | --- |
| `get_summary_steps()` | which steps get a row (default: every answered step) |
| `get_summary_label(step)` | a row's heading |
| `get_field_specs(step)` | a step's `Group` / `Hide` specs (default: `summary_fields` by step name) |
| `include_summary_field(step, bound_field)` | whether a field earns a line |
| `format_value(bound_field, value)` | how one answer reads |
| `summary_context_name` | the context variable's name (default `summary`) |

**One form per row.** Reading a step's answers means reconstructing its form
(see [Appendix C](appendix-c-what-replaying-costs.md)), so a page that reached
for `step.form` per field would pay a validation per field. The mixin builds
each row from a single form, and `RuntimeStep.form` is itself built once per
step per request.

### Dormant memory

Editing an answer that flips a branch does not discard the arm you leave. Pick
*organisation*, name it, then change your mind to *individual*: the
organisation arm is now inactive, but its answer is not gone. Flip back and
the name is already there — the run fast-forwards past it instead of asking
again. A de-selected arm's answers are kept as **dormant memory**,
re-validated and restored if you flip back, so the user never re-types an
answer they already gave.

Dormant arms live in the session until the run completes, and arm identity is
positional (declaration order) — so a `get_wizard()` that reorders branch arms
between requests would misattribute the memory, the same positional-alignment
rule that applies to steps.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/review/ (pick organisation,
> name it, then change the first answer to individual and back) &nbsp;·&nbsp; **Source:** [`ch06_review.py`](../tests/testapp/readme/ch06_review.py)

---

[← Chapter 5 — A wizard per request](05-a-wizard-per-request.md) · [README](../README.md) · [Chapter 7 — Step views and escapes →](07-step-views-and-escapes.md)
