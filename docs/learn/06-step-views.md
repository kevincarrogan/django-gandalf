# Chapter 6 — Step views: bring your own `FormView`

So far every step has been a `Form`, and Gandalf has done the rest. That is
the right default, and most steps stay that way. But a step is more than its
form: it has a template, initial values, the arguments its form is built
with, and what happens when the form is valid. In Django all of that lives
on a `FormView`, and a step can have one of its own.

The application asks for the organisation's website. Most of the time it
can be guessed from the email address already given — `ada@example.com`
suggests `https://example.com` — so the website step should arrive
pre-filled. That is `get_initial()`, which is a view's job, not a form's:

```python
from gandalf.form_views import StepFormView


class WebsiteForm(forms.Form):
    website = forms.URLField(label="Website", required=False)


class WebsiteStepView(StepFormView):
    form_class = WebsiteForm
    template_name = "testapp/other_linear_wizard.html"

    def get_initial(self):
        initial = super().get_initial()  # the stored answer, on a revisit
        contact = self.request.run.path.find_step(name="contact")
        if contact is not None and "website" not in initial:
            domain = contact.answer["email"].partition("@")[2]
            initial["website"] = f"https://{domain}"
        return initial


def with_contact(wizard):
    return wizard.step(EmailForm, name="contact", label="Email").step(
        WebsiteStepView, name="website", label="Website"
    )


class WebsiteApplicationViewSet(WizardViewSet):
    url_name = "readme-step-view"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact(ch02.applicant(organisation=ch04.organisation_details))

    def done(self, run):
        answers = run.answers
        return HttpResponse(
            f"Application from {answers['email']} ({answers['website']})"
        )
```

`.step()` takes either a `Form` or a `FormView`, and mixing them is the
normal case: `website` brings its own view, and every other step stays a
plain `Form`.

### There was always a view

When you pass a bare `Form`, Gandalf generates a `StepFormView` for it,
using the viewset's `template_name`. So a view you write is not a special
kind of step; it is the same kind of thing, written out. Which is why
nothing about the walk changes: a step with its own view is stored,
replayed, revisited and summarised exactly as a bare form is.

`StepFormView` is Django's `FormView` with one piece of wizard boilerplate
already written — `get_success_url()` returns the step's own URL. Gandalf
reads only the *status code* of a step's response: a redirect means the
answer stands, anything else means it does not (and on a live submission,
that response is what the user sees). You would otherwise write that same
no-op redirect in every step view. Everything else is `FormView` as you
know it.

One thing is not inherited: **`template_name`**. The viewset's template
reaches only the views Gandalf generates. A step view without one raises
`ImproperlyConfigured` on its first render.

### What the view can do

Because it is a `FormView`, the whole composition API is yours, and each
piece has a use in a wizard:

- **`get_initial()`** — pre-fill from an earlier answer, as above. Call
  `super().get_initial()` first: when a completed step is revisited for
  editing, Gandalf hands the stored answer to the view as `initial`, and an
  override that builds a fresh dict throws the user's answer away.
- **`get_form_kwargs()`** — hand the form something only the view has: the
  signed-in user (chapter 5), the organisation they belong to. The form is
  built the same way when its answer is read back later, so `cleaned_data`
  sees the same form the user did.
- **`form_valid()`** — decide whether an answer stands using the request,
  the session or `self.kwargs`. Return `super().form_valid(form)` for yes.
  For "the user should not be in the wizard at all", raise an escape —
  chapter 8.
- **`get_context_data()`** — put more than `form` in the template.
- **`form_class` is any `BaseForm`** — so a `ModelForm` step is a
  `StepFormView` with `form_class = TrusteeModelForm`. (A bare `ModelForm`
  cannot be passed to `.step()`: Gandalf recognises only `forms.Form`
  subclasses as forms.)

### What the view can see

`self.request.run` is the run, from anywhere in the view. What it shows
is the **validated prefix**: the answers before this step, already proved
on this request — never the step's own answer, and nothing after it. That
is the same contract a branch predicate has.

`path.find_step(name=...)` can therefore return `None`: a step not yet
reached, on an arm not taken, or downstream of this one. The website step
guards its lookup even though `contact` is always upstream of it, because a
step view has a life of its own — a `StepFormView` can be mounted as an
ordinary standalone view too, and there it has no run at all.

### The view runs on every request

A run re-proves itself on every request (chapter 1), and that means
re-dispatching every answered step. `WebsiteStepView.get_initial()` runs
again on every request after the website step, for as long as the run
lives — the same is true of `get_form_kwargs()`, `clean()` and
`form_valid()`. Keep them cheap and deterministic, and put anything that
must happen exactly once — creating a record, sending an email — in the
viewset's `run_started()` or `done()` (chapter 10).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/step-view/ &nbsp;·&nbsp; **Source:** [`ch06_step_views.py`](../../tests/testapp/readme/ch06_step_views.py) &nbsp;·&nbsp; **Reference:** [Step views](../reference/step-views.md)

---

[← Chapter 5 — A wizard per request](05-a-wizard-per-request.md) · [Learn](README.md) · [Chapter 7 — The summary: check your answers →](07-the-summary.md)
