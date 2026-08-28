# django-gandalf

`django-gandalf` lets you declare **multi-step, tree-shaped Django form flows**
as readable, composable code.

You build a flow with a small, immutable builder — `.step()` to add a form,
`.branch()` to fork on an answer, `.expand()` to grow steps from an answer — and
mount it as an ordinary Django view. Gandalf handles the per-step URLs, the
session state, back-navigation, editing, file uploads, and running your
completion logic exactly once. When one wizard is not enough, it handles the
task list of wizards too: sections the user does in any order, lists they
grow, sections that unlock or appear because of what they said elsewhere, and
a submit at the end of all of it.

```python
from gandalf.wizard import Wizard, condition

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as")
    .branch(
        condition(is_organisation, Wizard().step(OrganisationForm, name="organisation")),
        default=Wizard().step(AboutYouForm, name="about_you"),
    )
    .step(EmailForm, name="contact")
)
```

The only dependency is Django. Coming from `django-formtools`? See
[Appendix D](#appendix-d-coming-from-django-formtools) for a
declaration-by-declaration mapping.

---

## Installation & setup

```bash
pip install django-gandalf   # or: uv add django-gandalf
```

Gandalf ships no models or migrations, but it does rely on a few pieces of
standard Django plumbing:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django.contrib.sessions",   # wizard state lives in the session
    "gandalf",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",  # required
    "django.middleware.csrf.CsrfViewMiddleware",
    # ...
]

TEMPLATES = [
    {
        # ...
        "OPTIONS": {
            "context_processors": [
                # required so `request.wizard` is reachable in step templates
                "django.template.context_processors.request",
            ],
        },
    }
]
```

Requires Python 3.10+ and Django 4.2+.

---

## How this README works

This README is one worked example. A community grant fund takes applications:
from individuals and from organisations, for a project with a budget, with
referees and a governing document and a final submit. Chapter 1 asks two
questions in a row. Each chapter after it adds one thing the application
needs, says why that thing exists, and leaves a runnable application behind.
By chapter 14 the whole thing is there, and chapter 15 is about knowing what
you built.

Every chapter is real code. It lives in
[`tests/testapp/readme/`](tests/testapp/readme/), one module per chapter, and
each module imports the one before it and grows it — which is itself the
first lesson, since a `Wizard` is a value and the previous chapter's
declaration is still intact after this one has built on it.
[`tests/functional/test_readme_examples.py`](tests/functional/test_readme_examples.py)
drives every chapter through the Django test client, so the snippets below
are checked in CI, not just prose.

To click through them:

```bash
just serve
```

That starts Django at **http://127.0.0.1:8000/**, whose index page lists the
chapters in order. Each chapter below ends with a **▶ Try it live** link to
its start URL. These are local URLs — they only resolve while `just serve` is
running.

The reference material — testing, configuration, what replaying costs, and
the `django-formtools` mapping — is in the appendices at the end.

---

## Chapter 1 — A first wizard

The shortest application asks who is applying and how to reach them, and does
something once when both are answered.

```python
from django import forms
from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard


class ApplicantForm(forms.Form):
    full_name = forms.CharField(label="Your full name")


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email address")


class FirstApplicationViewSet(WizardViewSet):
    url_name = "readme-first"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
    )

    def done(self, bound_wizard):
        answers = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"Application received from {answers['full_name']} <{answers['email']}>"
        )
```

Mount it with a single `include`:

```python
urlpatterns = [
    path("readme/first/", include(FirstApplicationViewSet.urls())),
]
```

The step template is a plain Django form — no management form, no
wizard-specific markup, because Gandalf keeps position in the session rather
than in the POST body:

```django
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Continue</button>
</form>
```

That is the whole thing: two forms, a viewset, one URL include.

### Linking to it

`urls()` derives three URL names from `url_name`, so getting a user into the
wizard is ordinary Django reversing:

| URL name | Pattern | What it is |
| --- | --- | --- |
| `readme-first` | `readme/first/` | **the start URL** — begins a fresh run |
| `readme-first-run` | `readme/first/<run_id>/` | a run — redirects to wherever it has got to |
| `readme-first-step` | `readme/first/<run_id>/contact/` | one step of a run |

The start URL is the one you publish, and its name is `url_name` verbatim:

```django
<a href="{% url 'readme-first' %}">Apply</a>
```

The other two are the wizard's own business — it redirects between them as the
user walks — though being reversible is what makes a run resumable from a link.

### What is going on underneath

A few ideas carry the rest of the library.

**Every step is named, and every step gets its own URL.** Keyword arguments to
`.step()` become the step's context, so `name="contact"` is an ordinary context
entry — the one the default router reads. A step URL is a *claim*: it either
renders that step or redirects to wherever the run actually is, so a stale link
can never land an answer on the wrong step.

**A run re-proves itself on every request.** Gandalf stores raw submissions,
not "how far you got". On each request it replays the stored answers through
their forms up to the first missing or no-longer-valid one — that is what
makes position, branch selection, editing, and completion all fall out of a
single walk, and what makes stale state impossible. (The cost of that replay
is [Appendix C](#appendix-c-what-replaying-costs).)

**`done(self, bound_wizard)` receives the run, not a list of forms**, so it can
read the answers however it needs:

- `bound_wizard.path` — the resolved route: the answered steps in order,
  iterable, each a `RuntimeStep` exposing `.form.cleaned_data`, `.data` (raw
  submission), `.files`, and — for linking back to a step — `.name` and
  `.url`.
- `MergeCleanedData().reduce(bound_wizard.path)` — folds every step's
  `cleaned_data` into one dict (last-write-wins). Subclass it for a different
  merge policy.
- `bound_wizard.path.find_step(name=...)` / `path.filter_steps(...)` — look a
  step up by name or any context key. These live on `path`, so they only ever
  see steps actually on the resolved route — prior answers, never the current
  (unanswered) step or a step not yet reached.
- `bound_wizard.get_state()` / `get_run_data()` — the raw stored JSON.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/first/ &nbsp;·&nbsp; **Source:** [`ch01_first_wizard.py`](tests/testapp/readme/ch01_first_wizard.py)

---

## Chapter 2 — Individuals and organisations

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

`.branch()` forks the flow on a prior answer. Each arm is a sub-`Wizard` (or
`None` for "nothing extra here"); a `condition(predicate, arm)` pairs a
`predicate(context)` with the arm it selects. Selection is **first-match-wins**,
falling back to `default`.

A predicate always runs **behind a fully-validated prefix** — every step before
the branch has already validated on this same walk — so it can dereference
`path.find_step(...).form.cleaned_data` unconditionally without guarding for
missing answers.

**Why the arms are module-level values, and why `applicant()` is a function.**
The builder is immutable: every `.step()` / `.branch()` / `.expand()` returns
a *new* `Wizard`, like Django `QuerySet` chaining — nothing mutates in place.
So `organisation_details` is a thing later chapters can *grow* — chapter 3
adds a switch to it, chapter 4 an expansion — and hand back into
`applicant()` without chapter 2's own wizard changing underneath them. Every
chapter from here on is `applicant(organisation=...)` plus whatever the
chapter is about. That is what composable means here: arms are wizards, so a
subflow defined once drops into several branches, and a wizard is a value you
can pass around.

A de-selected arm's answers are not thrown away either — see
[dormant memory](#dormant-memory) in chapter 6.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/branching/ &nbsp;·&nbsp; **Source:** [`ch02_branching.py`](tests/testapp/readme/ch02_branching.py)

---

## Chapter 3 — Which kind of organisation

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
    ch02.organisation_details.step(OrganisationTypeForm, name="organisation_type")
    .switch(
        on_field("organisation_type", "organisation_type"),
        {
            "charity": Wizard().step(CharityNumberForm, name="charity_number"),
            "company": Wizard().step(CompanyNumberForm, name="company_number"),
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

A selector is the same arbitrary code a predicate is — read several answers,
call out to a service, compute whatever you like — but asking *which* rather
than *whether* buys three things. Exactly one case can apply, so overlapping
conditions cannot resolve by declaration order. The selector runs **once per
switch** however many cases there are, so it is free to be expensive. And each
case's answers are stored under its own name rather than its position, so
reordering the cases cannot strand them.

`on_field(step, field)` is the common case said declaratively — route on the
value of an earlier answer. Prefer a plain function whenever the decision is
anything more than "what did they say"; a multi-valued field has no single
value to switch on, so route those with a predicate `.branch()` or a selector
of your own.

A value no case names falls to `default`, or past the switch entirely when
there is none — which is what the community group does.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/switch/ &nbsp;·&nbsp; **Source:** [`ch03_switch.py`](tests/testapp/readme/ch03_switch.py)

---

## Chapter 4 — As many trustees as there are

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

    def done(self, bound_wizard):
        trustees = [
            step.form.cleaned_data["name"]
            for step in bound_wizard.path
            if step.name and step.name.startswith("trustee-")
        ]
        return HttpResponse("Trustees: " + ", ".join(trustees))
```

The builder runs mid-walk, behind the validated count, and its steps are
spliced in where `.expand()` sits — inside the organisation arm, so an
individual is never asked. Answering the count parks the user on the first
grown step in a *single* request; a `get_wizard()` that read the count back
off stored state (chapter 5) would have to walk twice to notice its own
submission had changed the shape.

Good to know: the builder reaches back to prior answers **by name**, so
renaming an upstream step can break it; grown answers store positionally, so
raising a count keeps the answers already given and lowering it drops the
trailing ones; and every grown step must be routable (carry a `name`).

That positional storage is exactly why `.expand()` is the wrong tool for a
list the user grows and prunes over time — deleting from the middle would
shift every answer after it. Budget lines, in chapter 12, are that kind of
list, and each is its own run.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/expand/ &nbsp;·&nbsp; **Source:** [`ch04_expand.py`](tests/testapp/readme/ch04_expand.py)

---

## Chapter 5 — Different funds, different questions

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
> [/arts/](http://127.0.0.1:8000/readme/funds/arts/) &nbsp;·&nbsp; **Source:** [`ch05_funds.py`](tests/testapp/readme/ch05_funds.py)

---

## Chapter 6 — Check your answers

Before an application goes anywhere, the applicant should see what they said
and be able to change it. This chapter adds an address and a review step.

### Editing is a link

Because every step has its own URL, an "edit" affordance is just a link. GET a
completed step's URL to render it pre-filled; POST the changed answer back to
it to place it there. Editing is not a separate operation — putting an answer
at a step works the same whether or not it already had one.

The promise is that changing an answer costs the user only as much of the
wizard as the change actually invalidates — usually nothing. A trivial edit
lands straight back on the summary; an edit that flips a branch parks only at
the steps that now need attention, then fast-forwards through every
still-valid answer. Nothing downstream is lost to a typo, because an invalid
edit is kept and re-rendered with its errors while the sealed tail is carried
verbatim.

For an explicit in-page back link, any step template can reach
`request.wizard.back_url` (the previous step's URL, branch-aware; `None` on
the first step) and `request.wizard.run_url` (a "return to where I was" link):

```django
{% if request.wizard.back_url %}
  <a href="{{ request.wizard.back_url }}">Back</a>
{% endif %}
```

### The summary page

> **Optional module.** `gandalf.summary` reads a run's answers back for
> display; nothing in the core depends on it.

A "check your answers" step asks the same three questions of every answer —
what is it called, what does it say, and where do I go to change it — so
`SummaryMixin` answers them once. Mix it into the step's `FormView` and the
template gets a `summary` list, one row per answered step:

```python
from gandalf.form_views import StepFormView
from gandalf.summary import Group, Hide, SummaryMixin


class ConfirmForm(forms.Form):
    """No fields at all. The button *is* the confirmation."""


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


class AddressReviewStepView(ReviewStepView):
    summary_fields = {
        "address": [
            Group("line_1", "line_2", "town", "postcode"),
            Hide("lookup_token"),
        ],
    }


def with_contact_and_review(wizard):
    """The tail every chapter from here shares."""
    return (
        wizard.step(EmailForm, name="contact", label="Email")
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class ReviewedApplicationViewSet(WizardViewSet):
    url_name = "readme-review"
    template_name = "testapp/linear_wizard.html"
    wizard = with_contact_and_review(
        ch02.applicant(organisation=ch04.organisation_details)
    )
```

```django
<h1>Check your answers</h1>
<dl>
  {% for row in summary %}
    <dt>{{ row.label }}</dt>
    <dd>
      {% for field in row.fields %}
        <span>{% if field.label %}{{ field.label }}: {% endif %}{{ field.value }}</span>
      {% endfor %}
      <a href="{{ row.url }}">Change {{ row.label }}</a>
    </dd>
  {% endfor %}
</dl>
<form method="post">
  {% csrf_token %}
  <button type="submit">Confirm and continue</button>
</form>
```

`ConfirmForm` has no fields — a required checkbox beside a Confirm button
asks the same question twice while giving the user a way to get it wrong.
Gandalf reads a submission, not a field: an empty submission is still a
submission, and only a missing entry (`{"step": null}`) is a hole.

The rows come from `request.wizard.path`, so they are the answers on the
run's resolved route, in walk order, with the selected arm inlined — never the
step doing the summarising, and never an answer left behind in a dormant arm.
Each row carries `label` (the step's `label` context, else its name made
readable), `fields`, `url`, `name`, the `step` it came from, and its `form`;
each field carries `label`, `value`, `parts`, `name`, and the `bound_field`
the value came from.

**Values are display text, not stored data.** A choice shows its label — the
first row reads *An individual*, not `individual` — a boolean shows Yes/No,
dates take the active locale's format, an upload shows its filename, and an
unanswered optional field is blank rather than "None".

### Shaping a row

One field per answer suits most steps and not all of them: an address is five
answers and one line. `summary_fields`, keyed by step name, says so — `Group`
shows several of a step's fields as one answer, `Hide` shows none of them.
Fields no spec names keep a line of their own. A group takes the place of the
first of its fields, so the row still reads in form order, and empty answers
drop out, so a blank second line does not leave `", ,"` in the middle. A
group's `label=` is optional because a step whose every field is grouped is
already named by its row; `field.parts` is what `field.value` was joined
from, for a template that wants an address as lines.

A key naming a step the wizard does not declare raises `ImproperlyConfigured`,
because a renamed step would otherwise take its shaping with it — which is
why the address spec lives on `AddressReviewStepView` and the plain
`ReviewStepView` is what chapters without an address use. The check is
against what the wizard *declares*, so a key naming a step on the arm not
taken is fine.

### Every decision is a hook

Override on the view, deferring to `super()` for the cases you do not
special-case:

| Hook | Decides |
| --- | --- |
| `get_summary_steps()` | which steps get a row (default: every answered step) |
| `get_summary_label(step)` | a row's heading |
| `get_field_specs(step)` | a step's `Group` / `Hide` specs (default: `summary_fields` by step name) |
| `include_summary_field(step, bound_field)` | whether a field earns a line |
| `format_value(bound_field, value)` | how one answer reads |
| `summary_context_name` | the context variable's name (default `summary`) |

**One form per row.** Reading a step's answers means reconstructing its form
(see [Appendix C](#appendix-c-what-replaying-costs)), so a page that reached
for `step.form` per field would pay a validation per field. The mixin builds
each row from a single form, and `RuntimeStep.form` is itself built once per
step per request.

### Dormant memory

Editing an answer that flips a branch does not discard the arm you leave. Pick
*organisation*, name it, then change your mind to *individual*: the
organisation arm is now inactive, but its answer is not gone. Flip back and
the name is already there — the run fast-forwards past it instead of asking
again. A de-selected arm's answers are kept as **dormant memory**,
re-validated and restored if you flip back, so the user never re-types an
answer they already gave.

Dormant arms live in the session until the run completes, and arm identity is
positional (declaration order) — so a `get_wizard()` that reorders branch arms
between requests would misattribute the memory, the same positional-alignment
rule that applies to steps.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/review/ (pick organisation,
> name it, then change the first answer to individual and back) &nbsp;·&nbsp; **Source:** [`ch06_review.py`](tests/testapp/readme/ch06_review.py)

---

## Chapter 7 — A step with a view of its own

Two things a plain `Form` cannot do. An organisation's website can be
guessed from its email domain, so the website step wants a pre-filled
initial value. And an email address that already has an account should send
the applicant to log in, not to the next step.

### Bringing your own `FormView`

Pass a plain `Form` and Gandalf generates the step's view. Bring your own when
the step needs view-level behavior — a per-step template, `get_initial()`,
`get_form_kwargs()`, a custom `form_valid()`:

```python
from gandalf.form_views import StepFormView


class WebsiteStepView(StepFormView):
    form_class = WebsiteForm
    template_name = "testapp/other_linear_wizard.html"

    def get_initial(self):
        initial = super().get_initial()
        contact = self.request.wizard.path.find_step(name="contact")
        domain = contact.form.cleaned_data["email"].partition("@")[2]
        initial["website"] = f"https://{domain}"
        return initial


def with_contact_and_review(wizard):
    return (
        wizard.step(EmailLookupForm, name="contact", label="Email")
        .step(WebsiteStepView, name="website", label="Website")
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )
```

Start from **`StepFormView`**. It is a plain Django `FormView` with the one
piece of wizard boilerplate already written: the success URL. Gandalf reads
only the *status code* of a step's response — a 3xx means "this answer
stands, carry on" — and then discards the response, so the URL is never
followed, and every step view would otherwise redirect to `self.request.path`
to say nothing. The views Gandalf generates are built on the same class.

You still supply **`template_name`**: a step with its own view does *not*
inherit the viewset's `template_name` — that default only reaches the views
Gandalf generates — and without one, rendering raises `ImproperlyConfigured`.
Mixing the two styles is the normal case: `website` brings its own view, and
the rest stay plain `Form`s. Because the view keeps its own configuration,
the same class can also be mounted as an ordinary standalone view outside the
wizard — one place for the form's behavior across "create in wizard" and
"edit later" screens; give the standalone subclass a real `get_success_url()`.

### Reading run state from a step view

The step runs on a wizard-shaped request, so `self.request.wizard` is the same
`BoundWizard` the rest of the flow sees — `path` for the resolved route,
`path.find_step(name=...)` to address a prior answer. That works from
anywhere in the view: `get_initial()`, `get_form_kwargs()`,
`get_context_data()`, `form_valid()`.

**What a step view sees is the prefix before it** — the answers the walk has
already validated on this request, never the step's own answer and nothing
after it. That is the same contract a branch predicate gets, and it holds
whether the step is being rendered or replayed behind the cursor. A step is
replayed on every later request, so its reads run again each time; keep them
cheap. `find_step()` returns `None` for a step the run cannot see, so guard
the lookup when the step you want is not unconditionally upstream — the
example does not, because `contact` always precedes `website`.

Gandalf ships type annotations (`py.typed`), and `StepFormView` declares its
`request` as a `WizardRequest` — an `HttpRequest` carrying `wizard` — so
`self.request.wizard` type-checks with no cast. Branch predicates and
`.expand()` builders are handed a `WizardContext`; annotate them with that to
reach `context.run`.

### Escaping the wizard

Sometimes an answer means the user should not be in the wizard any more. A
step says so by raising an escape, an ordinary exception in the spirit of
`Http404`:

```python
from gandalf.escapes import Park


class EmailLookupForm(forms.Form):
    email = forms.EmailField(label="Email address")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("email") == "existing@example.com":
            raise Park(reverse("readme-login"))
        return cleaned_data
```

All three escapes take the same arguments as `django.shortcuts.redirect` (a
URL, a named route, or a model with `get_absolute_url()`); which one you
raise decides what the user comes back to:

| Exception | The escaping answer | Coming back to the run |
| --- | --- | --- |
| `Park` | discarded, with any files it uploaded | the same step, unanswered |
| `Advance` | stored, and satisfies the step | the next step |
| `Obliterate` | destroyed with the rest of the run | a fresh run |

Escapes can also be raised from a `FormView`'s `form_valid()` when the
decision needs the view. `Escape` is the base class, so `except Escape`
catches all three.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/step-view/ (answer
> `existing@example.com` to be parked) &nbsp;·&nbsp; **Source:** [`ch07_step_views.py`](tests/testapp/readme/ch07_step_views.py)

---

## Chapter 8 — Proof it exists

An organisation uploads its governing document. Uploaded bytes cannot live in
the session, so Gandalf persists them through a companion
`WizardFileStorage`; the session carries only a small ref (storage key plus
original name, content type and size).

```python
class GoverningDocumentForm(forms.Form):
    document = forms.FileField(label="Your governing document")


organisation_details = ch04.organisation_details.step(
    GoverningDocumentForm, name="governing_document", label="Governing document"
)


class DocumentedApplicationViewSet(WizardViewSet):
    url_name = "readme-upload"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def done(self, bound_wizard):
        document = bound_wizard.path.find_step(name="governing_document")
        if document is None:
            return HttpResponse("Application received (no document needed)")
        return HttpResponse(f"Received {document.files['document']['name']}")
```

The step template just needs the usual `enctype="multipart/form-data"`. Here
`done()` does guard its `find_step()`, because an individual never sees the
document step — it is on the organisation arm.

On replay, Gandalf reopens each stored file and re-injects it into
`request.FILES` before re-validating the step, so validators that inspect the
upload see the same value they saw originally. The bytes stay on the backend
until something asks for them: a plain `FileField` only reads the name and
the size, both of which the ref already carries, so a run's requests cost the
same whether its uploads are a kilobyte or a hundred megabytes. A validator
that does read the content — `ImageField`, a MIME sniff — still gets it,
fetched at the moment it asks. Editing respects keep-vs-replace per field.

The run's files are cleaned up automatically once `done()`'s response has
been rendered — so a `done()` that hands back a `TemplateResponse` can still
read the finished run back in the template, even though Django renders that
response after the view has returned.

The default storage writes under a `gandalf/<run_id>/` prefix of Django's
default storage; point it elsewhere (S3, a per-tenant location) by
subclassing `WizardFileStorage` and passing it to
`.configure(file_storage_class=...)`.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/upload/ &nbsp;·&nbsp; **Source:** [`ch08_uploads.py`](tests/testapp/readme/ch08_uploads.py)

---

## Chapter 9 — Finishing, and what it leaves behind

An application is a record in a database, not a string in a response. This
chapter opens one when the run starts, submits it when the run finishes, and
makes sure both happen exactly once.

```python
class RecordedApplicationViewSet(WizardViewSet):
    url_name = "readme-record"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def run_started(self, bound_wizard):
        application = Application.objects.create()
        bound_wizard.metadata["application_id"] = application.pk

    def done(self, bound_wizard):
        application = Application.objects.get(pk=bound_wizard.metadata["application_id"])
        answers = MergeCleanedData().reduce(bound_wizard.path)
        application.submit(answers["email"])
        return redirect("readme-received", pk=application.pk)

    def run_unavailable(self, bound_wizard, reason):
        if reason == "completed":
            return redirect("readme-received", pk=bound_wizard.metadata["application_id"])
        raise Http404("That application has expired.")
```

### `done()` runs exactly once

A run finishes the first time it is walked and every step is satisfied;
`done()` is called, its files are cleaned up, and the run is retired — its
answers are dropped and a small completion marker takes their place. After
that, every request for it (bare run URL or any step URL, GET or POST) is
answered by `run_unavailable()` without reaching the wizard. So a stale tab
cannot submit twice, and a refreshed completion page cannot re-charge a card.
Put side effects in `done()` and they happen once, full stop. The marker is
written *after* `done()` returns, so a `done()` that raises leaves the run
intact and resumable.

`run_unavailable(self, bound_wizard, reason)` answers everything that cannot
be run — `reason` is `"completed"` or `"unknown"` (never started, obliterated,
or a lost session). The default redirects to the start URL; here a completed
run goes to its own received page instead.

### `run_started()`: the once-per-run hook

A wizard's state is answers, and every answer is re-proved from scratch on
every request. That leaves nowhere to keep the other kind of fact a run
accumulates: **the record it opened somewhere else.** Nobody typed it, no form
validates it, and doing it twice is the bug.

`run_started(self, bound_wizard)` fires when a fresh run of this wizard is
created, and does nothing by default. It is the only hook that runs **exactly
once per run** without you having to arrange it — a run is minted once, so it
is called once. It is handed a run that already has an id and a resolved
wizard, so it can read `bound_wizard.wizard` and write
`bound_wizard.metadata`. Both doors a fresh run comes through call it — the
start URL and `begin()` / `RunDriver` (chapter 15).

`reopen()` and `resurrect()` (chapter 10) do not fire it, and neither does
`inspect()`. A run seeded from a stash is a continuation, not a start: its
metadata comes back with its answers, so the record it created is already
there. Unlike an observer, it may raise, and a raise propagates to whoever
asked for the run. The cost worth knowing: the bare start URL mints a run and
redirects, so this fires for a drive-by visit that answers nothing. If that
is too expensive to do speculatively, do it on first answer instead — from
the first step's `form_valid()`, guarded on the metadata bag.

### `bound_wizard.metadata`: what it remembers

A dict, readable and writable from anywhere holding the run — a step view, a
branch predicate, `done()`, a driver. `metadata.for_step("website")` addresses
a sub-bag per step name, so two steps cannot tread on each other and neither
can tread on the run's own keys.

**Every write goes straight to storage**, and that is the whole point. A walk
persists nothing: `walk()` builds a tree and hands it back, and only the
caller decides to `persist()`. A GET never does, yet a GET still replays
every stored answer through its real `FormView` — `form_valid()` included. So
a record id written into *state* during a GET is thrown away, and the next
GET opens a second record. The bag is stored beside the state, through its
own storage seam, and survives:

| | |
| --- | --- |
| a walk that never persists | the write already reached storage |
| a `Park` | same — nothing was waiting on the walk |
| re-answering a step | state is rewritten wholesale; the bag is not touched |
| **completion** | `complete_run` discards the answers and keeps the bag, so `run_unavailable()` above can still name the application |
| **a stash round trip** | the bag rides in the payload, unlike file refs — a ref names bytes that completion deletes, a record id names something that outlives the run |

Three sharp edges. Values must be JSON-safe. Only *assignment* writes
through: a read hands back a deep copy, so mutating a nested value in place
changes that copy and nothing else — assign the whole value back instead.
That refusal is deliberate and uniform: left alone it would depend on the
backend (a session hands back its live dict and the mutation lands but is
never saved; a durable store re-reads the row and the change is gone at
once), and working in development while losing data in production is the
worst of the outcomes. And when several keys change together, `update()`
puts them in with **one** write rather than one per key.

A write from a step view runs on every walk, because the step is
re-dispatched every time the run is replayed — so a step that writes metadata
must be idempotent about it, exactly as its `clean()` must be. That is
precisely why the thing you only want to do once belongs in `run_started()`,
which is walked past rather than re-run.

### Storage

Storage is session-backed. Gandalf ships `SessionStorage`, which keeps plain
JSON in the session behind the walk's `WizardContext` — the browser's own
when a browser is driving, and whichever one a script was handed otherwise.
It is the one touch point set on the viewset rather than via `.configure()`,
because it must exist *before* the wizard does — a `get_wizard()` reads
stored state to shape itself:

```python
class RecordedApplicationViewSet(WizardViewSet):
    storage_class = CustomSessionStorage
```

Retired runs are pruned to the most recent `SessionStorage.max_completed_runs`
(25 by default), so completed runs cannot grow a session without bound.

### Storage that outlives a session

An application the applicant comes back to over days needs somewhere better
than a session. Gandalf ships no durable backend — that would mean models,
migrations and a retention policy, and the only dependency here is Django — so
`storage_class` is the seam, and it is small enough to swap. `BoundWizard`
calls exactly these eleven things and nothing in the runtime, the walker or
the viewset reaches past them:

| Method | Contract |
| --- | --- |
| `__init__(context)` | The `WizardContext` is passed in, so a backend can scope by `context.actor` or a tenant |
| `initialise_run()` | Create a run, return its id |
| `retrieve_run(run_id)` | Return the id, or raise `RunNotFound`. **This is the whole authorisation model** — scoping the queryset by owner is what stops one user resuming another's run |
| `get_run_data(run_id)` | `{"state": [...], "meta": {...}}`, or `{"completed": True, "meta": {...}}` for a finished run |
| `get_state(run_id)` | The state list; `[]` for a completed run |
| `set_state(run_id, state)` | Store the list verbatim |
| `get_run_metadata(run_id)` | The run's metadata bag; `{}` for a run that recorded nothing. Readable on a completed run |
| `set_run_metadata(run_id, metadata)` | Store the bag verbatim, **now** — this is called from places that never persist state |
| `delete_run(run_id)` | Forget it entirely. Idempotent |
| `complete_run(run_id)` | Discard the state and mark it finished, *keeping the metadata*, and leaving the run *addressable*. Idempotent |
| `is_run_complete(run_id)` | Whether it has been tombstoned |

A [worked `ModelStorage`](tests/testapp/durable.py) lives in the test app,
driven end to end by
[`test_durable_storage.py`](tests/functional/test_durable_storage.py) — a
whole task list over the database, with the session holding nothing but the
login. The task list (chapter 11) and the journey (chapter 14) have a second,
smaller seam of their own, `section_store_class`; the same module implements
that too, and a durable task list needs **both** swapped — durable answers
nobody can find, or a durable index into runs that have expired, is what
swapping one gives you.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/record/ &nbsp;·&nbsp; **Source:** [`ch09_records.py`](tests/testapp/readme/ch09_records.py)

---

## Chapter 10 — Coming back later

Completion is terminal — `done()` fires once and the run's answers are gone.
An application is not filled in one sitting, though: the contact details
should be saved *and* stay editable. That is a **stash**.

```python
from gandalf.storage import SessionStashStore, StashNotFound
from gandalf.wizard import InvalidStash


class ContactDetailsViewSet(WizardViewSet):
    url_name = "readme-stash"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant")
        .step(EmailForm, name="contact")
    )

    def done(self, bound_wizard):
        SessionStashStore(bound_wizard.context).put(
            "contact", bound_wizard.stash(label="contact")
        )
        return HttpResponse("Contact details saved.")


def reopen_contact_details(request):
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.get("contact")
        url = ContactDetailsViewSet.resurrect(request, payload, expected_label="contact")
    except (StashNotFound, InvalidStash):
        return redirect("readme-stash")  # nothing stashed — start fresh
    return redirect(url)
```

Inside `done()`, `bound_wizard.stash()` returns a small JSON-safe payload of
the run's answers. The payload is yours — a model field, the session,
wherever your bigger flow keeps its pieces; `SessionStashStore` is the helper
for the common case (`put` / `get` / `pop` / `delete` / `keys`), server-side
so it cannot be tampered with in transit. To re-open it,
`resurrect(request, payload)` seeds a brand-new run from the payload and
returns the URL to send the user to; they land in the ordinary wizard UI with
every answer pre-filled, edit whatever they need, and `done()` fires again
for the new run when they finish.

What resurrection promises:

- **A fresh, ordinary run.** Standard URLs, editing, escapes. Resurrecting the
  same payload twice yields two independent runs. The original run's tombstone
  is untouched, so the once-per-run `done()` guarantee holds: re-completion
  fires `done()` for the *new* run.
- **Every answer is re-proved.** A payload is trusted no further than a live
  session's own state — a mangled answer parks the run on that step with its
  errors rather than completing silently.
- **What the run did elsewhere comes back with it.** The metadata bag rides
  in the payload, so a re-opened run still knows which record it created and
  does not open a second one; `run_started()` deliberately does not fire.
  File refs are stripped: the bytes are deleted at completion. An *optional*
  file field sails through; a *required* one parks the run at that step for
  the user to re-upload.
- **A step URL, never the bare run URL.** A stashed run's answers all
  validate, so `resurrect()` lands the user on a step (`step="..."` to choose
  which; default is the first). The bare run URL of a run whose every answer
  validates would fire `done()` on a GET.
- **Re-opening is edit-and-re-save.** Every answer already validates, so the
  *next* successful submission — including an edit to step one — walks
  straight to the end and fires `done()` again. A review step does not gate
  that; what it gives you is somewhere to *land*, and `SummaryMixin` drops the
  step doing the summarising from its own rows so a review page revisited
  this way does not offer to change itself.
- **Same-shaped wizard only.** Stored answers align with the wizard tree
  positionally, so a payload only resurrects correctly against a tree shaped
  like the one that stashed it. The `label` is the guard rail: stamp it at
  stash time, pass `expected_label` at resurrect time, and bump the label when
  a deploy reshapes the wizard — a mismatch raises `InvalidStash` before any
  run is created.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/stash/ &nbsp;·&nbsp; **Source:** [`ch10_stash.py`](tests/testapp/readme/ch10_stash.py)

---

## Chapter 11 — A task list

> **Optional module.** `gandalf.sections` is a pattern built on everything
> above, with its own vocabulary and a second storage seam. Nothing in the
> core depends on it.

An application is not one wizard. Contact details, an address, the project,
the budget, referees — each is its own thing, finished on its own, in any
order, and re-opened later. Chapter 10 did the stashing by hand; a **hub** is
that pattern with the bookkeeping owned by the library: declare the sections,
mix `SectionMixin` into each section's viewset, and the hub renders a row per
section carrying its title, its status and one URL that does the right thing
whichever state it is in.

```python
from gandalf.sections import HubView, Section, SectionMixin


class ContactSectionViewSet(SectionMixin, WizardViewSet):
    url_name = "readme-hub-contact"
    template_name = "testapp/linear_wizard.html"
    section_key = "contact"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        # A review step is what makes re-opening safe: without it, one
        # successful edit walks straight through to done() again.
        .step(ReviewStepView, name="review")
    )


class AddressSectionViewSet(SectionMixin, WizardViewSet):
    url_name = "readme-hub-address"
    template_name = "testapp/linear_wizard.html"
    section_key = "address"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class GrantHubView(HubView):
    template_name = "testapp/readme_hub.html"
    url_name = "readme-hub"
    section_url_name = "readme-hub-section"
    sections = [
        Section("contact", ContactSectionViewSet, title="Contact details", reopen_step="review"),
        Section("address", AddressSectionViewSet, title="Address", reopen_step="review"),
    ]
```

A hub is mounted exactly like a wizard, and publishes two patterns from
`url_name` — the page, and the door into one section. **Mount the sections
beside it, never beneath it:** the hub's `<slug:section>/` door matches any
single segment and would swallow them.

```python
urlpatterns = [
    path("readme/hub/", include(GrantHubView.urls())),
    path("readme/hub-contact/", include(ContactSectionViewSet.urls())),
    path("readme/hub-address/", include(AddressSectionViewSet.urls())),
]
```

```django
<p>You have completed {{ hub.completed }} of {{ hub.count }} sections.</p>

{% for row in hub.rows %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
```

`hub.count`, `hub.completed` and `hub.remaining` are the task list heading;
`hub.status` is derived for the set — **Complete** when every row is, **Not
started** when none has been touched, **Incomplete** in between — so the
button that submits the whole thing reads one flag rather than counting rows
in the view. The rows are built once per request, so asking is free.

**Sections override `section_done()`, never `done()`.** `done()` belongs to
the mixin: it stashes the finished answers under `section_key`, which is the
only thing that can tell the hub the section is finished, then hands off to
`section_done()` for what runs once per edit — saving to your models, say —
whose default sends the user back to the hub. A subclass that replaced
`done()` would leave the section reading as not started forever.

The two strings a section repeats back to its hub — `section_key` and
`hub_url_name` — are checked against the hub's own declaration when it
renders, because each holds only for as long as both sides stay typed the
same. A drifted key means the hub reads a stash nothing writes; a drifted
`hub_url_name` means finishing quietly deposits the user somewhere that does
not list the section they just finished.

### What each status means

| Status | Comes from |
| --- | --- |
| **Complete** | A stash under the section's key — the section ran to its own end and `done()` fired |
| **Incomplete** | A recorded run holding at least one submission |
| **Not started** | Everything else, including a section opened and left unanswered, and one whose run has expired |
| **Cannot start yet** | The section's own `blocked()` — chapter 13 |

A row is deliberately cheap: two storage reads and a `reverse()`, no walk, so
a hub of six sections costs six dict lookups rather than a form `clean()` per
answered step per row. Whether the stored answers still *validate* is not
asked — it would not change the row.

### Every link is a step URL, never a bare run URL

This is the one thing worth understanding. A run whose every stored answer
validates **completes on a GET**. So a hub row can never point at the
wizard's own URL: it would fire the section's side effects on a click. Rows
link to the hub's own door, which is the only place that can afford to ask
what exists: it resumes a live run, re-opens a stash, or starts a fresh run,
and every arm ends at `BoundWizard.entry_url()` — a step URL by construction.
Resuming is tried *before* re-opening, so a section already being edited
continues that edit rather than resurrecting a second run beside it.

### Re-opening is edit-and-re-save

A re-opened section arrives with every answer already valid, so **the next
successful submission walks to the end and fires `done()` again** — the user
changed something and it saved. `reopen_step="review"` lands them on their
answers with a change link each, rather than at step one.

### Reaching a run from outside its own request

The hub is built on three classmethods that bind a wizard outside its own
dispatch, and they are public API in their own right:

| Method | Returns |
| --- | --- |
| `MyViewSet.begin(request, **url_kwargs)` | A fresh run — the start URL minus the redirect |
| `MyViewSet.inspect(request, run_id, **url_kwargs)` | An existing run, bound and ready to read. Walks nothing; raises `RunNotFound` |
| `MyViewSet.reopen(request, payload, ...)` | A run seeded from a stash — the run behind `resurrect()` |

Each hands back a `BoundWizard`. A tombstoned run is *found*, not missing, so
check `is_complete` before running one.

### Customising

Every decision is a hook. `get_sections()` chooses the sections per request,
`get_section_status()` decides how far one has got, `get_hub_status()` how
far they have got between them — override it where an optional section should
not hold the whole page back — `get_section_title()` names it,
`get_status_label()` reworks the wording, and `resume_section()` /
`reopen_section()` / `start_section()` each own one way into a run.
`stash_unusable()` handles a payload whose `label` no longer matches — it
re-raises by default, because silently starting over looks to the user
exactly like their answers vanishing.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/hub/ &nbsp;·&nbsp; **Source:** [`ch11_hub.py`](tests/testapp/readme/ch11_hub.py)

---

## Chapter 12 — Budget lines

A budget is not one answer but a list of them, and the applicant decides how
long the list is. `gandalf.collections` is the "add another" pattern — a page
listing what has been added so far, with **Change** and **Remove** on each
row, an **Add another** question, and one item wizard behind all of them.

A collection is a hub whose sections are *built* rather than declared: one per
id in an ordered registry the user grows. Everything the hub does — the status
derivation, the resume-before-reopen door, the no-bare-run-URL guarantee —
applies unchanged.

```python
from gandalf.collections import CollectionView, ItemSectionMixin


class BudgetLineViewSet(ItemSectionMixin, WizardViewSet):
    url_name = "readme-budget-line"
    template_name = "testapp/linear_wizard.html"
    collection_key = "budget"
    collection_url_name = "readme-budget"
    # The answer that names a row, cached when the line finishes.
    item_title_step = "line"
    item_title_field = "item"
    wizard = (
        Wizard()
        .step(BudgetLineForm, name="line", label="Budget line")
        .step(ReviewStepView, name="review")
    )


class BudgetCollectionView(CollectionView):
    template_name = "testapp/budget.html"
    remove_template_name = "testapp/budget_remove.html"
    url_name = "readme-budget"
    collection_key = "budget"
    item_viewset = BudgetLineViewSet
    item_name = "Budget line"
    item_reopen_step = "review"
    min_items = 1
    continue_url_name = "readme-project-hub"


class ProjectHubView(HubView):
    template_name = "testapp/readme_hub.html"
    url_name = "readme-project-hub"
    section_url_name = "readme-project-hub-section"
    sections = [
        Section("project", ProjectSectionViewSet, title="Project", reopen_step="review"),
        # A collection page is not a wizard, so the row links straight at it
        # and answers for its own status.
        BudgetCollectionView.as_section("budget", title="Budget"),
    ]
```

### Mount the three as siblings, never nested

This is the one thing that will bite you, and it fails silently:

```python
urlpatterns = [
    path("readme/project/", include(ProjectHubView.urls())),
    path("readme/project-details/", include(ProjectSectionViewSet.urls())),
    path("readme/budget/", include(BudgetCollectionView.urls())),
    path("readme/budget-line/<uuid:item>/", include(BudgetLineViewSet.urls())),
]
```

`HubView` publishes `<slug:section>/`, which matches **any** single segment —
so a collection mounted at `project/budget/` is swallowed by the hub's own
door for a section named `budget`. And `WizardViewSet` publishes `""` as its
start URL — so an item wizard mounted at `budget/<uuid:item>/` occupies the
exact path of the collection's door for that item. Either way, whichever
`include()` is listed first wins, and the symptom is "Change stopped working"
rather than anything that looks like a URL conflict.

The collection publishes three patterns from `url_name`: the page (GET lists,
POST answers *add another*), `<url_name>-item` (the door into one item) and
`<url_name>-remove` (confirm on GET, remove on POST). The item kwarg is a
`uuid` rather than a slug, which is what lets `remove/` be a safe sibling.

```django
{% if collection.is_empty %}
  <h1>You have not added any budget lines</h1>
{% else %}
  <h1>You have added {{ collection.count }} budget line{{ collection.count|pluralize }}</h1>
  <ul>
    {% for row in collection.rows %}
      <li>
        {{ row.title }}
        <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
        <a href="{{ row.url }}">Change</a>
        <a href="{{ row.remove_url }}">Remove</a>
      </li>
    {% endfor %}
  </ul>
{% endif %}
<form method="post">
  {% csrf_token %}
  {{ form.errors.add_another }}
  <button type="submit" name="add_another" value="yes">Add another budget line</button>
  {% if not collection.is_empty %}
    <button type="submit" name="add_another" value="no">Continue</button>
  {% endif %}
</form>
```

The view reads one POST field, so two submit buttons carry the answer and the
question needs no widget of its own. `AddAnotherForm` still validates it;
`form_class` swaps it for something else entirely.

**A `collection` is a `Hub`.** The rows, the status and the counts are the
hub's own and mean here exactly what they mean on a task list, so "3 lines,
2 of them finished" costs no loop in the template. What a collection adds is
what a hub has no notion of: `collection.key` and `collection.url`,
`collection.is_empty`, `collection.declared_done` — whether the user has said
there are no more — and `collection.min_items`, so a page that asks for at
least one can say so. A collection page publishes only `collection` and no
`hub` beside it: one page, one status.

### Identity is opaque, so removing renumbers nothing

An item is a uuid, never a position. Delete from the middle and the survivors
keep their ids, their URLs and their answers. This is the single biggest
reason a collection is not `.expand()`: an expansion's answers are one
positional list, so deleting from the middle shifts every answer after it
down a slot, and every item lives in one run, so there is no such thing as a
half-finished *item*. Use `.expand()` for "how many trustees? now name each";
use a collection for "add as many as you like, and change your mind later".

### A row costs no walk

An item is titled by the answer named in `item_title_step` /
`item_title_field`, worked out **once, when the item finishes**, and cached.
The page reads a string. That is one walk per completion — on a request that
already walked twice — in exchange for none on every later render. An item
that has never finished falls back to a positional name (`Budget line 2`),
which is honest: nothing it has answered is known to name it. Override
`get_item_title(bound_wizard)` when the name is not one field.

### Completeness is declared, not derived

| Status | Comes from |
| --- | --- |
| **Not started** | No items |
| **Incomplete** | Items, but the user has not said there are no more — or has, while one is unfinished or `min_items` is unmet |
| **Complete** | The user answered *no more to add*, every item has finished, and there are at least `min_items` |

No reading of storage can say whether the applicant has more lines to add.
Only they can, so the page asks and the answer is stored. Answering *yes*
again withdraws it — pressing **Add another** *is* the user changing their
mind. Removing an item does not re-ask it: three lines minus one is still
"and no more".

### Full CRUD, and the order each action takes

| Action | What happens |
| --- | --- |
| **Add** | The item is registered *first*, then its wizard starts — which is what lets a half-finished item have a row, and leaves a listed, removable row rather than an orphan run if entering fails |
| **Read** | One `Section` per registered id; the hub's own status derivation and row building, unchanged |
| **Change** | The door resumes a live run or re-opens a stash. A re-opened item re-saves on the next submission — and re-caches the title, so a rename shows on the page |
| **Remove** | Run obliterated → run cleared → stash deleted → title cleared → `item_removed()` → registry entry last, so a hook that raises leaves the item still listed and still removable |

Each verb has one route. The door is **GET only** — it answers a POST with
`405`, because the route that destroys an item is `<url_name>-remove` and
only that one may.

### Customising

`get_item_ids()` chooses the items — override it to build the list from your
own records instead of the registry. `new_item_id()` mints identity,
`get_item_title()` names a row, `get_collection_status()` decides how far the
whole thing has got, `item_removed()` is where the application deletes
whatever `section_done()` saved, and `collection_done()` is what happens when
the user says that is all.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/project/ &nbsp;·&nbsp; **Source:** [`ch12_budget.py`](tests/testapp/readme/ch12_budget.py)

---

## Chapter 13 — Locked and hidden

Most task lists are not a flat set. Referees cannot be asked for until the
project has been described. And an application for more than £10,000 has to
say where the rest of the money is coming from — a section that, for most
applicants, does not exist. Those are two different things, and the section
says which it is **itself**.

### Sections that unlock

Override `blocked()` on the section's own viewset. It is handed the store the
hub keeps its bookkeeping in, and the two rules that cover nearly every task
list are each one read of it:

```python
class RefereesSectionViewSet(SectionMixin, WizardViewSet):
    section_key = "referees"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(RefereeForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, section, store):
        """Unlocks once the project has been described."""
        return not store.has_stash("project")
```

The hub declares nothing about it — `Section("referees",
RefereesSectionViewSet, title="Referees")`, as before. Answered by the
section rather than asked about it, the rule lives with the wizard it gates:
it has a name, a docstring, a subclass, and a test that needs no hub. A hub
method taking a `section` is a method with a key in scope, and a task list
that grows becomes a chain of `if section.key == ...`. Here there is no key
to branch on.

A classmethod because the hub asks from outside the section's own dispatch,
exactly as it asks `begin()` and `inspect()`: there is no instance yet, and
the point of the question is that there must not be a run. `section` is the
row being asked about — what one viewset mounted per item of a collection
needs to tell its items apart.

That one answer does both halves. The row renders `BLOCKED` with the label
**Cannot start yet**, and the door refuses it — a stale link or a hand-typed
URL lands back on the task list instead of starting the run. This is the one
place display and dispatch have to agree, so the door asks for the *status*
rather than the hook.

Being blocked **outranks** a stash, so a section whose prerequisite was
withdrawn after it was answered reports what the user can do rather than what
they once did. And a blocked section keeps the whole hub off `COMPLETE`,
which is why a section that may never unlock is a job for `hidden()`, below,
rather than a lock that never opens. `blocked()` runs once per row when the
page renders and once more at the door, so keep it cheap.

### The other rule reads a fact, not a stash

"Only above £10,000" turns on an *answer* given in the project section. The
project section wrote it down when it finished:

```python
class GatedProjectSectionViewSet(SectionMixin, WizardViewSet):
    section_key = "project"
    hub_url_name = "readme-gated"
    wizard = (
        Wizard()
        .step(ProjectForm, name="project", label="Project")
        .step(ReviewStepView, name="review")
    )

    def section_done(self, bound_wizard):
        project = bound_wizard.path.find_step(name="project")
        self.get_section_store().data["amount"] = int(project.form.cleaned_data["amount"])
        return super().section_done(bound_wizard)
```

`store.data` is the journey's record of what its sections decided — chapter
14 has the whole of it. **Read `store.data` and `has_stash()` in `blocked()`
and `hidden()`, never a stash's state.** A stash is positional against a
tree whose shape may depend on a branch predicate nobody has evaluated, so
reading an answer out of one costs a walk — and a hub row must never walk.
`section_done()` is where a section pays that walk once, while the run is
still readable and on a request that has already walked, and writes what it
decided; every render after reads a string.

### Sections that appear

Locked is one thing; *not there yet* is another. Match funding for an
applicant asking for £5,000 is not waiting on anything — it may never apply,
and listing it as **Cannot start yet** makes a promise the journey cannot
keep. For that, override `hidden()`, the sibling of `blocked()` with the same
signature and the same store:

```python
class MatchFundingSectionViewSet(SectionMixin, WizardViewSet):
    section_key = "match_funding"
    hub_url_name = "readme-gated"
    wizard = Wizard().step(MatchFundingForm, name="source", label="Match funding")

    @classmethod
    def hidden(cls, request, section, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD
```

A hidden section is gone for that request: not in `hub.rows`, not in
`hub.count` or `hub.completed`, and its door refuses a stale link exactly as
it refuses a key the hub never declared. A hub of three sections with one
hidden is a hub of two, and finishing those two completes it. Hidden outranks
blocked, since a section that does not exist cannot also be waiting.

Use `hidden()` for a section that may never apply and `blocked()` for one
that will, once the user has done something else first. The hub keeps
`section_blocked()` and `section_hidden()` for what a section cannot answer
alone — a rule spanning rows, or a collection gating every item at once. Each
is the question rather than a vote joined to the sections', so an override
that does not call `super()` replaces their answers. `get_sections()` keeps
its own job — choosing the sections by user, plan or feature flag — and is not
where a section hides from an answer.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/gated/ (ask for more than
> 10,000 and a section appears) &nbsp;·&nbsp; **Source:** [`ch13_gated.py`](tests/testapp/readme/ch13_gated.py)

---

## Chapter 14 — One application, start to submit

Everything so far, put together. A hub's sections add up to something — this
application — and that something is a **journey**. It has three things a
single hub does not: a scope, a memory, and an ending.

### A scope

Everything a hub keeps — which run each section is being answered in, the
stash a finished one left, a collection's items, what the sections decided —
lives in one record per journey. A hub mounted under a `<journey>` segment
reads its journey off the URL, and so does every section, collection page and
item wizard mounted under the same segment, so two applications in two tabs
are two URLs and two records in one session that never see each other:

```python
urlpatterns = [
    path("readme/apply/new/", include(ApplicationStartViewSet.urls())),
    path("readme/apply/<slug:journey>/", include(GrantApplicationHubView.urls())),
    path("readme/apply-setup/<slug:journey>/", include(SetupSectionViewSet.urls())),
    path("readme/apply-contact/<slug:journey>/", include(ContactSectionViewSet.urls())),
    path("readme/apply-project/<slug:journey>/", include(ProjectSectionViewSet.urls())),
    path("readme/apply-budget/<slug:journey>/", include(BudgetCollectionView.urls())),
    path("readme/apply-budget-line/<slug:journey>/<uuid:item>/", include(BudgetLineViewSet.urls())),
    path("readme/apply-match-funding/<slug:journey>/", include(MatchFundingSectionViewSet.urls())),
    path("readme/apply-referees/<slug:journey>/", include(RefereesSectionViewSet.urls())),
    path("readme/apply-documents/<slug:journey>/", include(DocumentsSectionViewSet.urls())),
]
```

Siblings, as always. A hub not mounted under a journey uses the one it
declares, `journey = "default"` — one per session, which is what chapters
11 to 13 were. Every section's viewset declares the same pair (`journey`,
`journey_url_kwarg`), and the hub refuses one that does not, since it would
finish into a record the hub never reads.

### Somewhere to be minted

The library does not decide when a journey begins; the first wizard does. It
has no journey yet, so its `done()` mints one, stashes its own answers as the
journey's first section, and sends the applicant to the hub under the new id:

```python
def record_applying_as(store, bound_wizard):
    step = bound_wizard.path.find_step(name="applying_as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]


class ApplicationStartViewSet(WizardViewSet):
    url_name = "readme-apply-start"
    wizard = (
        Wizard()
        .step(ApplyingAsForm, name="applying_as", label="Applying as")
        .configure(
            template_name="testapp/linear_wizard.html",
            observer_class=CountRejections,      # chapter 15
        )
    )

    def done(self, bound_wizard):
        journey = uuid.uuid4().hex
        store = SessionSectionStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applying_as(store, bound_wizard)
        return redirect("readme-apply-hub", journey=journey)


class SetupSectionViewSet(SectionMixin, WizardViewSet):
    """The same wizard, once a journey exists."""

    url_name = "readme-apply-setup"
    section_key = "setup"
    hub_url_name = "readme-apply-hub"
    wizard = ApplicationStartViewSet.wizard

    def section_done(self, bound_wizard):
        record_applying_as(self.get_section_store(), bound_wizard)
        return super().section_done(bound_wizard)
```

The hub then lists `Section("setup", SetupSectionViewSet, title="Applying
as")` — the same wizard as a `SectionMixin` viewset mounted under the journey
— so the setup answers are re-openable like any other section.

### A memory

`store.data` is the journey's record of what its sections decided: a
JSON-safe mapping written through on every assignment, with
`for_section(key)` sub-bags so sections cannot tread on each other or on the
journey. It is the same bag chapter 9's `bound_wizard.metadata` is, kept for
the journey rather than for one run, and it is the answer to the question a
stash cannot answer cheaply. `record_applying_as` writes *individual* or
*organisation* there, and the governing document section reads it back:

```python
class DocumentsSectionViewSet(SectionMixin, WizardViewSet):
    section_key = "documents"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(GoverningDocumentForm, name="document", label="Document")

    @classmethod
    def hidden(cls, request, section, store):
        return store.data.get("applying_as") != "organisation"
```

The project section writes the amount and match funding reads it, exactly as
in chapter 13; referees lock on `has_stash("contact")`. It is the bargain a
collection strikes to name its rows — one walk at completion, none per render
— generalised from one cached title to the whole journey.

### An ending

`hub.is_complete` says the submit button may appear; a POST to the hub page
presses it:

```python
class GrantApplicationHubView(HubView):
    template_name = "testapp/journey_hub.html"
    url_name = "readme-apply-hub"
    section_url_name = "readme-apply-hub-section"
    sections = [
        Section("setup", SetupSectionViewSet, title="Applying as"),
        Section("contact", ContactSectionViewSet, title="Contact details", reopen_step="review"),
        Section("project", ProjectSectionViewSet, title="Project", reopen_step="review"),
        BudgetCollectionView.as_section("budget", title="Budget"),
        Section("match_funding", MatchFundingSectionViewSet, title="Match funding"),
        Section("referees", RefereesSectionViewSet, title="Referees"),
        Section("documents", DocumentsSectionViewSet, title="Governing document"),
    ]

    def journey_done(self, hub, store):
        contact = store.get_stash("contact")
        application = Application.objects.create()
        application.submit(contact["state"][1]["step"]["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_hub_url())

    def journey_completed(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )
```

```django
{% if hub.is_complete %}
  <form method="post">
    {% csrf_token %}
    <button type="submit">Submit application</button>
  </form>
{% endif %}
```

`submit()` refuses if any row is not complete (`hub_incomplete()`, which
sends the user back to the hub by default), then runs `journey_done()` — the
application's work, and the one thing with no default — and only once that
has returned tombstones the journey, exactly as `SectionMixin.done()` runs
`section_done()` before clearing the run. A `journey_done()` that raises
leaves every section resumable. It runs inside the window where the stashes
are still readable; anything the done page needs goes in `store.data`, which
the tombstone keeps.

After that, the runs and stashes are gone, so a submitted journey can neither
be edited nor keep growing the session. The hub page and every door answer
with `journey_completed()` — `Http404` until you say what a submitted journey
looks like — a collection page sends the user on to its `continue_url`, and
each section's own wizard sends a bookmarked step URL back to the hub. Only
the ten most recently completed journeys are kept per session.

### Beyond the session

The store behind all of this is one class,
`SessionSectionStore(context, journey)`, and the contract it satisfies is
written down as `gandalf.types.SectionStore` (and `CollectionStore` for a
collection): the section runs and stashes, `data`, `complete()` and
`is_complete()`, plus a collection's registry. An application of seven
sections is a lot to hold in a cookie; the day it outgrows the session, a
store that keeps the same things in a table drops in by `section_store_class`
alone — [`tests/testapp/durable.py`](tests/testapp/durable.py) is that store,
scoped by owner and by journey, and the swap is the same one chapter 9
described for runs.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/apply/new/ &nbsp;·&nbsp; **Source:** [`ch14_journey.py`](tests/testapp/readme/ch14_journey.py)

---

## Chapter 15 — Knowing what you built

The application is done. Three things are worth knowing about it from the
outside.

### What shape is it

> **Optional to know about.** `wizard.outline()` is a read of the declaration.

A configured wizard can describe itself, as data:

```python
ExpandingApplicationViewSet.wizard.configure(template_name="...").outline()
# [{"kind": "step", "name": "applying_as", ...},
#  {"kind": "branch", "arms": [{"steps": [..., {"kind": "switch", ...},
#                                         ..., {"kind": "expand"}]}],
#   "default": [{"kind": "step", "name": "about_you", ...}]},
#  {"kind": "step", "name": "contact", ...}]
```

It is the data counterpart of the tree `repr()` you get while debugging:
every step in order, every fork with **all** of its possible routes, and a
marker wherever `.expand()` grows the tree from an answer. Since it describes
the declaration, it needs no run, no request and no storage. A dynamic
`get_wizard()` is described as it currently resolves.
`WizardViewSet.resolve(request)` is the third door alongside `begin()` and
`inspect()`: it binds the wizard without creating a run. Useful for a
progress indicator that has to cope with branches, for documentation or a
diagram, and for a test that pins a wizard's shape.

### How is it going

> **Optional module.** `gandalf.observers` is a hook and a no-op base class.

Which step do applicants get wrong most often? Declare an observer and it is
told what happens, for every run of that wizard — over HTTP, from a script,
or from a test. Chapter 14's setup wizard carries one:

```python
from gandalf.observers import WizardObserver


class CountRejections(WizardObserver):
    def submission(self, step, accepted, metadata):
        if not accepted:
            rejections.append(step.context["name"])
```

**One event per placement, not per validation.** A run re-proves every stored
answer on every request, so an observer told about validations would count
one mistyped answer again on every page that followed it. `submission()`
fires only when an answer is actually placed, so counting `accepted=False`
counts mistakes people made.

**Observers see what happened, never what was said.** A step's answers are
somebody's name and address, so an observer is handed the step *declaration*
and the outcome — enough to count, group and compare, and not enough to leak
personal data into a metrics backend. `metadata` is whatever the placement
claimed about itself: `None` for a browser submission, `{"unattended": True}`
for one a driver made. There is no "run started" event here, because a run
exists before its wizard is resolved; the viewset's `run_started()` is for
that. An observer must not raise.

### Filling it in without a browser

> **Optional module.** `gandalf.driver` needs nothing but Django and is never
> imported unless you ask for it.

`RunDriver` is the same wizard without a browser: it walks a run by calling
the runtime directly, so a data import, a management command, an admin action
— or an AI agent holding somebody's details — can answer steps as data.

```python
from gandalf.driver import RunDriver

driver = RunDriver.begin(FirstApplicationViewSet, may_finish=True)

driver.describe().schema        # JSON Schema for the current step's form
driver.submit({"full_name": "Ada"})
result = driver.submit({"email": "ada@example.com"})
if result.status == "complete":
    driver.finish()             # fires done() exactly once
```

`submit()` reports `"advanced"`, `"invalid"` (with `errors` in
`form.errors.get_json_data()` shape), `"complete"`, or `"escaped"`;
`submit(data, step="applying_as")` edits an earlier answer and lets the walk
re-route from it. `outline()` describes the declared journey before any
answers exist; `check(answers)` says what a bag of answers *would* do without
placing any of it; `prefill(answers)` places as many as the tree will take
and reports the residue; `answers()` hands back cleaned values, and
`answers(json_safe=True)` serialisable ones.

Nothing here is a second implementation. Every operation is the one a request
performs, so a run filled programmatically is an ordinary run: same `run_id`,
same stored state, same re-validation. With a durable storage backend you can
fill a run from a script and hand somebody `bound_wizard.entry_url("review")`
to check and confirm in the browser.

Two things follow from a caller that is not a person. **Concluding a run is
opt-in**: `done()` is where the irreversible things live, so `finish()`
raises `ConfirmationRequired` unless the driver was built with
`may_finish=True`. And **every placement records who made it**: the driver
marks its own `{"unattended": True}`, `submit(..., metadata={...})` records
anything else, and `placements()` reads it all back — so a rule like "never
overwrite what a person typed" can be written, and is yours to write, because
whose answer this is is a question about your domain rather than about
wizards. Files go both ways: `open_file(ref)` gets from a stored reference to
the bytes, and `submit({}, files={"document": uploaded})` places one.

> **Source:** the driver against the README's own wizards is
> [`test_driver_journeys.py`](tests/functional/test_driver_journeys.py).
> **See also:** [AGENT_ACCESS.md](AGENT_ACCESS.md) for the design behind
> this, and `gandalf.contrib.agent` for the other half — an agent built on
> the driver, which ships beside the library rather than inside it.

---

## Appendix A — Testing your wizards

Driving a multi-step wizard with the raw Django test client means chasing the
run id through the session and hand-building step URLs. `gandalf.testing`
does that plumbing for you, and a pytest plugin ships with the package —
installing django-gandalf makes the `wizard_driver` fixture available with no
conftest wiring (it builds on
[pytest-django](https://pytest-django.readthedocs.io/)'s `client` fixture).

`wizard_driver` is a factory: give it your viewset's `url_name` — the driver
reverses the same three names `urls()` published — and drive the whole wizard
in one call. For chapter 1:

```python
def test_chapter_1_collects_both_steps_and_finishes_once(wizard_driver):
    response, run = wizard_driver("readme-first").drive(
        [
            ("applicant", {"full_name": "Ada"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == 200
    assert run.is_completed
```

`drive()` starts a run (discovering its id from the session), POSTs each
`(step, data)` pair following redirects, and returns the final response along
with a `WizardRun` — URLs, requests, and stored state, all keyed by the run
id. Step by step, the same run object makes redirect and state assertions
direct:

```python
def test_chapter_1_first_answer_advances_and_stores(wizard_driver):
    run = wizard_driver("readme-first").start()

    response = run.post_step("applicant", {"full_name": "Ada"})

    assert response["Location"] == run.step_url("contact")
    assert run.state == [{"step": {"full_name": "Ada"}}]
```

Request helpers default to `follow=False` like the test client — pass
`follow=True` to land on the rendered next step. The run also exposes
`run.url`, `run.get()`, `run.get_step("name")` (the edit render of an
answered step), `run.data` (the raw session entry — `{"completed": True}`
after `done()` fires), and `run.seed_state([...])`.

- **Mount-prefix kwargs.** A wizard mounted under `readme/funds/<slug:fund>/`
  is driven with `wizard_driver("readme-fund", fund="arts")`.
- **Multiple runs.** `driver.start()` works with any number of existing runs;
  `driver.only_run()` and `driver.new_run(*known)` recover a run you didn't
  start yourself (a resurrected stash, say), raising `RunDiscoveryError` when
  the session is ambiguous.
- **Uploads** ride along as ordinary POST data:
  `run.post_step("governing_document", {"document": SimpleUploadedFile(...)})`.
- **Arranging a part-answered run.** `seed_state` writes stored state
  *verbatim*, so reach for it only when the state is one no walk would place.
  Answers the walk can reach are better placed than written: fill the run
  with a `RunDriver` over the client's own session, and the state is whatever
  the runtime really produces.

  ```python
  from gandalf.driver import RunDriver, fabricate_request

  session = client.session
  driver = RunDriver.resume(
      FirstApplicationViewSet, run.run_id, request=fabricate_request(session=session)
  )
  driver.prefill({"applicant": {"full_name": "Ada"}})
  session.save()   # nothing saves a session outside the request cycle
  ```

- **Session peeking and seeding.** `stored_runs(client)` /
  `stored_run(client, run_id)` / `seed_run(client, run_id, data)` read and
  write raw run entries; `stored_stash(client, key)` / `seed_stash(...)` do
  the same for caller-owned stash payloads (chapter 10); and
  `stored_journey(client)`, `stored_section_run(client, key)` /
  `seed_section_run(...)`, `stored_section_stash(client, key)` /
  `seed_section_stash(...)`, `stored_journey_data(client)` /
  `seed_journey_data(...)` and `seed_journey_complete(client)` do it for a
  journey's record, each taking `journey=` for a hub mounted under one — no
  session keys in your tests. They read the session stores directly, so they
  do not apply to a custom backend; assert against your own models instead.
- **Outside pytest** the helpers work from any test:
  `WizardTestDriver(Client(), "readme-first")`.
- Wizards with a **custom URL scheme** fall outside the driver's contract —
  drive those with the plain test client. To keep the plugin out of a run
  entirely: `pytest -p no:gandalf`.

Gandalf's own functional suite is written with these helpers, and the
snippets above are the checked-in tests for chapter 1 — **Source:**
[`test_readme_examples.py`](tests/functional/test_readme_examples.py).

---

## Appendix B — Configuration

Declaring steps is usually all you need; `.configure(...)` overrides a runtime
default when you want one. It is optional — a `WizardViewSet` configures a
plain `Wizard` with defaults automatically.

```python
wizard = (
    Wizard()
    .step(ApplicantForm, name="applicant")
    .configure(file_storage_class=TenantFileStorage, observer_class=CountRejections)
)
```

The same keyword pattern applies to every touch point on the configured
wizard — `template_name`, `form_view_factory`, `cursor_walker_class`,
`step_dispatcher_class`, `state_serializer_class`, `step_router_class`,
`file_storage_class` and `observer_class`. Each has a sensible default, so
you only configure what you need. A pre-configured wizard is taken as-is by
the viewset, so set `template_name` there too, as chapter 14's setup wizard
does. `storage_class` is the one thing set on the viewset instead, for the
reason chapter 9 gives.

For a runtime-level view of how the pieces fit together, see
[ARCHITECTURE.md](ARCHITECTURE.md). For driving a wizard programmatically —
an AI agent submitting steps as data instead of clicking the forms — see
[AGENT_ACCESS.md](AGENT_ACCESS.md).

---

## Appendix C — What replaying costs

Gandalf re-proves stored submissions rather than trusting a recorded position.
The rule is small enough to keep in your head:

> The walk runs a form's `clean()` **once per completed step per HTTP
> request** — and each step whose answers the request *reads back* costs one
> more.

So with `k` answers stored, a request costs `k` replays, and a POST costs one
more for the answer being submitted; completing an `N`-step run costs `N²`
validations end to end, spread over `2N` requests.

Reading answers back is the second clause. Proving an answer and displaying
it are separate passes over the same form — the walk dispatches the step's
view to prove it, `RuntimeStep.form` reconstructs one to hand back
`cleaned_data` — so a check-your-answers page costs **two validations per
answered step**. A branch predicate that dereferences an earlier answer is
charged the same way, on every request that resolves its arm.

Within one read, the form is built once per step however many fields you
render from it. What does add up is reading *again*: `path` builds fresh step
nodes on each access, so iterate the steps you hold rather than re-reading
`wizard.path` per field. Outside a render — in `done()`, a completion page, or
a driver reading a run — every `path` access walks: looking each of `k` steps
up separately costs `k²` validations in that one request, where iterating
once costs `k`.

**The number that matters is not `N`, it is how many of your steps are
expensive** — each completed step is validated once per request whether the
user is on step 5 or step 29, so `N²` only bites when *most* steps do real
work in `clean()`.

Measured on a 2023 laptop with `just bench`, for a linear wizard:

| steps | `clean()` | whole run | final POST |
|---|---|---|---|
| 30 | free | 72ms | 1.1ms |
| 30 | 5ms on *every* step | 6.7s | 222ms |

Gandalf's own share is about a millisecond per request at 30 steps;
everything else is your forms. If expensive `clean()` becomes a problem, move
the work into `done()` (where it runs once), store a cheaply-recheckable
token, or accept that some checks belong only at submission time. `just
bench` measures your own shapes, and `tests/functional/test_walk_cost.py`
pins the counts so they cannot regress unnoticed.

A hub row (chapter 11) deliberately pays none of this: two storage reads and
a `reverse()`, never a walk. That is why what a section decided is written to
`store.data` at completion rather than read out of a stash at render time.

---

## Appendix D — Coming from `django-formtools`

Gandalf neither forks nor depends on `django-formtools` — the storage shape,
the URL model, and the re-proving walk all differ, so there is no drop-in
replacement. What maps cleanly is the *declaration*: a `form_list` becomes
chained `.step(...)` calls, and a `condition_dict` becomes
`.branch(condition(predicate, subflow))`. The predicates are the same idea —
a callable given the request — but a Gandalf predicate runs behind a
fully-validated prefix, so it reads prior answers with
`path.find_step(...).form.cleaned_data` unconditionally.

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
    applying_as = context.run.path.find_step(name="applying_as")
    return applying_as.form.cleaned_data["applying_as"] == "organisation"

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as")
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
organisation_details = Wizard().step(OrganisationForm, name="organisation").step(OrganisationTypeForm, name="organisation_type")
individual_details = Wizard().step(AboutYouForm, name="about_you")

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as")
    .branch(condition(is_organisation, organisation_details), default=individual_details)
    .step(EmailForm, name="contact")
)
```

The payoff for tree-shaped journeys: branch condition and target stay
together, arms are reusable sub-wizards, and the whole flow is visible in one
declaration instead of growing bespoke navigation plumbing as branches
multiply.

---

## Contributing

See `CONTRIBUTING.md` for local setup, workflow expectations, separated unit
and functional test commands, and commit message conventions.
