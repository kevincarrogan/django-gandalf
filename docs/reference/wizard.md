# Wizard

`gandalf.wizard` — the builder that declares a wizard's shape, and the
configured wizard a viewset runs.

```python
from gandalf.wizard import (
    ConfiguredWizard,
    InvalidStash,
    MergeCleanedData,
    StepNameRouter,
    Wizard,
    branch,
    condition,
    on_field,
    step,
    switch,
)
```

The module also re-exports `Run`, `StepFormView`, `WizardFileStorage`,
`WizardObserver` and `form_view_factory`, documented on their own pages
([The run](run.md), [Step views](step-views.md),
[File uploads](file-uploads.md), [Observers](observers.md),
[Configuration](configuration.md)).

---

## Reference

### `Wizard(*, tree=None)`

The declaration builder. A `Wizard` is a value: every builder method
returns a *new* `Wizard` and leaves the one it was called on untouched, so a
sub-flow declared once can be grown into several variants and dropped into
several branches without any of them changing underneath the others.

**Parameters**

- `tree` — a declaration tree (`gandalf.tree.Node`) to start from. Default
  `None`, an empty wizard. Normally left alone; the builder methods supply
  it.

**Attributes**

- `tree` — the head of the declaration tree, or `None` for an empty
  wizard. Each node is a frozen dataclass from `gandalf.tree` (`Step`,
  `Branch`, `Switch`, `Expand`) linked by `next`.

**Caveats**

- `Wizard` declares; it does not run. Lifecycle methods (`initialise()`,
  `walk()`, `path`, …) live on [`Run`](run.md), which the
  viewset builds per request.
- Nothing on a `Wizard` is validated until it is configured and resolved
  — see [`ConfiguredWizard`](#configuredwizard) and *Validation at resolve
  time* below.

### `Wizard.step(form_class_or_form_view_class, /, **context)`

Append a step.

**Parameters**

- `form_class_or_form_view_class` — positional only. Either a
  `django.forms.Form` subclass, for which a view is generated at configure
  time, or a `FormView` subclass (normally a
  [`StepFormView`](step-views.md)) that brings its own view and template.
- `**context` — the step's context. Every keyword becomes a key; there is no
  fixed schema. Two keys are read by the library:

  | Key | Read by |
  | --- | --- |
  | `name` | [`StepNameRouter`](#stepnamerouter) (the URL segment), `RuntimeStep.name`, `path.find_step(name=...)`, `on_field`, `outline()` |
  | `label` | the summary mixin's `summary_label_context_key` (see [Summary](summary.md)) |

  Any other key is stored as declared and is matched by
  `find_step(**context)` / `filter_steps(**context)` and reported by
  `outline()`.

**Returns** — a new `Wizard` with the step appended.

**Caveats**

- A step with no `name` is not routable and is refused when the wizard is
  resolved by a viewset (see *Validation at resolve time*). Declaring one is
  not itself an error — the builder does not know how it will be routed.
- `context=` is refused with `ImproperlyConfigured`. Up to 0.9 the context
  was passed as `context={...}`; under keywords that spelling would silently
  declare a step whose only context key is `"context"`, so it is rejected
  outright. Spell the keys out: `.step(Form, name="email")`.

### `Wizard.branch(*conditions, default=None)`

Append a fork whose arms are guarded by predicates.

**Parameters**

- `*conditions` — `(predicate, arm)` pairs, normally built with
  [`condition()`](#conditionpredicate-target). `predicate` is any callable
  `(context: WizardContext) -> bool`; `arm` is a `Wizard` — an empty
  `Wizard()` for an arm that adds nothing.
- `default` — the `Wizard` (or `None`) taken when no predicate returns true.
  Default `None`.

**Returns** — a new `Wizard` with the branch appended.

**Semantics**

- **First match wins.** Arms are asked in declaration order and the first
  predicate to return true selects its arm; later predicates are not
  called.
- **An empty `Wizard()` as an arm** means "nothing extra here": the walk
  continues at the node after the branch. The same applies when no arm
  matches and there is no `default`. Passing `None` in place of an arm
  raises `AttributeError` — only `default` accepts `None`.
- A predicate runs **behind a fully-validated prefix** — every step before
  the branch has already been proved on this walk — so it may dereference
  `context.run.path.find_step(...).form.cleaned_data` without guarding for
  a missing answer.
- An arm's answers are stored under the arm's declaration-order index
  (`"0"`, `"1"`, …) or under `"default"`, as `{"branch": {"<arm>": [...]}}`.
  Inserting an arm before an existing one changes the index the existing
  arm's answers are stored under. A de-selected arm's answers are kept
  (dormant memory; see [Summary](summary.md)).

### `Wizard.switch(selector, cases, default=None)`

Append a fork whose arms are named by the value a selector returns.

**Parameters**

- `selector` — a callable `(context: WizardContext) -> str`, or an
  [`on_field`](#on_fieldstep-field).
- `cases` — `dict[str, Wizard]`, one arm per outcome, keyed by the value
  that selects it. An arm that adds nothing is an empty `Wizard()`.
- `default` — the `Wizard` (or `None`) taken when the selector returns a
  value no case names. Default `None`.

**Returns** — a new `Wizard` with the switch appended.

**Raises** — `ImproperlyConfigured` at declaration time if a case is called
`"default"`: that key is where the fallback arm's answers are stored.

**Semantics**

- The selector is called **once per walk** however many cases there are.
  Each case is still a real guard (`gandalf.tree.CaseGuard`) so any code
  that walks a declaration tree keeps working, but the guards ask the run
  for the memoised value rather than calling the selector again.
- Exactly one case can apply. A value no case names falls to `default`, or
  past the switch entirely when there is none.
- Each case's answers are stored under the **case name**, not its position:
  `{"branch": {"charity": [...]}}`. Reordering the cases cannot strand
  their answers. The fallback arm's answers are stored under `"default"`.
- A `Switch` is a `Branch` (`gandalf.tree.Switch` subclasses
  `gandalf.tree.Branch`); everything said about a branch's prefix and
  dormant memory applies.

### `Wizard.expand(builder)`

Append a point where the tree grows during the walk.

**Parameters**

- `builder` — a callable `(context: WizardContext) -> Wizard`. It runs
  mid-walk, behind a fully-validated prefix, and the steps of the `Wizard`
  it returns are spliced in at this point.

**Returns** — a new `Wizard` with the expansion appended.

**Semantics**

- The builder is called on every walk that reaches the expansion; the
  declared node carries only the builder, and the subtree does not exist
  until then. `outline()` therefore reports only `{"kind": "expand"}`.
- **Every expanded step must be routable** — build them with
  `.step(..., name=...)`. This is checked when the subtree is built, not at
  resolve time, and raises `ImproperlyConfigured` *"Every expanded step needs
  a routable name; … Unroutable steps: …"*.
- **An expansion may not contain another expansion.** A branch inside an
  expansion, and an expansion inside a branch arm, are both fine; nesting
  `.expand()` inside a builder's result raises `ImproperlyConfigured`
  *"An expansion cannot contain another expansion."*, again at build time.
- **Answers store positionally**, as `{"expand": [entry, entry, …]}`.
  Growing the count keeps the answers already given and appends a hole;
  shrinking it drops the trailing answers. Removing a step from the middle
  shifts every answer after it — for a list the user grows and prunes over
  time, use [add another](add-another.md) instead.
- A builder that returns an empty `Wizard` leaves nothing behind: the walk
  passes straight to the node after the expansion and the state holds no
  entry for it.
- Answering the step that decides the count parks the user on the first
  grown step in a *single* request, because the builder runs inside the same
  walk that placed the answer.

### `Wizard.configure(**configuration)`

Freeze the declaration into a [`ConfiguredWizard`](#configuredwizard).

**Parameters** — see [Configuration](configuration.md) for every key. In
brief: `template_name`, `form_view_factory`, `cursor_walker_class`,
`step_dispatcher_class`, `state_serializer_class`, `step_router_class`,
`file_storage_class`, `observer_class`.

**Returns** — a `ConfiguredWizard`.

**Raises** — `ImproperlyConfigured` if `storage_class` is passed (it belongs
on the viewset), or if any step is a bare `Form` and no `template_name` was
given.

### `step(form_class_or_form_view_class, /, **context)`

Module-level entry point: `Wizard().step(...)`. Returns a `Wizard` with one
step.

### `branch(*conditions, default=None)`

Module-level entry point: `Wizard().branch(...)`. Returns a `Wizard` with one
branch.

### `switch(selector, cases, default=None)`

Module-level entry point: `Wizard().switch(...)`. Returns a `Wizard` with one
switch.

### `condition(predicate, target)`

Pair a predicate with the arm it selects, for `.branch()`.

**Parameters**

- `predicate` — `(context: WizardContext) -> bool`.
- `target` — a `Wizard`.

**Returns** — the tuple `(predicate, target)`. It exists to make a branch
read as what it is; passing the tuple directly is equivalent.

### `on_field(step, field)`

A selector for `.switch()` that reads a value straight out of an earlier
answer. A frozen dataclass; instances are callable.

**Parameters**

- `step` — the `name` of an answered step on the current route.
- `field` — a field of that step's form.

**Attributes**

- `step`, `field` — as given.
- `__name__` — `"<step>.<field>"`. This is what `outline()` reports as
  `decided_by`.

**Behaviour**

- Called with a `WizardContext`, it finds the step by name on
  `context.run.path` and returns `str(cleaned_data.get(field, ""))` — a
  field the form did not clean yields `""`.
- Raises `ImproperlyConfigured` *"on_field(…) found no answered step named
  … before this switch."* when the named step is not on the validated
  prefix — because it is not answered, was renamed, or sits on another
  arm.
- Scalar answers only. A multi-valued field has no single value to switch
  on; route those with a selector of your own or a predicate `.branch()`.

Because `on_field` *is* the answer rather than a computation over it, an
outline can name which step and field decide the route (`source`). Reach for
a plain function whenever the decision is anything more than "what did they
say".

### `ConfiguredWizard`

A declaration plus its configuration. Built by `Wizard.configure()`; not
normally constructed directly (`ConfiguredWizard(*, tree, configuration)`).

**Attributes** — each is the configured value or the class default; see
[Configuration](configuration.md) for what each is for.

| Attribute | Default |
| --- | --- |
| `tree` | the declaration tree with a `form_view` attached to every step |
| `configuration` | the `dict` passed to `configure()` |
| `form_view_factory` | `gandalf.form_views.form_view_factory` |
| `file_storage_class` | `gandalf.file_storage.WizardFileStorage` |
| `observer_class` | `gandalf.observers.WizardObserver` |
| `cursor_walker_class` | `gandalf.runtime.CursorWalker` |
| `step_dispatcher_class` | `gandalf.runtime.StepDispatcher` |
| `state_serializer_class` | `gandalf.runtime.StateSerializer` |
| `step_router_class` | `StepNameRouter` |

**Methods**

- `configure(**configuration)` — always raises `ImproperlyConfigured`
  *"ConfiguredWizard instances cannot be configured."* Configure once, from
  the `Wizard`.
- `outline()` — the declared shape as data; see below.
- `configure_expansion(built)` — configures and vets the `Wizard` an
  `Expand` builder returned (routable names, no nested expansion). Called by
  the runtime; documented here because its `ImproperlyConfigured` errors are
  the ones a builder author sees.

**Caveats**

- A `ConfiguredWizard` is what a viewset takes as-is: `WizardViewSet` does
  not re-configure one, so its `template_name` must be given here rather
  than on the viewset. See [Configuration](configuration.md).
- `configure()` stores every key it is given and reads only the ones it
  knows. A misspelt key is silently ignored.

### `ConfiguredWizard.outline()`

The wizard's declared shape, as a list of dicts. A description of the
declaration: it needs no run, request or storage, and gives the same answer
before anybody starts and after they finish. The last-resolved shape of a
dynamic `get_wizard()` is what is described — see
[`WizardViewSet.resolve()`](viewsets.md).

**Returns** — `list[dict]`. Each entry has a `kind`:

| `kind` | Keys |
| --- | --- |
| `"step"` | `name` — the `name` context, or `None`; `context` — a copy of the full context dict (`{}` when none); `declaration` — the `gandalf.tree.Step` node itself |
| `"branch"` | `arms` — a list of `{"when": predicate.__name__ or None, "description": inspect.getdoc(predicate), "steps": [entries…]}` in declaration order; `default` — the default arm's entries (`[]` when none) |
| `"switch"` | `decided_by` — `selector.__name__` or `None`; `description` — `inspect.getdoc(selector)`; `cases` — a list of `{"case": name, "steps": [entries…]}` in declaration order; `default` — as for a branch; and, only when the selector is an `on_field`, `source` — `{"step": ..., "field": ...}`, in which case `description` is `None` |
| `"expand"` | nothing else — an expansion's steps do not exist until the answer that shapes them does |

Every entry is JSON-serialisable except `declaration`; callers that want
plain data drop it, or replace it with something derived from it (a JSON
Schema of the step's form, say).

### `StepNameRouter`

Routes the optional URL step segment to a step-context lookup, and reverses
a step declaration back into a segment. The default `step_router_class`.

**Attributes**

- `url_kwarg = "gandalf_step"` — the URL kwarg the segment is captured in.
  `WizardViewSet.urls()` publishes `<uuid:run_id>/<slug:gandalf_step>/`.
- `context_key = "name"` — the step-context key routed on.

**Methods**

- `resolve(url_kwargs) -> Context | None` — `{context_key: value}` for the
  captured segment, or `None` when `url_kwargs` has no (or an empty)
  `url_kwarg`. With no segment the wizard behaves as if routing did not
  exist.
- `reverse(step) -> str | None` — the segment for a `gandalf.tree.Step`:
  `step.context[context_key]`, or `None` when the step carries none (an
  unroutable step).
- `clean_url_kwargs(url_kwargs) -> dict` — `url_kwargs` without
  `url_kwarg`.

**Caveats**

- Subclass to route on another context key (`context_key = "slug"`) or a
  composite lookup, and pass it as `.configure(step_router_class=...)`. The
  dict `resolve()` returns is matched against step context exactly as
  `find_step(**context)` is.
- For a URL scheme the router cannot express, skip `urls()`, write the
  patterns yourself and override the viewset's three URL hooks
  ([`WizardViewSet`](viewsets.md)).

### `MergeCleanedData`

A `gandalf.tree.Reducer` that folds every completed step's `cleaned_data`
into one dict, last write wins on key collisions.

- `MergeCleanedData().reduce(run.path)` — the usual call.
  `reduce()` also accepts `run.runtime_tree`.
- Per node: `visit_step()` returns `step.form.cleaned_data`; `visit_branch()`
  and `visit_expand()` return their sub-fold; `initial()` is `{}` and
  `combine()` is `{**accumulator, **value}`. Override any of them for a
  different merge policy.

`gandalf.tree.Reducer` is the public base: a bottom-up fold whose `reduce()`
walks a chain (a `Path`, or a runtime head) calling each node's `visit_*`
and combining the results. Its defaults collect a list; override `initial()`
and `combine()` to fold into any shape. It is not re-exported from
`gandalf.wizard` — import it from `gandalf.tree`.

**Caveats** — reading `cleaned_data` builds and validates each step's form
again; see [Walk costs](walk-costs.md).

### `InvalidStash`

Re-exported from `gandalf.runtime`. A `ValueError` raised when a payload
cannot seed a run: not a stash envelope, an unsupported version, or a label
that does not match the one expected. See [Stashing](stashing.md).

### Validation at resolve time

A viewset resolves its wizard on every request (`get_wizard()`, then
`configure_wizard()` for a bare `Wizard`). Resolution checks the **whole
declared tree** — every arm of every branch, not only the route this walk
takes — and raises `ImproperlyConfigured` for:

| Condition | Message |
| --- | --- |
| a step the router cannot reverse | *"Every wizard step needs a routable name; declare steps with .step(..., name=...). Unroutable steps: …"* |
| two steps reversing to the same segment | *"Wizard step names must be unique; a URL segment has to name exactly one step. Duplicated: …"* |
| a bare `Form` step with no `template_name` | *"Wizard.configure() must receive template_name when generating FormView steps from Form classes."* |

Expanded subtrees cannot be checked here because they do not exist yet; they
get the routability check (but not the uniqueness check) when they are
built. Re-resolving a static wizard hands back the same object, so the walk
over the tree is not repeated.

---

## Usage

### A linear wizard

```python
from django import forms

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ApplicantForm(forms.Form):
    full_name = forms.CharField(label="Your name")


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email address")


class ApplicationViewSet(WizardViewSet):
    url_name = "grant-application"
    template_name = "grants/step.html"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="applicant", label="About you")
        .step(EmailForm, name="contact", label="Contact details")
    )
```

### Branching on an earlier answer

```python
from gandalf.wizard import Wizard, condition


def is_organisation(context):
    applying_as = context.run.path.find_step(name="applying_as")
    return applying_as.form.cleaned_data["applying_as"] == "organisation"


individual_details = Wizard().step(AboutYouForm, name="about_you")
organisation_details = Wizard().step(OrganisationForm, name="organisation")

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as")
    .branch(condition(is_organisation, organisation_details), default=individual_details)
    .step(EmailForm, name="contact")
)
```

`organisation_details` is unchanged by being placed in the branch; a later
module can grow it (`organisation_details.step(...)`) and build a second
wizard from the result.

### Switching on a choice

```python
from gandalf.wizard import Wizard, on_field

organisation_details = (
    Wizard()
    .step(OrganisationTypeForm, name="organisation_type")
    .switch(
        on_field("organisation_type", "organisation_type"),
        {
            "charity": Wizard().step(CharityNumberForm, name="charity_number"),
            "company": Wizard().step(CompanyNumberForm, name="company_number"),
        },
        # No default: a community group has no number to give, so the walk
        # continues past the switch.
    )
)
```

### Growing steps from a count

```python
from gandalf.wizard import Wizard


def build_trustee_steps(context):
    count = context.run.path.find_step(name="trustees").form.cleaned_data["trustees"]
    steps = Wizard()
    for index in range(count):
        steps = steps.step(TrusteeForm, name=f"trustee-{index}")
    return steps


organisation_details = (
    Wizard()
    .step(TrusteeCountForm, name="trustees")
    .expand(build_trustee_steps)
)
```

### Reading a wizard's shape

```python
configured = application.configure(template_name="grants/step.html")

for entry in configured.outline():
    if entry["kind"] == "step":
        print(entry["name"], entry["context"].get("label"))
    elif entry["kind"] == "switch":
        print("decided by", entry["decided_by"], [case["case"] for case in entry["cases"]])
```

From a viewset, `ApplicationViewSet.resolve(request).wizard.outline()` gives
the same for a dynamic `get_wizard()`, without starting a run.

---

## Troubleshooting

### `ImproperlyConfigured: Every wizard step needs a routable name`

A step was declared without `name=` and the viewset routes steps by URL
segment. Add `name="..."` to every `.step()`. If the message says *expanded*
step, the offending step is inside an `.expand()` builder's result, and the
error surfaces on the request that reaches the expansion.

### `ImproperlyConfigured: Wizard step names must be unique`

Two steps in the declared tree reverse to the same segment — including
steps on different arms of a branch, which the walk would never both reach
but the URL cannot tell apart. Rename one.

### `ImproperlyConfigured: … context= is no longer how to pass one`

`.step(Form, context={...})` is the pre-0.10 spelling. Pass the keys as
keywords: `.step(Form, name="email", label="Email")`.

### `ImproperlyConfigured: A switch case cannot be called "default"`

`"default"` is the storage key for the fallback arm. Pass the fallback as
`default=Wizard()...` instead of as a case.

### `ImproperlyConfigured: on_field('trustees', 'count') found no answered step named 'trustees'`

The step `on_field` reads is not on the validated prefix at the switch —
it is declared after the switch, sits on another branch arm, or was renamed.
`on_field` reaches back by name, so renaming an upstream step breaks every
`on_field` and builder that names it.

### My `.step()` call did nothing

The builder is immutable. `wizard.step(Form, name="x")` returns a new
`Wizard`; assign the result (`wizard = wizard.step(...)`).

### `ConfiguredWizard instances cannot be configured`

`.configure()` was called twice, or on the result of a previous
`.configure()`. Configure once, at the end of the chain, with every key.

---

**Learn:** [Chapter 1 — Steps and completion](../learn/01-steps-and-completion.md), [Chapter 2 — Branching](../learn/02-branching.md), [Chapter 3 — Switching](../learn/03-switching.md), [Chapter 4 — Expanding](../learn/04-expanding.md) · **Related:** [Configuration](configuration.md), [`WizardViewSet`](viewsets.md), [The run](run.md), [Add another](add-another.md)
