# Chapter 7 — A step with a view of its own

Two things a plain `Form` cannot do. An organisation's website can be
guessed from its email domain, so the website step wants a pre-filled
initial value. And an email address that already has an account should send
the applicant to log in, not to the next step.

### Bringing your own `FormView`

Pass a plain `Form` and Gandalf generates the step's view. Bring your own when
the step needs view-level behavior — a per-step template, `get_initial()`,
`get_form_kwargs()`, a custom `form_valid()`:

```python
from gandalf.form_views import StepFormView


class WebsiteStepView(StepFormView):
    form_class = WebsiteForm
    template_name = "testapp/other_linear_wizard.html"

    def get_initial(self):
        initial = super().get_initial()
        contact = self.request.wizard.path.find_step(name="contact")
        domain = contact.form.cleaned_data["email"].partition("@")[2]
        initial["website"] = f"https://{domain}"
        return initial


def with_contact_and_review(wizard):
    return (
        wizard.step(EmailLookupForm, name="contact", label="Email")
        .step(WebsiteStepView, name="website", label="Website")
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )
```

Start from **`StepFormView`**. It is a plain Django `FormView` with the one
piece of wizard boilerplate already written: the success URL. Gandalf reads
only the *status code* of a step's response — a 3xx means "this answer
stands, carry on" — and then discards the response, so the URL is never
followed, and every step view would otherwise redirect to `self.request.path`
to say nothing. The views Gandalf generates are built on the same class.

You still supply **`template_name`**: a step with its own view does *not*
inherit the viewset's `template_name` — that default only reaches the views
Gandalf generates — and without one, rendering raises `ImproperlyConfigured`.
Mixing the two styles is the normal case: `website` brings its own view, and
the rest stay plain `Form`s. Because the view keeps its own configuration,
the same class can also be mounted as an ordinary standalone view outside the
wizard — one place for the form's behavior across "create in wizard" and
"edit later" screens; give the standalone subclass a real `get_success_url()`.

### Reading run state from a step view

The step runs on a wizard-shaped request, so `self.request.wizard` is the same
`BoundWizard` the rest of the flow sees — `path` for the resolved route,
`path.find_step(name=...)` to address a prior answer. That works from
anywhere in the view: `get_initial()`, `get_form_kwargs()`,
`get_context_data()`, `form_valid()`.

**What a step view sees is the prefix before it** — the answers the walk has
already validated on this request, never the step's own answer and nothing
after it. That is the same contract a branch predicate gets, and it holds
whether the step is being rendered or replayed behind the cursor. A step is
replayed on every later request, so its reads run again each time; keep them
cheap. `find_step()` returns `None` for a step the run cannot see, so guard
the lookup when the step you want is not unconditionally upstream — the
example does not, because `contact` always precedes `website`.

Gandalf ships type annotations (`py.typed`), and `StepFormView` declares its
`request` as a `WizardRequest` — an `HttpRequest` carrying `wizard` — so
`self.request.wizard` type-checks with no cast. Branch predicates and
`.expand()` builders are handed a `WizardContext`; annotate them with that to
reach `context.run`.

### Escaping the wizard

Sometimes an answer means the user should not be in the wizard any more. A
step says so by raising an escape, an ordinary exception in the spirit of
`Http404`:

```python
from gandalf.escapes import Park


class EmailLookupForm(forms.Form):
    email = forms.EmailField(label="Email address")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("email") == "existing@example.com":
            raise Park(reverse("readme-login"))
        return cleaned_data
```

All three escapes take the same arguments as `django.shortcuts.redirect` (a
URL, a named route, or a model with `get_absolute_url()`); which one you
raise decides what the user comes back to:

| Exception | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded, with any files it uploaded | the same step, unanswered |
| `Advance` | stored, and satisfies the step | the next step |
| `Obliterate` | destroyed with the rest of the run | a fresh run |

Escapes can also be raised from a `FormView`'s `form_valid()` when the
decision needs the view. `Escape` is the base class, so `except Escape`
catches all three.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/step-view/ (answer
> `existing@example.com` to be parked) &nbsp;·&nbsp; **Source:** [`ch07_step_views.py`](../tests/testapp/readme/ch07_step_views.py)

---

[← Chapter 6 — Check your answers](06-check-your-answers.md) · [README](../README.md) · [Chapter 8 — Proof it exists →](08-proof-it-exists.md)
