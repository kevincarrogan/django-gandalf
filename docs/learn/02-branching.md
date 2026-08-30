# Chapter 2 — Branching on an answer

The fund takes applications from people and from organisations, and the two
are asked different things. The first question decides which.

```python
from gandalf.wizard import Wizard, condition


class ApplyingAsForm(forms.Form):
    applying_as = forms.ChoiceField(
        label="Are you applying as",
        choices=[("individual", "An individual"), ("organisation", "An organisation")],
    )


class AboutYouForm(forms.Form):
    occupation = forms.CharField(label="What do you do?")


class OrganisationForm(forms.Form):
    organisation_name = forms.CharField(label="Organisation name")


def is_organisation(context):
    applying_as = context.run.path.find_step(name="applying_as")
    return applying_as.form.cleaned_data["applying_as"] == "organisation"


individual_details = Wizard().step(AboutYouForm, name="about_you")
organisation_details = Wizard().step(OrganisationForm, name="organisation")


def applicant(organisation=organisation_details, individual=individual_details):
    """Who is applying: the question, then the arm the answer selects."""
    return (
        Wizard()
        .step(ApplyingAsForm, name="applying_as")
        .branch(condition(is_organisation, organisation), default=individual)
    )


class BranchingApplicationViewSet(WizardViewSet):
    url_name = "readme-branching"
    template_name = "testapp/linear_wizard.html"
    wizard = applicant().step(EmailForm, name="contact")

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        who = answers.get("organisation_name") or answers["occupation"]
        return HttpResponse(f"Application from {who} <{answers['email']}>")
```

`.branch()` forks the flow on a prior answer. Each arm is a sub-`Wizard`
(an empty `Wizard()` for "nothing extra here"); a `condition(predicate, arm)`
pairs a `predicate(context)` with the arm it selects. Selection is
first-match-wins, falling back to `default`, which may be left out.

The `context` a predicate receives is the *run context*: one object per
request that carries the request, the session-backed run and its resolved
`path`. Every callable Gandalf hands control to — predicates here, selectors
in chapter 3, expanders in chapter 4 — takes the same object, so
`context.run.path.find_step(name=...)` is how each of them reads an earlier
answer.

A predicate always runs behind a fully-validated prefix — every step before
the branch has already validated on this same walk — so it can dereference
`path.find_step(...).form.cleaned_data` without guarding for missing answers.

### Why `applicant()` is a function

The builder is immutable: every `.step()` / `.branch()` / `.expand()` returns
a *new* `Wizard`, like Django `QuerySet` chaining. So `organisation_details`
is a thing later chapters can *grow* — chapter 3 adds a switch to it, chapter
4 an expansion — and hand back into `applicant()` without chapter 2's own
wizard changing underneath them. Every chapter from here on is
`applicant(organisation=...)` plus whatever the chapter is about.

That is what composable means here: arms are wizards, so a subflow defined
once drops into several branches, and a wizard is a value you can pass
around.

A de-selected arm's answers are not thrown away either — see
[dormant memory](06-the-summary.md#dormant-memory) in chapter 6.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/branching/ &nbsp;·&nbsp; **Source:** [`ch02_branching.py`](../../tests/testapp/readme/ch02_branching.py) &nbsp;·&nbsp; **Reference:** [`Wizard.branch()`](../reference/wizard.md)

---

[← Chapter 1 — Steps and completion](01-steps-and-completion.md) · [Learn](README.md) · [Chapter 3 — Switching on a choice →](03-switching.md)
