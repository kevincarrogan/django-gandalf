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

What if the count changes? Say the applicant answers three, names three
trustees, then goes back to the count (every step has a URL, so they can)
and says two. The builder runs again and grows two steps. Gandalf keeps the
grown answers in order under the expansion — first, second, third — not by
name, so the first two trustees are still there and the third is dropped.
Say four instead and all three survive, with one more to ask. Nothing
already answered is asked again.

That is also the limit of `.expand()`. The only thing the applicant can
change is *how many*: there is no way to say "remove the second trustee",
because with answers kept in order, taking one out of the middle would slide
every later answer up a place and put the wrong name against the wrong
trustee. A list the user grows and prunes over time — budget lines, in
[chapter 13](13-add-another.md) — needs each item to be its own run, and
that is a different tool.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/expand/ &nbsp;·&nbsp; **Source:** [`ch04_expand.py`](../../tests/testapp/readme/ch04_expand.py) &nbsp;·&nbsp; **Reference:** [`Wizard.expand()`](../reference/wizard.md)

---

[← Chapter 3 — Switching on a choice](03-switching.md) · [Learn](README.md) · [Chapter 5 — A wizard per request →](05-a-wizard-per-request.md)
