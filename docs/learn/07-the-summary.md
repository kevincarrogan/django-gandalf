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
`request.wizard.back_url` (the previous step's URL, branch-aware; `None` on
the first step) and `request.wizard.run_url` (a "return to where I was"
link):

```django
{% if request.wizard.back_url %}
  <a href="{{ request.wizard.back_url }}">Back</a>
{% endif %}
```

### The summary page

A "check your answers" step asks the same three questions of every answer —
what is it called, what does it say, and where do I go to change it — so
`SummaryMixin` answers them once. Mix it into the step's view — a
`StepFormView`, as in chapter 6 — and the
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
submission.

The rows are the answers on the run's resolved route, in walk order — never
the step doing the summarising, and never an answer left behind in a dormant
arm. A row's `label` is the step's `label` keyword — `.step(Form,
name="contact", label="How to reach you")` — else its name made readable.
`name` and `label` are the two keywords the Learn track uses; any keyword
given to `.step()` is kept on the step, and the
[reference](../reference/wizard.md#wizardstepform_class_or_form_view_class-context)
lists which ones mean something. Values are display text, not stored data: a choice shows its
label, a boolean shows Yes/No, an upload shows its filename.

One field per answer suits most steps and not all of them: an address is five
answers and one line. `summary_fields`, keyed by step name, says so — `Group`
shows several fields as one answer, `Hide` shows none of them. A key naming a
step the wizard does not declare raises `ImproperlyConfigured`, which is why
the address spec lives on `AddressReviewStepView` and the plain
`ReviewStepView` is what chapters without an address use.

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
