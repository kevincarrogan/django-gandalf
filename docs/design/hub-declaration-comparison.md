# Declaring a hub: eleven shapes compared

Companion to [`hub-declaration-sketches.py`](hub-declaration-sketches.py),
which has chapter 14's grant application written out in full in each
shape. This page is the argument: what each shape buys, what it costs,
and where the seams are — with the lines that show it.

The lens throughout is **cohesion**: does the thing that *writes* a fact
and the thing that *reads* it sit together, or are they two places joined
by a string? That was the original complaint about `member_key` /
`hub_url_name`, and it turns out to be the complaint about the gates too.

## At a glance

| # | Shape | Cohesion | Rhymes with `Wizard()` | Verdict |
| --- | --- | --- | --- | --- |
| [0](#0-main-a-viewset-class-per-member) | main — a class per member | apparent only | ✗ | replaced |
| [A](#a-the-branch-builder-with-lambdas) | branch — builder, lambdas | low | ✓ | the base |
| [B](#b-class-body) | class body | high (local) | ✗ | the serious alternative |
| [C](#c-builder-with-named-predicates) | builder, named predicates | medium | ✓ | A, tidied |
| [D](#d-the-wizard-owns-its-identity) | wizard owns its identity | medium | partly | no |
| [E](#e-keyword-rows) | keyword rows | low | ✗ | no |
| [F](#f-page-vocabulary) | page vocabulary | medium | ✓ | cosmetic on C |
| [G](#g-facts) | facts | high (global) | ✓ | a second idiom for what `condition()` already does |
| [H](#h-a-with-named-predicates) | A, named predicates | high (local) | ✓ | **A as it should have been written** |
| [I](#i-h-with-rule-keywords) | H, `until=` / `only_if=` | high (local) | ✓ | H, if the keywords earn it |
| [J](#j-the-wizards-ladder) | behaviour on the member viewset, facts on the row | high (local) | ✓ — it *is* the wizard's rule | **the principled one** |

---

## 0. main: a viewset class per member

```python
class RefereesMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-referees"
    member_key = "supporting:referees"      # typed to match the hub's prefix + key
    hub_url_name = "apply-supporting"       # typed to match the hub's url_name
    wizard = referees

    @classmethod
    def blocked(cls, request, member, store):
        return not store.has_stash("contact")


class SupportingHubView(HubView):
    url_name = "apply-supporting"
    member_url_name = "apply-supporting-member"
    member_key = "supporting"
    hub_url_name = "apply"
    members = [Member("referees", RefereesMemberViewSet, title="Referees"), ...]
```

**Pros**

- The gate is a method on the member it gates. Read `RefereesMemberViewSet`
  and you know when it opens.
- Ordinary classes, ordinary methods, nothing generated.

**Cons**

- The same fact is declared twice and checked back together. Three strings
  on the member (`member_key`, `hub_url_name`, the nesting prefix) exist
  only to agree with the hub's declaration, and ~120 lines of drift checks
  existed only because they could disagree.
- The shape of the task list is invisible. Chapter 14 is nine classes and
  ten URL lines; you read it bottom-up.
- Mounting is the app's problem, with a silent footgun (the hub's
  `<slug:member>/` door swallows anything mounted beneath it).
- The cohesion is only apparent: `has_stash("contact")` is still a string
  naming a member declared somewhere else.

## A. the branch: builder with lambdas

```python
application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member("match_funding", match_funding, title="Match funding",
            hidden=lambda store: store.data.get("amount", 0) <= 10_000)
    .hub("supporting", supporting, title="Supporting information")
)
```

**Pros**

- One expression, read top-down, mounted once — the property the wizard
  API has.
- Nothing declared twice; nesting prefixes composed; no drift to check.
- Two hazards gone by construction: a member's bare URL *is* its door, and
  nothing can be mounted where the door would swallow it.

**Cons**

- The gate body is an implementation detail in a declaration:

  ```python
  hidden=lambda store: store.data.get("amount", 0) <= 10_000
  ```

  What the row means is "only above £10,000"; what it says is a dict read.
- The coupling is invisible. `amount` is written here —

  ```python
  def record_amount(store, bound_wizard):
      store.data["amount"] = int(...)          # in project's done=

  hidden=lambda store: store.data.get("amount", 0) <= 10_000   # in match_funding
  ```

  — two places, a string between them, nothing to say they are the same
  thing. That is `member_key` / `hub_url_name` again, one level down.
- `blocked` / `hidden` are the engine's words. `until` / `unless` would be
  the row's.
- Presentation (`.configure(template_name=…)`) and the root's hooks
  (`journey_done`) live off the value, on the viewset.

## B. class body

```python
class GrantApplication(Journey):
    template_name = "apply/hub.html"

    contact = Member(contact, title="Contact details", reopen="review", done=record_email)
    project = Member(project, title="Project", reopen="review", done=record_amount)
    match_funding = Member(match_funding, title="Match funding")
    supporting = SupportingInformation(title="Supporting information")

    def match_funding_hidden(self, store):
        return store.data.get("amount", 0) <= 10_000

    def journey_done(self, hub, store): ...
```

**Pros**

- The highest *local* cohesion of the eight. The gate is a named method
  beside the row it gates, on the same object as `journey_done` and the
  template — structure, hooks and presentation in one place.
- No lambdas, no quoted keys (the attribute name is the key), no
  `configure()`.
- Every Django developer already reads this: it is `Model`, `Form`,
  `Serializer`.

**Cons**

- Two idioms for the library's two central objects:

  ```python
  contact = Wizard().step(ApplicantForm, name="name").step(EmailForm, name="email")

  class GrantApplication(Journey):
      contact = Member(contact, ...)
  ```

  The chain reads like a flow because it *is* one; a class body reads like
  a schema. Both are fine; having both is the cost.
- Nesting is a nested class and a metaclass collects the rows — more
  machinery than `__init_subclass__` and a list.
- The fact/consumer coupling is unchanged. `match_funding_hidden` still
  reads `store.data["amount"]`, written by `record_amount` somewhere else.

## C. builder with named predicates

```python
    .member("match_funding", match_funding, title="Match funding",
            unless=amount_at_most(10_000))
    .member("referees", referees, title="Referees", until=finished("contact"))
    .member("documents", documents, title="Governing document",
            unless=answered("applying_as", "organisation"))
```

**Pros**

- Removes the lambda without changing the shape. Same engine, same
  `Rule = Callable[[JourneyStore], bool]` underneath — a predicate helper
  just returns one.
- `until=` / `unless=` say which gate it is in the row's own words, and
  `finished("contact")` says what is being waited for rather than how it
  is stored.

**Cons**

- The fact is still named by a string. `answered("applying_as",
  "organisation")` and `record_applying_as` agree by convention.
- Needs a small vocabulary (`finished`, `answered`, `amount_at_most`…),
  and the escape hatch back to a plain callable for anything it does not
  cover.
- The *writer* of the fact is still a `done=` callback elsewhere.

## D. the wizard owns its identity

```python
contact = (
    Wizard(name="contact", title="Contact details", reopen="review", done=record_email)
    .step(ApplicantForm, name="name")
    ...
)

application = Hub(
    setup,
    contact,
    project,
    Collection(budget_line, name="budget", title="Budget", min_items=1),
    match_funding.unless(amount_at_most(10_000)),
    supporting,
)
```

**Pros**

- The shortest hub of the eight: a list.
- `referees.until(finished("contact"))` is the most readable gate written
  in any sketch.
- A wizard is reusable under its own name anywhere.

**Cons**

- `Wizard()` grows `name`, `title`, `reopen`, `done` — none of which a
  wizard needs on its own. What a wizard *is* gets blurrier to make the
  hub shorter.
- Listing one wizard twice (the setup wizard is both the minting start and
  a member) needs a rename step.
- The gate moves onto the wizard but the fact it reads belongs to the
  journey. Cohesion moved, not gained.

## E. keyword rows

```python
application = Hub(
    contact=Member(contact, title="Contact details", reopen="review", done=record_email),
    match_funding=Member(match_funding, title="Match funding", hidden=amount_at_most(10_000)),
    supporting=Hub(
        referees=Member(referees, title="Referees", blocked=finished("contact")),
    ),
)
```

**Pros**

- No quoted keys; Python keywords are the keys and dict order is row order.
- Nesting is literally nested.

**Cons**

- Constructor calls do not chain, so it does not read as a flow — it reads
  as a config dict.
- Keys cannot contain hyphens.
- Otherwise exactly A's trade-offs.

## F. page vocabulary

```python
application = (
    TaskList()
    .section("contact", contact, title="Contact details", reopen="review", done=record_email)
    .add_another("budget", budget_line, title="Budget", min_items=1)
    .group("supporting", title="Supporting information", sections=(...))
)
```

**Pros**

- The declaration uses the words the person filling it in sees. The docs
  already say "the word on the page is yours — a task list says
  *sections*"; this makes the library say it too.
- `add_another` and `group` are self-describing in a way `collection` and
  `hub` are not.

**Cons**

- Cosmetic over C — the same coupling underneath.
- "Section" already means something in some of the apps this will serve.

## G. facts

```python
applying_as = Fact("applying_as")
amount = Fact("amount", int)

application = (
    Hub()
    .member("setup", setup, title="Applying as",
            records=applying_as.from_answer("applying_as", "applying_as"))
    .member("project", project, title="Project", reopen="review",
            records=amount.from_answer("project", "amount"))
    .member("match_funding", match_funding, title="Match funding",
            unless=amount <= 10_000)
    .hub("supporting", title="Supporting information", members=(
        Hub()
        .member("referees", referees, title="Referees", until=finished("contact"))
        .member("documents", documents, title="Governing document",
                unless=applying_as != "organisation")
    ))
)
```

**Pros**

- The writer and every reader hold the *same object*. Rename `amount` and
  both `records=` and `unless=` move with it; there is no string for them
  to disagree over. This is the only sketch that fixes the coupling rather
  than hiding it.
- No store access anywhere in the declaration. Compare A:

  ```python
  hidden=lambda store: store.data.get("amount", 0) <= 10_000    # A
  unless=amount <= 10_000                                       # G
  ```

- The common `done=` — read one answer, write it to `store.data` — becomes
  declarative (`records=`). Chapter 13 and 14's three `record_*` functions
  disappear.
- The outline the agent reads can list, per member, which facts it records
  and which gates depend on them, for free.

**Cons**

- A new concept, and operator overloading on `Fact` to make `amount <=
  10_000` return a rule.
- `done=` is still needed for real side effects (chapter 14's contact
  member writes the email *and* the submit uses it — `records=` covers the
  first, `journey_done` reads `email.read(store)` for the second).
- `finished("contact")` is a different kind of predicate — a stash, not a
  fact — so the vocabulary has two roots. Making it `contact.finished`
  pulls towards D.

## H. A with named predicates

```python
def record_amount(store, bound_wizard):
    step = bound_wizard.path.find_step(name="project")
    store.data["amount"] = int(step.form.cleaned_data["amount"])


def below_match_funding_threshold(store):
    return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


    .member("project", project, title="Project", reopen="review", done=record_amount)
    .member("match_funding", match_funding, title="Match funding",
            hidden=below_match_funding_threshold)
```

This is A's API unchanged — the difference is entirely in how the examples
are written, and it comes from looking at how the wizard already handles a
fact one step decides and another reacts to:

```python
.branch(condition(is_organisation, Wizard().step(OrganisationForm, ...)))
.switch(on_field("applying_as", "applying_as"), {...})
```

A named predicate, and a string naming the answer it reads. That is the
library's idiom already, and it is the shape of `record_amount` /
`below_match_funding_threshold` sitting together in one module.

**Pros**

- No engine change, no new concept, no vocabulary to learn.
- The writer and the reader are two named functions next to each other,
  each with a name, a docstring and a test that needs no hub — the
  cohesion `RefereesMemberViewSet.blocked` had on main, without the class.
- Reads exactly like `condition(is_organisation, ...)` one level up.
- Makes `Fact` (G) unnecessary: the coupling it fixes is the coupling
  `on_field("applying_as", ...)` already lives with.

**Cons**

- Still a string key between `record_amount` and its reader — by the same
  convention `on_field` uses. Accepted, not solved.
- `blocked=contact_not_finished` has the negation in the predicate name;
  see I.
- Whether the examples stay this way is a documentation discipline, not
  something the API enforces.

## I. H with rule keywords

```python
    .member("referees", referees, title="Referees", until=contact_finished)
    .member("documents", documents, title="Governing document", only_if=is_organisation)
    .member("match_funding", match_funding, title="Match funding",
            only_if=above_match_funding_threshold)
```

**Pros**

- `blocked=` / `hidden=` describe the row's *state*; `until=` / `only_if=`
  describe the *rule*, as `condition(...)` does. The keyword carries the
  negation, so predicates read positively: `until=contact_finished` rather
  than `blocked=contact_not_finished`.
- A rename on the builder and the `Member` record; the engine's
  `member_blocked` / `member_hidden` and the statuses stay as they are.

**Cons**

- The row's status is still called `blocked` in `MemberRow` and the
  template (`tag--blocked`), so the rule word and the state word differ.
  Arguably right — a rule and a state *are* different — but two words.
- `only_if` vs `unless` vs `when`: bikeshed with no obvious winner.
  `only_if` chosen here because it reads positively with `is_organisation`.

## J. the wizard's ladder

```python
# rung 1 — a wizard, wrapped by the library
.member("contact", contact, title="Contact details", reopen="review")

# rung 2 — your own member viewset, when it has something to do
class MatchFundingMember(MemberViewSet):
    wizard = match_funding

    @classmethod
    def hidden(cls, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD

.member("match_funding", MatchFundingMember, title="Match funding")
```

The wizard's one rule, applied to hubs without exception: the builder
carries *facts* and the thing in the slot carries *behaviour*.

| | wizard | hub |
| --- | --- | --- |
| rung 1 | `.step(ApplicantForm, name="name")` — a `Form`, wrapped in a `FormView` | `.member("contact", contact, title=…)` — a `Wizard`, wrapped in a `MemberViewSet` |
| rung 2 | `.step(ReviewStepView, name="review")` — your `FormView` with `get_initial`, `form_valid` | `.member("project", ProjectMember, title=…)` — your `MemberViewSet` with `run_done`, `blocked`, `hidden` |
| rung 3 | `WizardViewSet` — hooks for the run | `HubViewSet` — hooks for the page and the journey |

There is no `.step(Form, form_valid=…)`; by the same rule there is no
`.member(wizard, done=…)`.

**Pros**

- One principle for the whole library. Nothing about the hub changes
  between rung 1 and rung 2 — you hand it the richer object, as with a
  step.
- Behaviour has the home it had on main (`run_done`, `blocked`, `hidden`
  as methods on the member's viewset — named, documented, testable) with
  the string wiring gone: no `member_key`, no `hub_url_name`, no mount.
- The row-level callables (`done=`, `blocked=`, `hidden=`) go, and with
  them the lambda question, the naming question (H), the keyword question
  (I) and the `Fact` question (G). There is nothing to name because the
  hook already has a name.
- The escape hatch already on the branch (`wizard_bases`) *is* rung 2; the
  engine change is a deletion.

**Cons**

- A member that does something is a small class again — chapter 14 gets
  six of them. They are three lines each and carry no wiring, but the
  declaration no longer shows *that* a member is gated; you read the class.
- `blocked` / `hidden` as classmethods (the hub asks before any instance
  exists) is a slightly odd shape next to `run_done` as a method — the
  same split `begin` / `inspect` / `reopen` already have.
- `Collection(wizard)` needs the same rung 2 — `Collection(BudgetLineItem)`
  with an `ItemViewSet` subclass — which the branch already accepts.

---

## Where that leaves it

- **A → H** is no code change at all: rewrite the chapters, the scenario
  views and the docs' examples with named predicates beside the `record_*`
  functions that feed them, and never show a lambda.
- **H → I** is a keyword rename on `.member()` / `.collection()` / `.hub()`
  and the `Member` record. Engine untouched.
- **C** and **G** are what H looks like if you forget the wizard already
  has an idiom for this. C's vocabulary (`finished("contact")`) is
  lambda-avoidance in a hat; G's `Fact` is a second idiom for what
  `condition()` + `on_field()` already do.
- **B** stays on the table as the one genuine alternative, and its
  argument is "more Django", not "more fluent". If the wizard builder ever
  became a class body, both would converge here.

- **J** is the wizard's own rule applied to hubs, and it is a *deletion*
  from the branch: drop `done=` / `blocked=` / `hidden=` from the builder,
  keep the two rungs the engine already has.

Recommendation: **J**. H and I are what you do if the row-level callables
stay; J says they should not have been there, for the same reason
`.step()` has no `form_valid=`.
