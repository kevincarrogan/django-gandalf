# Chapter 4 — Expanding from an answer

An organisation names its trustees. How many there are is not known until
the applicant says, so the *shape* of the flow is decided by an answer the
user has just given. `.expand()` grows the tree during the walk from a
builder you provide:

```python
from . import ch02_branching as ch02, ch03_switch as ch03


class TrusteeCountForm(forms.Form):
    trustees = forms.IntegerField(
        label="How many trustees or directors does it have?", min_value=1, max_value=5
    )


class TrusteeForm(forms.Form):
    name = forms.CharField(label="Trustee's name")


def build_trustee_steps(context):
    count = context.run.path.find_step(name="trustees").form.cleaned_data["trustees"]
    steps = Wizard()
    for index in range(count):
        steps = steps.step(TrusteeForm, name=f"trustee-{index}")
    return steps


organisation_details = ch03.organisation_details.step(
    TrusteeCountForm, name="trustees"
).expand(build_trustee_steps)


class ExpandingApplicationViewSet(WizardViewSet):
    url_name = "readme-expand"
    template_name = "testapp/linear_wizard.html"
    wizard = ch02.applicant(organisation=organisation_details).step(
        EmailForm, name="contact"
    )

    def done(self, run):
        trustees = [
            step.form.cleaned_data["name"]
            for step in run.path
            if step.name and step.name.startswith("trustee-")
        ]
        return HttpResponse("Trustees: " + ", ".join(trustees))
```

The builder runs mid-walk, behind the validated count, and its steps are
spliced in where `.expand()` sits — inside the organisation arm, so an
individual is never asked. Answering the count parks the user on the first
grown step in a single request.

Grown answers are stored positionally: raising a count keeps the answers
already given, lowering it drops the trailing ones. That is exactly why
`.expand()` is the wrong tool for a list the user grows and prunes over time
— deleting from the middle would shift every answer after it. Budget lines,
in [chapter 12](12-add-another.md), are that kind of list, and each is its
own run.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/expand/ &nbsp;·&nbsp; **Source:** [`ch04_expand.py`](../../tests/testapp/readme/ch04_expand.py) &nbsp;·&nbsp; **Reference:** [`Wizard.expand()`](../reference/wizard.md)

---

[← Chapter 3 — Switching on a choice](03-switching.md) · [Learn](README.md) · [Chapter 5 — A wizard per request →](05-a-wizard-per-request.md)
