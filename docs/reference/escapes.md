# Escapes

`gandalf.escapes` — exceptions a step raises to send the user out of the
wizard.

```python
from gandalf.escapes import Advance, Escape, Obliterate, Park
```

---

## Reference

### `Escape(to, *args, permanent=False, **kwargs)`

The base class. Raising it directly is an error — it names no disposition
for the run — but `except Escape` catches all three subclasses.

**Parameters**

- `to`, `*args`, `**kwargs` — handed verbatim to
  [`django.shortcuts.redirect`](https://docs.djangoproject.com/en/stable/topics/http/shortcuts/#redirect):
  a URL, a URL name with its arguments, or a model with `get_absolute_url()`.
- `permanent` — issue a 301 instead of a 302. Default `False`.

**Attributes** — `to`, `redirect_args`, `redirect_kwargs`, `permanent`.

**Caveats**

- An escape only redirects for the submission the user *actually made*.
  Stored answers replay on every later walk, and a replayed escape marks its
  step satisfied without redirecting — so a `clean()` that escapes must be
  deterministic for the same input, like any other validation.
- Raise it from wherever the step's submission is validated: `Form.clean()`,
  a field's `clean_<name>()`, or a `FormView.form_valid()`. The viewset
  catches it around the step's POST dispatch; nothing has been persisted at
  that point, so `Park` simply declines to write rather than undoing one.

### `Park(to, ...)`

Leave, keeping the run parked on this step. The escaping submission is
discarded, along with any files it uploaded. Coming back to the run shows
this step again, unanswered.

### `Advance(to, ...)`

Leave, keeping the run *and* this answer. The submission is stored and
satisfies the step, so returning to the run resumes at the next one.

### `Obliterate(to, ...)`

Leave, destroying the run. Stored state and uploaded files are removed.
Returning to the wizard starts a fresh run.

| | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded | the same step, unanswered |
| `Advance` | stored | the next step |
| `Obliterate` | destroyed with the run | a fresh run |

---

## Usage

### Sending an existing account to log in

```python
from django import forms
from django.urls import reverse

from gandalf.escapes import Park


class EmailLookupForm(forms.Form):
    email = forms.EmailField(label="Email address")

    def clean(self):
        cleaned_data = super().clean()
        if Account.objects.filter(email=cleaned_data.get("email")).exists():
            raise Park(reverse("login"))
        return cleaned_data
```

The user is redirected to the login page. If they come back to the run, the
email step is shown again with no answer — the lookup was a detour.

### Escaping from a step view

When the decision needs the view — the request, the session, `self.kwargs` —
raise from `form_valid()` instead:

```python
from gandalf.escapes import Advance
from gandalf.form_views import StepFormView


class ConsentStepView(StepFormView):
    form_class = ConsentForm
    template_name = "steps/consent.html"

    def form_valid(self, form):
        if form.cleaned_data["read_terms_first"]:
            raise Advance("terms")   # answer kept; back to the run lands on the next step
        return super().form_valid(form)
```

### Bailing out entirely

```python
from gandalf.escapes import Obliterate


def clean_country(self):
    country = self.cleaned_data["country"]
    if country not in SUPPORTED:
        raise Obliterate("unsupported-country")
    return country
```

The run is deleted. A link back to the wizard begins a new one.

---

## Troubleshooting

### My escape redirects the first time, but a later GET of the run does not

That is by design. Stored answers replay on every request; a replayed
`Advance` just satisfies its step, and a `Park` never stored anything to
replay. The redirect belongs to the submission, not the run.

### I raised `Escape` itself and got `ImproperlyConfigured`

`Escape` names no disposition for the run, so the viewset refuses it with
*"Raise Park, Advance or Obliterate to escape a wizard"*. Pick one of the
three.

### The escape target reverses fine outside the wizard but raises `NoReverseMatch` here

`to` is resolved with `django.shortcuts.redirect`, so a URL name that needs
kwargs must be given them: `Park("account-detail", pk=account.pk)`.

---

**Learn:** [Chapter 7 — Step views and escapes](../learn/07-step-views-and-escapes.md) · **Related:** [Step views](step-views.md), [`WizardViewSet`](viewsets.md)
