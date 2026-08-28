# Chapter 1 — A first wizard

The shortest application asks who is applying and how to reach them, and does
something once when both are answered.

```python
from django import forms
from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard


class ApplicantForm(forms.Form):
    full_name = forms.CharField(label="Your full name")


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email address")


class FirstApplicationViewSet(WizardViewSet):
    url_name = "readme-first"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
    )

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"Application received from {answers['full_name']} <{answers['email']}>"
        )
```

Mount it with a single `include`:

```python
urlpatterns = [
    path("readme/first/", include(FirstApplicationViewSet.urls())),
]
```

The step template is a plain Django form — no management form, no
wizard-specific markup, because Gandalf keeps position in the session rather
than in the POST body:

```django
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Continue</button>
</form>
```

That is the whole thing: two forms, a viewset, one URL include.

### Linking to it

`urls()` derives three URL names from `url_name`, so getting a user into the
wizard is ordinary Django reversing:

| URL name | Pattern | What it is |
| --- | --- | --- |
| `readme-first` | `readme/first/` | **the start URL** — begins a fresh run |
| `readme-first-run` | `readme/first/<run_id>/` | a run — redirects to wherever it has got to |
| `readme-first-step` | `readme/first/<run_id>/contact/` | one step of a run |

The start URL is the one you publish, and its name is `url_name` verbatim:

```django
<a href="{% url 'readme-first' %}">Apply</a>
```

The other two are the wizard's own business — it redirects between them as the
user walks — though being reversible is what makes a run resumable from a link.

### What is going on underneath

A few ideas carry the rest of the library.

**Every step is named, and every step gets its own URL.** Keyword arguments to
`.step()` become the step's context, so `name="contact"` is an ordinary context
entry — the one the default router reads. A step URL is a *claim*: it either
renders that step or redirects to wherever the run actually is, so a stale link
can never land an answer on the wrong step.

**A run re-proves itself on every request.** Gandalf stores raw submissions,
not "how far you got". On each request it replays the stored answers through
their forms up to the first missing or no-longer-valid one — that is what
makes position, branch selection, editing, and completion all fall out of a
single walk, and what makes stale state impossible. (The cost of that replay
is [Appendix C](appendix-c-what-replaying-costs.md).)

**`done(self, bound_wizard)` receives the run, not a list of forms**, so it can
read the answers however it needs:

- `bound_wizard.path` — the resolved route: the answered steps in order,
  iterable, each a `RuntimeStep` exposing `.form.cleaned_data`, `.data` (raw
  submission), `.files`, and — for linking back to a step — `.name` and
  `.url`.
- `MergeCleanedData().reduce(bound_wizard.path)` — folds every step's
  `cleaned_data` into one dict (last-write-wins). Subclass it for a different
  merge policy.
- `bound_wizard.path.find_step(name=...)` / `path.filter_steps(...)` — look a
  step up by name or any context key. These live on `path`, so they only ever
  see steps actually on the resolved route — prior answers, never the current
  (unanswered) step or a step not yet reached.
- `bound_wizard.get_state()` / `get_run_data()` — the raw stored JSON.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/first/ &nbsp;·&nbsp; **Source:** [`ch01_first_wizard.py`](../tests/testapp/readme/ch01_first_wizard.py)

---

[← README](../README.md) · [Chapter 2 — Individuals and organisations →](02-individuals-and-organisations.md)
