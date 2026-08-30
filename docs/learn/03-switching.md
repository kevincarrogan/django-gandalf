# Chapter 3 — Switching on a choice

A charity has a charity number, a company has a company number, and a
community group has neither. That is not "is this true" but "which of these",
and `.switch()` says so directly:

```python
from gandalf.wizard import Wizard, on_field

from . import ch02_branching as ch02


class OrganisationTypeForm(forms.Form):
    organisation_type = forms.ChoiceField(
        label="What kind of organisation is it?",
        choices=[
            ("charity", "A registered charity"),
            ("company", "A company"),
            ("community", "An unincorporated community group"),
        ],
    )


organisation_details = (
    ch02.organisation_details.step(OrganisationTypeForm, name="organisation-type")
    .switch(
        on_field("organisation-type", "organisation_type"),
        {
            "charity": Wizard().step(CharityNumberForm, name="charity-number"),
            "company": Wizard().step(CompanyNumberForm, name="company-number"),
        },
        # A community group has no number to give, so there is no default
        # arm: the walk continues past the switch.
    )
)


class SwitchingApplicationViewSet(WizardViewSet):
    url_name = "readme-switch"
    template_name = "testapp/linear_wizard.html"
    wizard = ch02.applicant(organisation=organisation_details).step(
        EmailForm, name="contact"
    )
```

`ch02.organisation_details` is untouched — this chapter's
`organisation_details` is a new value built from it.

A selector is the same arbitrary code a predicate is, but asking *which*
rather than *whether* buys three things: exactly one case can apply, so
overlapping conditions cannot resolve by declaration order; the selector runs
once per switch however many cases there are; and each case's answers are
stored under its own name, so reordering the cases cannot strand them.

`on_field(step, field)` is the common case said declaratively — route on the
value of an earlier answer. Prefer a plain function whenever the decision is
anything more than "what did they say". A value no case names falls to
`default`, or past the switch entirely when there is none — which is what
the community group does.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/switch/ &nbsp;·&nbsp; **Source:** [`ch03_switch.py`](../../tests/testapp/readme/ch03_switch.py) &nbsp;·&nbsp; **Reference:** [`Wizard.switch()`](../reference/wizard.md)

---

[← Chapter 2 — Branching on an answer](02-branching.md) · [Learn](README.md) · [Chapter 4 — Expanding from an answer →](04-expanding.md)
