# Chapter 5 — A wizard per request

The fund runs two programmes, arts and sport, and each has its own
application link: `/readme/funds/arts/` and `/readme/funds/sport/`. The
forms are the same except that the arts programme also asks for a link to
your work.

So far, every fork in the flow has turned on an *answer*: whether they are
an organisation, which kind. This one is different. The applicant is never
asked which programme they are applying to — the link they clicked already
said. That is a fact about the request, not about the run, so a branch
cannot see it; a predicate reads answers. Instead the viewset builds a
different wizard for each request, in `get_wizard()`:

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
`self.kwargs["fund"]`; the section below says how that stays put for the
whole run.

The rule of thumb: when the shape depends on the *request* — which URL,
which tenant, which plan, who is logged in, a feature flag — build it in
`get_wizard()`. When it depends on an *answer*, it belongs in the
declaration: `.branch()`, `.switch()` or `.expand()`.

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
