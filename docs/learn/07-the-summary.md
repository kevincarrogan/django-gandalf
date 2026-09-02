# Chapter 7 — The summary: check your answers

Before an application goes anywhere, the applicant should see what they said
and be able to change it. This chapter adds an address and a review step.

### Editing is a link

Because every step has its own URL, an "edit" affordance is just a link. GET
a completed step's URL to render it pre-filled; POST the changed answer back
to it to place it there. Editing is not a separate operation — putting an
answer at a step works the same whether or not it already had one.

The promise is that changing an answer costs the user only as much of the
wizard as the change actually invalidates — usually nothing. A trivial edit
lands straight back on the summary; an edit that flips a branch parks only at
the steps that now need attention, then fast-forwards through every
still-valid answer.

For an explicit in-page back link, any step template can reach
`request.run.back_url` (the previous step's URL, branch-aware; `None` on
the first step) and `request.run.run_url` (a "return to where I was"
link):

```django
{% if request.run.back_url %}
  <a href="{{ request.run.back_url }}">Back</a>
{% endif %}
```

### The summary page

A "check your answers" step asks the same three questions of every answer —
what is it called, what does it say, and where do I go to change it — so
`SummaryMixin` answers them once. Mix it into the step's view — a
`StepFormView`, as in chapter 6 — and the template gets a `summary` list: a
flat list of rows, one per answer, each a label, a value and somewhere to go
and change it.

```python
from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin


class ConfirmForm(forms.Form):
    """No fields at all. The button *is* the confirmation."""


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


def with_contact_and_review(wizard):
    """The tail every chapter from here shares."""
    return (
        wizard.step(EmailForm, name="contact", label="Email")
        .step(AddressStepView, name="address", label="Address")
        .step(ReviewStepView, name="review")
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
      <span>{{ row.value }}</span>
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
submission.

The rows are the answers on the run's resolved route, in walk order — never
the step doing the summarising, and never an answer left behind in a dormant
arm. A step that asked three questions reads as three rows, all linking back
to the page that asked them. Each row is named by the field that asked it, so
the label on the page is the label on the form. Values are display text, not
stored data: a choice shows its label, a boolean shows Yes/No, an upload
shows its filename.

A step's own `label` keyword — `.step(Form, name="contact", label="How to
reach you")`, else its name made readable — names a row that no single field
made, which is the next section. `name` and `label` are the two keywords the
Learn track uses; any keyword given to `.step()` is kept on the step, and the
[reference](../reference/wizard.md#wizardstepform_class_or_form_view_class--context)
lists which ones mean something.

### An address is an address

One field per answer suits most steps and not all of them: an address is five
answers and one line, and the token that looked it up is an answer the
applicant never gave.

The step is what knows that, so the step is where it is said — on its view,
the same seam chapter 6 used for everything else a step decides:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Answer, Hide


class AddressStepView(StepFormView):
    form_class = AddressForm
    template_name = "testapp/linear_wizard.html"
    summary_rows = [
        Answer("line_1", "line_2", "town", "postcode"),
        Hide("lookup_token"),
    ]
```

Not on `AddressForm` itself, tempting as that looks. A form is a Django
object shared with everything else that asks it, and a form does not render
the page it would be describing.

`Answer` reads several fields as one row, and `Hide` keeps an answer off the
page. That row is named by the step — "Address" — because no one field asked
it. Note where they are *not*:
`ReviewStepView` says nothing about the address, and never will. An address
reads as an address wherever it is asked, so every review page in this
application gets it right without knowing a thing about it —
[chapter 12](12-task-lists.md) reuses that very view for a section with no
address in it at all.

A page that wants one step read differently — a step from someone else's
library, say — says so in its own `summary_overrides`, keyed by step name,
and wins. The
[reference](../reference/summary.md#where-shaping-is-declared) has both
places and the order they resolve in.

An answer can bring its own markup too: `Answer("line_1", "line_2", "town",
"postcode", template_name="grants/summary/address.html")` names the template
that row's value renders through, Gandalf renders it, and `{{ row.value }}`
prints what came back. The review template gains nothing to decide — no
`{% if %}` learning the name of every step whose answer does not read as one
line. The partial is handed `row`, so it can render the pieces as lines
(`row.parts`) or reach past them to the whole validated form
(`row.form.cleaned_data`) for a value the form derived rather than asked.

Naming no fields means *the rest of the step*: `Answer(template_name="…")` is
how a step whose answer is not a list of fields at all — a formset's rows,
say — says how it reads, without listing a field for the template to ignore.

When the step's own name is not the answer's, `Question` gives the row one:

```python
summary_rows = [
    Question("Date of birth", Answer(template_name="grants/summary/dob.html")),
    Question("Address", Answer("line_1", "line_2", "town", "postcode")),
    Hide("lookup_token"),
]
```

It wraps one spec and names the row it builds. Everything about what the row
*says* stays with the spec inside it.

Every decision — which steps get a row, how a row is labelled, how a value
reads — is a hook on the mixin. They are listed in the
[Summary reference](../reference/summary.md).

### Dormant memory

Editing an answer that flips a branch does not discard the arm you leave.
Pick *organisation*, name it, then change your mind to *individual*: the
organisation arm is now inactive, but its answer is not gone. Flip back and
the name is already there — the run fast-forwards past it instead of asking
again. A de-selected arm's answers are kept as **dormant memory**,
re-validated and restored if you flip back, so the user never re-types an
answer they already gave.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/review/ (pick organisation,
> name it, then change the first answer to individual and back) &nbsp;·&nbsp; **Source:** [`ch07_review.py`](../../tests/testapp/readme/ch07_review.py)

---

[← Chapter 6 — Step views](06-step-views.md) · [Learn](README.md) · [Chapter 8 — Escapes →](08-escapes.md)
