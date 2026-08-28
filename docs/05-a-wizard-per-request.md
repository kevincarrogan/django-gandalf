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
plan, permissions, locale, feature flags; when it depends on a prior *answer*,
reach for `.expand()` as chapter 4 did.

### Mount prefixes that capture kwargs

The mount prefix can capture kwargs of its own. Inside the wizard you never
pass them by hand: `get_url_kwargs()` takes whatever the request captured,
drops the wizard's own `run_id` and `gandalf_step`, and forwards the rest
into every reverse — so a run started at `/readme/funds/arts/` stays under
`/readme/funds/arts/` for the whole walk, and `self.kwargs["fund"]` is there
on each request of the run. From outside, reverse with the kwargs:

```python
reverse("readme-fund", kwargs={"fund": "arts"})     # "/readme/funds/arts/"
```

### The URL hooks

`WizardViewSet.urls()` publishes every URL a wizard needs, all derived from
`url_name` — which is therefore required, and `urls()` raises
`ImproperlyConfigured` without it. Three hooks build the wizard's own URLs;
each forwards `get_url_kwargs()`, so an override that keeps that call keeps
mount-prefix support:

| Hook | Reverses | Called for |
| --- | --- | --- |
| `get_start_url()` | `<url_name>` | a run that cannot be continued — unknown, obliterated, or already completed (see `run_unavailable()`, chapter 9) |
| `get_wizard_url(run_id)` | `<url_name>-run` | the redirect after a fresh run is created, and when a walk has no step left to land on |
| `get_step_url(run_id, segment)` | `<url_name>-step` | every step-to-step redirect |

`get_start_url()` is an instance method that reads `self.kwargs` off a live
request, so it only exists inside a viewset handling one. From anywhere else,
reverse the name.

**Namespaces.** The names `urls()` publishes are global, and the hooks reverse
them unprefixed. Mounting under a namespace therefore breaks the wizard's own
redirects — the first one raises `NoReverseMatch` — unless you override all
three hooks to reverse `"checkout:readme-fund"` and friends. If all you wanted
was to avoid a name clash, prefixing `url_name` itself is less work and needs
no overrides.

**Custom step segments.** The step segment comes from `StepNameRouter`, which
reads each step's `name` context and reverses it back into a slug. Subclass
it to key off different context (`context_key = "slug"`) and pass it as
`.configure(step_router_class=...)`. Every step must be reversible and every
segment unique; both are checked when the wizard is resolved, across the whole
declared tree rather than just the steps this walk happens to reach, and a
step with no routable name raises `ImproperlyConfigured` rather than quietly
serving an unreachable step. For a scheme the router cannot express, skip
`urls()`, write the patterns yourself, and override the three hooks.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/funds/sport/ or
> [/arts/](http://127.0.0.1:8000/readme/funds/arts/) &nbsp;·&nbsp; **Source:** [`ch05_funds.py`](../tests/testapp/readme/ch05_funds.py)

---

[← Chapter 4 — Expanding from an answer](04-expanding.md) · [README](../README.md) · [Chapter 6 — The summary: check your answers →](06-the-summary.md)
