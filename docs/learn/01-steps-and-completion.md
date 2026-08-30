# Chapter 1 — Steps and completion

The shortest application asks who is applying and how to reach them, and does
something once when both are answered.

Four words carry the whole library, so here they are before the code. A
**wizard** is a sequence of Django forms answered in order; each form is a
**step**. One user's pass through a wizard — their answers so far, kept in the
session — is a **run**. And a **walk** is what Gandalf does on every request:
replay the run's stored answers through their forms to find out where it is.

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

    def done(self, run):
        answers = MergeCleanedData().reduce(run.path)
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

The step template is a plain Django form, with no wizard-specific markup,
because the run lives in the session rather than in the POST body:

```django
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Continue</button>
</form>
```

That is the whole thing: two forms, a viewset — the Django view that
publishes a wizard's URLs and serves them — and one URL include.

### Linking to it

`urls()` publishes three URL names derived from `url_name`. The one you link
to is the start URL, whose name is `url_name` verbatim:

```django
<a href="{% url 'readme-first' %}">Apply</a>
```

The other two — one for the run and one for a step within it — are the
wizard's own business; it redirects between them as the user answers. (All three, and the hooks that
build them, are in the [`WizardViewSet` reference](../reference/viewsets.md#wizardviewseturls-classmethod).)

### What is going on underneath

Three ideas carry the rest of the library.

**Every step is named, and every step gets its own URL.** `name` is the one
keyword `.step()` requires, and the step's URL is built from it. A step URL
is a *claim*: it either renders that step or redirects to wherever the run
actually is, so a stale link can never land an answer on the wrong step.

**A run re-proves itself on every request.** Gandalf stores raw submissions,
not "how far you got". The walk replays the stored answers through their
forms up to the first missing or no-longer-valid one, and that is where the
run is. Which step is current, which branch was taken (chapter 2), editing an
earlier answer (chapter 7) and completion all fall out of that single walk,
so stale state is impossible. (What a walk costs is in
[Walk costs](../reference/walk-costs.md).)

**`done()` receives the run, not a list of forms.** `run.path` is
what the walk found — the answered steps in order, each exposing its
`form.cleaned_data`; `MergeCleanedData().reduce(path)` folds them into one
dict; `path.find_step(name=...)` looks one up. The full surface is in the
[Run reference](../reference/run.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/first/ &nbsp;·&nbsp; **Source:** [`ch01_first_wizard.py`](../../tests/testapp/readme/ch01_first_wizard.py)

---

[← Learn](README.md) · [Chapter 2 — Branching on an answer →](02-branching.md)
