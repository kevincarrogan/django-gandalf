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

### Three real wizards, ported

Snippets prove a mapping is legible. They do not prove it survives contact
with a wizard someone ships. These three are ported whole from projects that
do, and driven end to end by `tests/functional/test_from_formtools.py`:

| Wizard | Upstream | What the port turns on |
| --- | --- | --- |
| [organise an event](../../tests/testapp/from_formtools/djangogirls.py) | Django Girls, `organize/views.py` | a three-entry `condition_dict` becomes two `.branch()` nodes |
| [request a service](../../tests/testapp/from_formtools/squest.py) | Squest, `service_catalog/views/catalog_views.py` | a later form built from an earlier answer |
| [two-factor setup](../../tests/testapp/from_formtools/two_factor.py) | django-two-factor-auth, `two_factor/views/core.py` | a shape decided per request, and a check that consumes what it checks |

Each module's docstring says what stops being the application's problem.
Three things are worth knowing before you start a port of your own.

**A `condition_dict` cannot express a fork.** It says whether a step is *in*,
so a two-way choice is written as two predicates that must stay opposites —
Django Girls has `skip_workshop_if_remote` and
`skip_workshop_remote_if_in_person`, and nothing checks they agree. One
`.branch()` with two arms cannot show both or neither. A condition that
really is a skip stays one, as `.branch(..., default=None)`.

**Reading an earlier answer stops being a storage detail.** Squest's second
form needs the first step's answers, and `get_form_kwargs()` runs before
there is a validated answer to read, so it indexes the raw session:
`self.storage.data['step_data']['0']['0-quota_scope'][0]` — position, prefix
and a list-of-one, all load-bearing. A step view is dispatched behind a
validated prefix, so it is `find_step(name=...).form.cleaned_data`.

**A check that consumes what it checks needs a
[proof](../reference/proofs.md).** Re-proving every answer on every request
assumes validating twice gives the same answer twice. A one-time password
breaks that, which is why django-two-factor-auth carries an
`IdempotentSessionWizardView` at all. `run.proof()` is the seam.

Two rough edges the ports met, both worth knowing:

- **Formsets work, and `MergeCleanedData` does not follow them.** `.step()`
  takes a `FormView`, and `FormView` builds a formset the way it builds a
  form, so Django Girls' organisers step needed nothing special. Reducing
  that path afterwards raises `TypeError: 'list' object is not a mapping` —
  a formset answers with a list. Gather per step in `done()` instead.
- **A `ModelForm` is not a `forms.Form`.** `.step()` tests
  `issubclass(declaration, forms.Form)`, and a `ModelForm` subclasses
  `BaseForm`. Wrap it in a [`StepFormView`](../reference/step-views.md);
  most real wizards are ModelForm-based, so expect to write one per step.

---

[← Chapter 16 — Outline, observers and the driver](16-outline-observers-and-the-driver.md) · [Learn](README.md) · **Reference:** [Wizard](../reference/wizard.md)
