# Coming from `django-formtools`

Gandalf neither forks nor depends on `django-formtools` — the storage shape,
the URL model, and the re-proving walk all differ, so there is no drop-in
replacement. What maps cleanly is the *declaration*: a `form_list` becomes
chained `.step(...)` calls, and a `condition_dict` becomes
`.branch(condition(predicate, subflow))`. The predicates are the same idea —
a callable that decides — but a Gandalf predicate is handed a `WizardContext`
and runs behind a fully-validated prefix, so it reads prior answers with
`path.find_step(...).form.cleaned_data` unconditionally.

The template changes too: there is no `{{ wizard.management_form }}`. A
formtools wizard carries its position in the POST body; Gandalf keeps the
run in the session and works out its position by replaying the answers, so
a step template is a plain Django form.

### Linear wizard

```python
# formtools
class ApplicationWizard(SessionWizardView):
    form_list = [ApplicantForm, EmailForm, ConfirmForm]

# gandalf
application = (
    Wizard()
    .step(ApplicantForm, name="applicant")
    .step(EmailForm, name="contact")
    .step(ConfirmForm, name="confirm")
)
```

### Conditional step inclusion

```python
# formtools — a condition_dict keyed by step name
def is_organisation(wizard):
    cleaned = wizard.get_cleaned_data_for_step("applying_as") or {}
    return cleaned.get("applying_as") == "organisation"

class ApplicationWizard(SessionWizardView):
    form_list = [("applying_as", ApplyingAsForm), ("organisation", OrganisationForm), ("contact", EmailForm)]
    condition_dict = {"organisation": is_organisation}

# gandalf — the condition lives next to the step it guards
def is_organisation(context):
    applying_as = context.run.path.find_step(name="applying-as")
    return applying_as.form.cleaned_data["applying_as"] == "organisation"

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying-as")
    .branch(
        condition(is_organisation, Wizard().step(OrganisationForm, name="organisation")),
        default=None,  # skip it when the condition is false
    )
    .step(EmailForm, name="contact")
)
```

### Tree-like branching with reusable subflows

```python
# formtools — branching lives in imperative get_next_step() logic
class ApplicationWizard(SessionWizardView):
    form_list = [ApplyingAsForm, OrganisationForm, OrganisationTypeForm, AboutYouForm, EmailForm]

    def get_next_step(self, step=None):
        ...  # custom, dynamic next-step logic

# gandalf — the shape is the declaration
organisation_details = Wizard().step(OrganisationForm, name="organisation").step(OrganisationTypeForm, name="organisation-type")
individual_details = Wizard().step(AboutYouForm, name="about-you")

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying-as")
    .branch(condition(is_organisation, organisation_details), default=individual_details)
    .step(EmailForm, name="contact")
)
```

The payoff for tree-shaped journeys: branch condition and target stay
together, arms are reusable sub-wizards, and the whole flow is visible in one
declaration instead of growing bespoke navigation plumbing as branches
multiply.

---

[← Chapter 16 — Outline, observers and the driver](16-outline-observers-and-the-driver.md) · [Learn](README.md) · **Reference:** [Wizard](../reference/wizard.md)
