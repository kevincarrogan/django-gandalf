# Driver

`gandalf.driver` — drive a wizard run from Python: schemas in, submissions
in, answers out. No browser, no test client, no HTML.

```python
from gandalf.driver import (
    CheckResult,
    ConfirmationRequired,
    Placement,
    PrefillResult,
    RunComplete,
    RunDriver,
    RunIncomplete,
    StepDescription,
    SubmitResult,
    field_json_schema,
    form_json_schema,
    outline_steps,
)
```

The module imports nothing beyond Django and gandalf, and is never imported
unless you ask for it. Nothing in it is a second implementation: every
operation is the one `WizardViewSet` performs for a request, so branching,
expansion, escapes, dormant memory and re-validation behave identically
whichever door a run is reached through. A run a driver fills is an
ordinary run — the same `run_id`, the same stored state, the same walk — and
the two doors can be used on the same run one after the other.

---

## Reference

### `RunDriver(view, run, *, may_finish=None)`

One wizard run, driven as data. Construct it through `begin()`,
`resume()` or `outline_for()` rather than directly.

**Attributes**

- `view` — the `WizardViewSet` instance the run is driven through.
- `run` — the run's [`Run`](run.md). Everything
  the runtime offers is reachable here: `run.entry_url(step)` for
  the URL to hand a person, `run.stash()`, `run.path`.
- `run_id` (property) — `run.run_id`.
- `metadata` (property) — the run's [`RunMetadata`](run-metadata.md) bag,
  the same one `run_started()`, step views and `done()` read and write. A
  fact about the *run*; what each *placement* claimed about itself is in
  `placements()`.
- `may_finish` — whether this driver may fire `done()`. Class attribute,
  default `False`; set per driver with `may_finish=True` or on a subclass.
- `default_metadata` — class attribute, `{"unattended": True}`. Recorded
  against every placement this driver makes unless `submit()` is given
  `metadata=`.

### `RunDriver.begin(viewset_class, *, context=None, actor=None, session=None, may_finish=None, **url_kwargs)`

A driver over a fresh run of `viewset_class`'s wizard. The run is minted
first and the wizard resolved against it (`WizardViewSet.begin_for()`), so
`run_started()` fires and a dynamic `get_wizard()` sees the run.

**Parameters**

- `viewset_class` — a `WizardViewSet` subclass.
- `context` — a `WizardContext` to use as it stands. `url_kwargs` named
  alongside it still apply and win over the context's own, so a context
  held for a conversation can address one add-another item and then the
  next.
- `actor` — whoever the run is for; what a durable storage scopes runs by.
  Ignored when `context` is given.
- `session` — a session to share with a browser or another driver (any
  object satisfying `WizardSession`: Django's `SessionBase` does). Without
  one, an in-memory `gandalf.context.Session` is created and the run lives
  only as long as the context. Ignored when `context` is given.
- `may_finish` — sets the driver's `may_finish`; `None` leaves the class
  default.
- `**url_kwargs` — mount-prefix kwargs (a tenant slug, an add-another item
  id), forwarded to the viewset exactly as URL kwargs would be.

**Returns** a `RunDriver`.

### `RunDriver.resume(viewset_class, run_id, *, context=None, actor=None, session=None, may_finish=None, **url_kwargs)`

A driver over an existing run (`WizardViewSet.inspect_driven_for()`): the
door is asked, the run retrieved, then the wizard resolved against it.
`run_started()` does not fire. Parameters as `begin()`.

**Raises** `RunNotFound` for a run this storage does not hold, and
`DoorRefused` for a section shut since the run started — its prerequisite
withdrawn, its journey submitted. The door comes first, which is what a
browser returning to the same section gets.

**Raises** `gandalf.storage.RunNotFound` for a run the storage does not
hold — pass the `session` the run lives in, or the `actor` a durable
storage scopes it to.

### `RunDriver.outline_for(viewset_class, *, context=None, actor=None, session=None, **url_kwargs)`

The shape of `viewset_class`'s wizard without starting a run
(`WizardViewSet.resolve_for()`). Nothing is left behind by asking, which
matters to a caller describing several wizards to choose between them. A
dynamic `get_wizard()` resolves with no stored state, so it describes
itself as it would begin.

**Returns** the same list `outline()` returns.

### `describe(*, json_safe=False)`

Where the run is, as data a caller can act on.

**Returns** a `StepDescription`. Once the run is complete, `step` and
`schema` are `None`, `errors` is `{}` and `complete` is `True`.

**Caveats** — `json_safe` is `answers()`'s flag, taken here so a caller
serialising the whole description does not read the answers a second time.
A description costs one walk.

### `submit(data, *, files=None, step=None, metadata=None)`

Place `data` at the cursor step, or at the step `step` names.

**Parameters**

- `data` — an `Answer`: bare field names to values, or a list of one such
  mapping per row for a step that repeats its fields. Values are reduced to
  what a browser would have posted: the cleaned values `answers()` hands
  back (`datetime.date`, `Decimal`, …) are converted through
  `DjangoJSONEncoder` first, so a step's answers can be read, changed and
  submitted straight back — rows included. A value the encoder cannot
  render raises `TypeError` here rather than when state is written.

  Turning an answer into a submission is the step view's to do
  ([`get_submission()`](step-views.md)), so any form prefix is applied for
  you, and a repeated step's management form is rendered for you. The shape
  a browser posts is still taken as it is: rows are the addition, not the
  replacement.
- `files` — uploads keyed by form field name, as `django.core.files.uploadedfile.UploadedFile`
  instances, placed exactly as a multipart POST would place them. A file
  belongs here and not in `data`, which is stored as JSON. Omitting
  `files` says nothing about files: a step re-answered without them keeps
  the upload it has.
- `step` — the name of a step to answer instead of the cursor's. The walk
  re-routes from there and keeps every later answer that still holds.
  Works for a step grown by `.expand()` too, though its form prefix (if
  any) cannot be looked up in the static tree.
- `metadata` — recorded against the placement, read back from
  `placements()`, and handed to the wizard's [observer](observers.md).
  Defaults to `default_metadata` (`{"unattended": True}`); pass your own
  to describe a placement made on somebody else's behalf, or `{}` to
  record nothing.

**Returns** a `SubmitResult`.

**Raises**

- `RunComplete` — the cursor is past the last step; call `finish()`.
- `gandalf.runtime.StepNotFound` — `step` names a step the run cannot
  reach (an unselected branch arm, a step past a gap, a name that exists
  nowhere). Uploads saved for the attempt are deleted again.
- `ImproperlyConfigured` — the step raised bare `Escape` rather than a
  subclass.

**Escapes.** An escape raised by the step's validation is settled the way
the viewset settles it, minus the redirect: `Obliterate` destroys the run,
`Advance` stores the answer and moves on, `Park` stores nothing and
deletes the uploads it brought. The result has `status="escaped"`,
`escape` set to `"park"`, `"advance"` or `"obliterate"`, and
`next_step=None`; ask `describe()` where the run now is.

**Dynamic wizards.** After persisting, the wizard is re-resolved; only if
`get_wizard()` returns a different declaration is the run walked again to
find the cursor, so a static wizard pays one walk per submission.

### `prefill(answers)`

Place as many of `answers` (step name → submission dict) as the tree will
take, and report the residue. The cursor step's answer is submitted for as
long as the bag holds one, so a placement that selects a branch arm or
grows an expansion lets the pass keep consuming answers for the steps it
just revealed. Stops at the first step the bag cannot answer, the first
rejected answer, or an escape.

**Returns** a `PrefillResult`. Each placement is a `submit()` call with the
driver's default metadata; a bag cannot carry files.

### `check(answers)`

Judge `answers` (step name → submission dict) against the wizard without
placing any of them. Nothing is walked and nothing is stored: each
candidate is bound to its own step's form — composed through the step
view, so the same overrides apply — and validated alone.

**Returns** a `CheckResult`.

**Caveats**

- `ok` is not a promise. A standalone form knows nothing about the walk;
  the real placement re-proves it.
- `missing` lists only steps the run will certainly reach — steps inside
  any branch arm or default are left out, and so are steps already
  answered. An expansion has no static subtree, so the steps it will grow
  cannot be checked or listed at all.
- An escape raised while validating a candidate is reported under
  `unchecked` and never acted on. So is a form that cannot be built from
  the answers available yet.
- A step whose view declares
  [`consumes_what_it_checks`](step-views.md) is reported under `unchecked`
  without being validated at all. Judging it would *perform* its check —
  spending the one-time code it was asked about, and recording no
  [proof](proofs.md) of having done so, because a check places nothing. The
  real placement would then fail on an answer that was right when it was
  offered. A check is a question; this is the step where asking would have
  been an act.
- What a candidate refused is the step view's to say, exactly as it is for
  [`submit()`](#submitdata--filesnone-stepnone-metadatanone) — so a
  repeated step's rows are keyed by row and field, and a valid formset
  reads as `ok` rather than as a refusal (its `errors` is truthy when every
  row is valid, which is why the view is asked rather than the object).

### `answers(*, json_safe=False)`

Every answered step's `cleaned_data`, keyed by step name in walk order.

**Returns** `dict[str, Answer]` — each step's answer as its view reads it
back, which is a mapping of field name to value, or a list of one such
mapping per row for a step that repeats its fields. With `json_safe=False`
the values are Python objects — a `DateField` gives a `datetime.date` — and
feed straight back into `submit()`. With `json_safe=True` they are rendered as
JSON holds them (ISO dates, strings for decimals and UUIDs), and still feed
back into `submit()`. It is the *cleaned* answer either way: a ticked
checkbox is `True`, not `"on"`. The one exception is an uploaded file,
which `json_safe=True` renders as its stored `FileRef`; `submit()` cannot
take a file back through `data` in either form.

### `placements(*, json_safe=False)`

Every answered step, keyed by step name in walk order, as a `Placement` —
the answers, the files stored with them, and what the placement recorded
about itself, all from one walk. `answers()` is this with the other two
dropped. A step nobody has answered has no entry at all, which is
different from one answered by somebody who recorded nothing.

`json_safe` applies to the answers and to the metadata.

### `open_file(ref)`

Open a file stored with a placement.

**Parameters** — `ref`, a `FileRef` from `placements()[step].files[field]`.

**Returns** a `gandalf.file_storage.StoredUpload`: a Django `UploadedFile`
that answers `name`, `size`, `content_type` and `charset` from the ref and
reads the bytes from the backend only when asked. `ref["size"]` is there
before the bytes are, so a caller that must not read a large file can
decline without opening it.

### `outline()`

The wizard's declared shape as data, before any answers exist —
`ConfiguredWizard.outline()` with each step's declaration swapped for a
JSON Schema of its form.

**Returns** a list of entries, each with a `kind`:

| `kind` | Keys | Notes |
| --- | --- | --- |
| `step` | `step`, `schema` | `schema` is `None` for a step whose view cannot compose its form yet (it reads answers the run does not hold); `describe()` supplies it once the walk reaches the step. |
| `branch` | `arms`, `default` | Every arm is shown, since which runs depends on answers. Each arm has `when` (the predicate's name), `description` (its docstring, or `None`) and `steps`. `default` is a list of entries. |
| `switch` | `decided_by`, `description`, `cases`, `default`, `source` | `cases` are named outcomes, each `{"case": value, "steps": [...]}`. `source` — `{"step": ..., "field": ...}` — is present only when the selector is an `on_field`. |
| `expand` | — | A marker. The steps an expansion grows do not exist until the answer that shapes them does. |

A dynamic `get_wizard()` is outlined as currently resolved. Add-another lists
are not steps and do not appear.

### `finish()`

Fire `done()` and retire the run — `WizardViewSet.finish()`, guarded
twice.

**Returns** whatever `done()` returned (an `HttpResponseBase`, possibly an
unrendered `TemplateResponse`).

**Raises**

- `RunIncomplete` — the cursor still sits at a step. Checked first.
- `ConfirmationRequired` — `may_finish` is `False`.

`done()` is where the irreversible things live, and a driver is the
unattended path by definition, so concluding a run is opt-in per driver.
The alternative is to hand the run to a person:
`driver.run.entry_url("review")` is the wizard's own step URL, and
their first page load walks the same answers the same way.

### `StepDescription`

Frozen dataclass.

| Field | Type | Meaning |
| --- | --- | --- |
| `step` | `str \| None` | the current step's name; `None` once complete |
| `schema` | `dict \| None` | JSON Schema of its form; `None` once complete |
| `answers` | `dict[str, Answer]` | `answers()` |
| `errors` | `dict[str, list[dict]]` | field errors of the last submission made *through this driver* (`{}` when it validated, or after an escape) |
| `complete` | `bool` | |

### `SubmitResult`

Frozen dataclass.

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | `"advanced" \| "invalid" \| "complete" \| "escaped"` | see below |
| `errors` | `dict[str, list[dict]]` | `form.errors.get_json_data()` — field name to a list of `{"message", "code"}`; `{}` unless `invalid` |
| `next_step` | `str \| None` | the step now at the cursor |
| `escape` | `str \| None` | `"park"`, `"advance"` or `"obliterate"` when `escaped`; else `None` |

| `status` | What happened |
| --- | --- |
| `advanced` | stored, satisfied; the run moved on to `next_step` |
| `invalid` | stored but not satisfied; the cursor stays at this step and `errors` says why |
| `complete` | stored, and it was the last answer needed — call `finish()`; `next_step` is `None` |
| `escaped` | the step raised an escape; the run is wherever the escape's disposition left it |

An `invalid` submission is kept, exactly as over HTTP, so `describe()`
re-reports its errors until a valid answer replaces it.

### `PrefillResult`

Frozen dataclass.

| Field | Type | Meaning |
| --- | --- | --- |
| `placed` | `list[str]` | steps filled, in walk order |
| `errors` | `dict[str, Errors]` | the rejected answer the pass stopped at, if any |
| `unused` | `list[str]` | answers the walk never asked for: a dormant arm, a step past a gap, an already complete run |
| `next_step` | `str \| None` | where the run stands afterwards |
| `complete` | `bool` | |
| `escape` | `str \| None` | an escape a placed answer raised |

### `CheckResult`

Frozen dataclass.

| Field | Type | Meaning |
| --- | --- | --- |
| `ok` | `list[str]` | validated alone; nothing to ask about |
| `invalid` | `dict[str, Errors]` | field errors per step |
| `missing` | `list[str]` | unconditional, unanswered steps with no answer in the bag |
| `unchecked` | `dict[str, str]` | steps that could not be judged, and why |
| `unknown` | `list[str]` | names matching no declared step — a typo, or a step an expansion has not grown |

### `Placement`

Frozen dataclass: `answers` (cleaned data, as `Answer`), `files`
(`dict[str, FileRef]`), `metadata` (`dict`; `{}` when the placement recorded
nothing).

### `Answer`

`dict[str, Any] | list[dict[str, Any]]` — one step's answer as its view
reads it back. A mapping of field name to cleaned value for a form; a list
of one such mapping per row for a step that repeats its fields, which
declares none of its own. It is the same shape in both directions:
`answers()` hands it out and `submit()`, `prefill()` and `check()` take it
straight back.

### `RunComplete`, `RunIncomplete`, `ConfirmationRequired`

Plain `Exception` subclasses. `RunComplete` from `submit()` on a finished
walk; `RunIncomplete` and `ConfirmationRequired` from `finish()`, in that
order of precedence.

### `form_json_schema(form)`

Describe a Django form as a JSON Schema object: `type: "object"`,
`properties` keyed by bare field name, `required` listing the fields Django
would reject an empty answer for (omitted when empty), and
`additionalProperties: false` so a misspelled field is caught before
validation is.

### `field_json_schema(field)`

Describe one form field as a JSON Schema property. The mapping is
submission-shaped — what to *send*, not what `cleaned_data` holds.

| Field | Schema |
| --- | --- |
| `MultipleChoiceField`, `ModelMultipleChoiceField` | `{"type": "array", "items": {"type": "string", "enum": [...]}}`; `minItems: 1` when required |
| `ChoiceField` (and model/typed subclasses) | `{"type": "string", "enum": [...]}`; grouped choices are flattened; the empty prompt choice is dropped when required and kept when optional; [capped](#long-lists-of-choices) at `MAX_DESCRIBED_CHOICES` |
| `NullBooleanField` | `{"type": ["boolean", "null"]}` |
| `BooleanField` | `{"type": "boolean"}`; `const: true` when required |
| `FloatField`, `DecimalField` | `{"type": "number"}` with `minimum`/`maximum` |
| `IntegerField` | `{"type": "integer"}` with `minimum`/`maximum` |
| `DateTimeField` | `{"type": "string", "format": "date-time"}` |
| `DateField` | `{"type": "string", "format": "date"}` |
| `TimeField` | `{"type": "string", "format": "time"}` |
| `EmailField` | `{"type": "string", "format": "email"}` plus length bounds |
| `URLField` | `{"type": "string", "format": "uri"}` plus length bounds |
| `CharField` | `{"type": "string"}` with `maxLength`/`minLength` |
| `FileField`, `ImageField` | `{"type": "string", "format": "binary"}` — `format: binary` is the only part to branch on |
| anything else | `{"type": "string"}` |

**A field can describe itself.** The table above is what Gandalf recognises;
a project's own field is by definition not on it, and would be called a bare
string with an `x-note` saying the mapping gave up. Give the field a
`json_schema()` and it is asked instead of guessed at — once, for every step
that asks it:

```python
from django import forms


class MoneyField(forms.DecimalField):
    def json_schema(self):
        return {"type": "number", "minimum": 0, "x-unit": "GBP"}
```

It replaces the type-shaped half only: `title`, `description` and the rest
are added around it either way, so a field cannot lose its label by
answering, and the "not supported" note is dropped because the note
apologises for not knowing. It is consulted *before* the table, so a field
may correct a description it would otherwise have been given rather than
only supply a missing one — a `CharField` subclass can carry a `pattern`
nothing could have derived, and a `pattern` it states is not overwritten by
one read off a `RegexValidator`.

The step view's [`get_answer_schema()`](step-views.md) is the same idea one
level up, for when the whole step is not form-shaped. Reach for the field
when one field is unusual, and the view when the object holding them is.

#### Long lists of choices

A description travels to a model, and a reference table does not belong in
a prompt. A choice field's values are read one past
`MAX_DESCRIBED_CHOICES` (50) and no further, so describing a step never
enumerates a queryset — `ModelChoiceField.choices` is one in disguise, and
`RunDriver.outline_for()` describes every declared step of the wizard.

Past the cap the enum is dropped rather than cut short, because a caller
reads `enum` as the whole list and would rule out every value below the
cut:

```json
{
  "type": "string",
  "title": "Application",
  "x-choices-omitted": true,
  "x-note": "More than 50 choices, so they are not listed here. Send the value the form expects; it is checked against the real list when the answer is submitted."
}
```

`x-choices-omitted` is the half to branch on; the note beside it is prose.
For a `MultipleChoiceField` both the enum and its absence live on `items`,
which is what the values belong to.

A field whose values are worth listing however many there are says so
itself, and is asked before the cap applies:

```python
from django import forms


class ApplicationField(forms.ModelChoiceField):
    def json_schema(self):
        pairs = [(application.pk, str(application)) for application in self.queryset]
        legend = ", ".join(f"{value} ({label})" for value, label in pairs)
        return {
            "type": "string",
            "enum": [str(value) for value, _ in pairs],
            "x-note": f"Choices: {legend}.",
        }
```

That the note is written out here is the point of the hatch rather than an
oversight: the library's own `x-note` apologises for not knowing, so it is
dropped when a field answers, and a field listing its own values says what
they are called.

On every property: `title` from `label`, `description` from `help_text`
(only when set), `pattern` from the first `RegexValidator` on a string
field that has no `format`, and `x-note` for a library remark — the choice
legend (`Choices: value (label), …`) or the reason there is none, the file
instruction, or
`<FieldType> is not supported by the schema mapping; submit its raw form
value`. Numeric bounds are the tightest of `min_value`/`max_value` and any
`MinValueValidator`/`MaxValueValidator`; a callable `limit_value` is left
out.

### `outline_steps(entries)`

Yield every `step` entry an outline holds, however deeply an arm or case
buries it, in declared order (arms before what follows them). Yields the
entries, not their names, since the question is usually about the `schema`
beside the name. An `expand` entry yields nothing. A plain function over
plain data, so it works on an outline that has been through JSON.

---

## Usage

### Filling a run and finishing it

```python
from gandalf.driver import RunDriver

from applications.views import GrantApplicationViewSet

driver = RunDriver.begin(GrantApplicationViewSet, may_finish=True)

driver.describe().schema           # JSON Schema for the current step's form
driver.submit({"full_name": "Ada Lovelace"})
result = driver.submit({"email": "ada@example.org"})
if result.status == "complete":
    response = driver.finish()     # fires done() exactly once
```

### Recovering from a rejected answer, and editing an earlier one

```python
rejected = driver.submit({"email": "not-an-email"})
rejected.status                    # "invalid"
rejected.errors["email"][0]["code"]  # "invalid"

driver.submit({"email": "ada@example.org"})

# Re-answer the step that chose the branch; the walk re-routes from it.
driver.submit({"applying_as": "organisation"}, step="applying-as")
driver.describe().step             # "organisation"
```

### Prefilling from a profile and handing the rest to a person

```python
from gandalf.driver import RunDriver

from applications.views import GrantApplicationViewSet

driver = RunDriver.begin(GrantApplicationViewSet, actor=request.user)

report = driver.check(profile_answers)
if report.invalid or report.missing:
    ...                            # ask for everything wrong or absent, once

result = driver.prefill(profile_answers)
result.placed                      # ["organisation", "trustees", "budget"]
result.unused                      # answers the route never asked for

# No may_finish: the person confirms in the browser.
review_url = driver.run.entry_url("review")
```

The run is the same run the browser opens. With a durable storage scoped
by `actor`, `retrieve_run` raising `RunNotFound` for someone else's run is
the authorisation.

### Sharing a browser session

```python
from django.contrib.sessions.backends.db import SessionStore

from gandalf.driver import RunDriver

session = SessionStore(session_key=key)
driver = RunDriver.resume(GrantApplicationViewSet, run_id, session=session)
```

A driver given a session has no request and therefore no
`SessionMiddleware` to save it, so `WizardContext.persist()` calls
`session.save()` after every write. That needs a server-side
`SESSION_ENGINE` (`db`, `cache`, `cached_db`, `file`); `signed_cookies`
can be read but not written back.

### Placing and reading a file

```python
from django.core.files.uploadedfile import SimpleUploadedFile

driver.submit({}, files={"accounts": SimpleUploadedFile("accounts.pdf", data)})

ref = driver.placements()["accounts"].files["accounts"]
ref["size"]                        # known before the bytes are read
with driver.open_file(ref) as upload:
    upload.read()
```

### Telling the driver's answers from a person's

```python
def is_the_drivers_own(driver, step):
    placement = driver.placements().get(step)
    return placement is not None and bool(placement.metadata.get("unattended"))

driver.submit({"full_name": "Grace Hopper"}, step="applicant",
              metadata={"placed_by": "person"})
```

The library refuses no edit — whose answer this is is a question about
your domain — so a "never overwrite what a person typed" rule is yours to
write, and this is the whole recipe.

### An agent on top

`gandalf.contrib.agent` (`pip install django-gandalf[agent]`) is a
pydantic-ai toolset over this driver — `start_run`, `resume_run`, `get_run`,
`get_outline`, `check_answers`, `prefill`, `submit_step`, `edit_step`,
`attach_document`, `handoff` — plus the instructions that go with it and an AG-UI endpoint
served from Django. It names no model provider and has no tool that
concludes a run: the person confirms. See [Agent](agent.md).

---

## Troubleshooting

### `finish()` raises `ConfirmationRequired` although `submit()` said `"complete"`

The default. Construct the driver with `may_finish=True`, or subclass with
`may_finish = True` for a caller that is always allowed (an import
command). Otherwise hand the person `run.entry_url(...)` and let
them confirm.

### `submit()` raises `StepNotFound` for a step that is in the wizard

Reaching a step is the authorisation. The step is behind a branch arm the
current answers do not select, past a step still unanswered, or inside an
expansion that has not grown yet. Answer what comes before it first; the
uploads sent with the refused submission have already been deleted.

### The run I started from a management command is gone on the next request

Without `session=` the driver uses an in-memory session that dies with the
context. Pass the person's session (server-side backend) or use a durable
storage and `actor=`. With `signed_cookies`, `session.save()` has nowhere
to write.

### `TypeError: Object of type … is not JSON serializable` from `submit()`

Submissions are stored as JSON. `DjangoJSONEncoder` handles dates, times,
decimals and UUIDs; anything else must be reduced to what a browser would
post before it is passed in. A file goes in `files=`, never in `data`.

### `describe(json_safe=True)` shows a dict where a file was uploaded

That is the stored `FileRef` — an open file is not JSON. Use
`placements()[step].files` and `open_file(ref)` to reach the bytes.

### `outline()` gives `schema: None` for one step

The step's view composes its form from answers the run does not hold yet,
so the form cannot be built. `describe()` supplies the schema once the walk
reaches that step.

### `check()` returns `unknown` for steps an expansion will grow

An expansion has no static subtree. The steps exist only after the answer
that shapes them is placed; `prefill()` does cross that boundary, because
it places one answer at a time and reads the tree again.

---

**Learn:** [Chapter 16 — Outline, observers and the driver](../learn/16-outline-observers-and-the-driver.md) · **Related:** [Agent](agent.md), [`Run`](run.md), [`WizardViewSet`](viewsets.md), [Run metadata](run-metadata.md), [Observers](observers.md), [File uploads](file-uploads.md), [Storage](storage.md), [Testing](testing.md)
