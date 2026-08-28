# Chapter 7 — Step views and escapes

Two things a plain `Form` cannot do. An organisation's website can be
guessed from its email domain, so the website step wants a pre-filled
initial value. And an email address that already has an account should send
the applicant to log in, not to the next step.

### Bringing your own `FormView`

Pass a plain `Form` and Gandalf generates the step's view. Bring your own when
the step needs view-level behaviour — a per-step template, `get_initial()`,
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

Start from `StepFormView`. It is a plain Django `FormView` with the one piece
of wizard boilerplate already written — the success URL, which Gandalf never
follows because it reads only the *status code* of a step's response. You
still supply `template_name`: a step with its own view does not inherit the
viewset's. Mixing the two styles is the normal case: `website` brings its
own view, and the rest stay plain `Form`s.

The step runs on a wizard-shaped request, so `self.request.wizard` is the
same run the rest of the flow sees — `path` for the resolved route,
`path.find_step(name=...)` to address a prior answer. What a step view sees
is the prefix before it: the answers already validated on this request,
never its own answer and nothing after it. A step is replayed on every later
request, so its reads run again each time; keep them cheap.

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

All three escapes take the same arguments as `django.shortcuts.redirect`;
which one you raise decides what the user comes back to:

| Exception | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded | the same step, unanswered |
| `Advance` | stored | the next step |
| `Obliterate` | destroyed with the run | a fresh run |

> ▶ **Try it live:** http://127.0.0.1:8000/readme/step-view/ (answer
> `existing@example.com` to be parked) &nbsp;·&nbsp; **Source:** [`ch07_step_views.py`](../../tests/testapp/readme/ch07_step_views.py) &nbsp;·&nbsp; **Reference:** [Step views](../reference/step-views.md), [Escapes](../reference/escapes.md)

---

[← Chapter 6 — The summary: check your answers](06-the-summary.md) · [Learn](README.md) · [Chapter 8 — File uploads →](08-file-uploads.md)
