# Chapter 5 — A wizard per request

The fund runs an arts programme and a sports programme, and the arts
programme wants a link to your work. That is a difference in the *request* —
which fund's URL the applicant came in through — not in any answer, so it is
`get_wizard()`, called per request, rather than a branch:

```python
class FundApplicationViewSet(WizardViewSet):
    url_name = "readme-fund"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, bound_wizard):
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

Reach for `get_wizard()` when the shape depends on the request — tenant,
plan, permissions, locale, feature flags. When it depends on a prior
*answer*, reach for `.expand()` as chapter 4 did.

### Mount prefixes that capture kwargs

The mount prefix can capture kwargs of its own, and inside the wizard you
never pass them by hand: whatever the request captured is forwarded into
every redirect, so a run started at `/readme/funds/arts/` stays under
`/readme/funds/arts/` for the whole walk, and `self.kwargs["fund"]` is there
on each request of the run. From outside, reverse with the kwargs:

```python
reverse("readme-fund", kwargs={"fund": "arts"})     # "/readme/funds/arts/"
```

Mounting under a URL namespace, changing how step segments are spelled, or
writing the patterns by hand instead of `urls()` are all possible and all
documented in the [`WizardViewSet` reference](../reference/viewsets.md#wizardviewseturls-classmethod).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/funds/sport/ or
> [/arts/](http://127.0.0.1:8000/readme/funds/arts/) &nbsp;·&nbsp; **Source:** [`ch05_funds.py`](../../tests/testapp/readme/ch05_funds.py)

---

[← Chapter 4 — Expanding from an answer](04-expanding.md) · [Learn](README.md) · [Chapter 6 — The summary: check your answers →](06-the-summary.md)
