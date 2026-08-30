# Chapter 5 — A wizard per request

Some things are known at the front door, before the first question is
asked: who is signed in, which link they came in through, what the date is.
The applicant is never asked them — they are already true when the run
starts — and the shape of the wizard can depend on them all the same.

A fund officer sometimes keys in an application that arrived on paper.
Signed in as staff, they are asked one thing an applicant never is: the
date it was received.

```python
class ReceivedOnForm(forms.Form):
    received_on = forms.DateField(label="Date the paper application was received")


class PaperApplicationViewSet(WizardViewSet):
    url_name = "readme-paper"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, run):
        wizard = ch02.applicant(organisation=ch04.organisation_details)
        if self.request.user.is_staff:
            wizard = wizard.step(ReceivedOnForm, name="received-on")
        return wizard.step(EmailForm, name="contact")
```

Every fork so far — chapters 2, 3 and 4 — turned on an *answer*, and so
lived in the declaration. This one cannot: whether the person is staff is
not in any answer, so no predicate can read it. Instead the viewset builds
the wizard itself, on every request, in `get_wizard()`. The default
`get_wizard()` just returns the `wizard` attribute; overriding it is how a
viewset says "the wizard depends on who is asking".

The rule of thumb: when the shape depends on the *request* — who is signed
in, which tenant, which plan, a feature flag, even the clock — build it in
`get_wizard()`. When it depends on an *answer*, it belongs in the
declaration: `.branch()`, `.switch()` or `.expand()`.

### Mount prefixes that capture kwargs

The front door can also be a URL. The fund runs two programmes, arts and
sport, each with its own application link, and the arts programme also
wants a link to your work:

```python
class FundApplicationViewSet(WizardViewSet):
    url_name = "readme-fund"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, run):
        wizard = ch02.applicant(organisation=ch04.organisation_details)
        if self.kwargs["fund"] == "arts":
            wizard = wizard.step(PortfolioForm, name="portfolio")
        return wizard.step(EmailForm, name="contact")
```

```python
urlpatterns = [
    path("readme/funds/<slug:fund>/", include(FundApplicationViewSet.urls())),
]
```

`<slug:fund>` in the mount is what puts `"arts"` or `"sport"` in
`self.kwargs["fund"]`. The mount prefix can capture kwargs of its own, and
inside the wizard you never pass them by hand: whatever the request
captured is forwarded into every redirect, so a run started at
`/readme/funds/arts/` stays under `/readme/funds/arts/` for the whole walk,
and `self.kwargs["fund"]` is there on each request of the run. From
outside, reverse with the kwargs:

```python
reverse("readme-fund", kwargs={"fund": "arts"})     # "/readme/funds/arts/"
```

Mounting under a URL namespace, changing how step segments are spelled, or
writing the patterns by hand instead of `urls()` are all possible and all
documented in the [`WizardViewSet` reference](../reference/viewsets.md#wizardviewseturls-classmethod).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/paper/ — then
> [sign in as staff](http://127.0.0.1:8000/readme/staff/sign-in/) and start
> again; the funds are at [/funds/sport/](http://127.0.0.1:8000/readme/funds/sport/)
> and [/funds/arts/](http://127.0.0.1:8000/readme/funds/arts/) &nbsp;·&nbsp; **Source:** [`ch05_per_request.py`](../../tests/testapp/readme/ch05_per_request.py)

---

[← Chapter 4 — Expanding from an answer](04-expanding.md) · [Learn](README.md) · [Chapter 6 — Step views: bring your own `FormView` →](06-step-views.md)
