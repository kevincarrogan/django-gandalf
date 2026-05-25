# Architecture

## Module map

| Module | Role |
|---|---|
| `gandalf/tree.py` | Immutable wizard tree — `Step` and `Branch` frozen dataclasses linked via `next` pointers; `build()` threads `next` from a flat declaration list |
| `gandalf/wizards.py` | Declarative builder — `Wizard` (fluent `.step()` / `.branch()` API) and `ConfiguredWizard` (post-`.configure()`, holds `storage_class` and fully-configured tree) |
| `gandalf/form_views.py` | `form_view_factory()` — generates a `FormView` subclass from a plain `Form` class |
| `gandalf/storage.py` | `SessionStorage` (JSON persistence to `request.session`) and `WizardState` (lockstep walker that zips the wizard tree with the stored state list) |
| `gandalf/runtime.py` | `BoundWizard` — request-bound runtime; drives `replay()` and `submit()`; `_BranchView` exposes `get_submissions()` to branch predicates |
| `gandalf/viewsets.py` | `WizardViewSet` — Django `View` subclass; HTTP boundary for GET and POST |

---

## Object graph for one request

The diagram below shows the objects created and how they reference each other during a single request.

```mermaid
graph LR
    subgraph HTTP boundary
        WVS["WizardViewSet\n(view instance)"]
    end

    subgraph Declaration layer
        CW["ConfiguredWizard\n(class attribute on WizardViewSet)"]
        S1["tree.Step\n(AccountTypeForm)"]
        BR["tree.Branch\n(arms + default)"]
        S2a["tree.Step\n(BusinessDetailsForm)"]
        S2b["tree.Step\n(PersonalDetailsForm)"]
        S3["tree.Step\n(ReviewForm)"]
        FV["GeneratedFormView\n(from form_view_factory)"]
    end

    subgraph Request-bound layer
        BW["BoundWizard"]
        SS["SessionStorage"]
        WS["WizardState"]
    end

    Session[("request.session\n[gandalf_runs][run_id]")]

    WVS -->|".wizard"| CW
    CW -->|".tree"| S1
    S1 -->|".next"| BR
    BR -->|"arms[0][1]"| S2a
    BR -->|".default"| S2b
    BR -->|".next"| S3
    S1 -->|".form_view"| FV
    S2a -->|".form_view"| FV
    S2b -->|".form_view"| FV
    S3 -->|".form_view"| FV

    WVS -->|"get_bound_wizard(request)"| BW
    BW -->|".wizard"| CW
    BW -->|".storage"| SS
    BW -->|"WizardState(entries)"| WS
    SS -->|"reads/writes"| Session
    WS -->|"entries from"| Session
```

`form_view_factory()` produces one `GeneratedFormView` class per `Step`, but the diagram collapses them to a single node for clarity; each `Step.form_view` points to its own generated class.

---

## Request lifecycle

### GET — first visit (no `run_id`)

```mermaid
sequenceDiagram
    participant Django
    participant WVS as WizardViewSet
    participant CW as ConfiguredWizard
    participant BW as BoundWizard
    participant SS as SessionStorage

    Django->>WVS: GET /wizard/  (run_id=None)
    WVS->>CW: configure_wizard() → ConfiguredWizard
    Note over CW: configure() walks tree recursively,<br/>calling form_view_factory() on each Step
    WVS->>BW: get_bound_wizard(request)
    WVS->>BW: initialise()
    BW->>SS: initialise_run() → UUID run_id
    SS-->>BW: run_id
    WVS-->>Django: redirect(wizard_url(run_id))
```

### GET — returning visit (with `run_id`)

```mermaid
sequenceDiagram
    participant Django
    participant WVS as WizardViewSet
    participant BW as BoundWizard
    participant SS as SessionStorage
    participant WS as WizardState
    participant FV as GeneratedFormView

    Django->>WVS: GET /wizard/<run_id>/
    WVS->>BW: get_bound_wizard(request)
    WVS->>BW: retrieve(run_id)
    BW->>SS: retrieve_run(run_id)
    WVS->>BW: replay()
    BW->>SS: get_state(run_id) → entries
    BW->>WS: WizardState(entries).walk(tree, select_arm)
    loop for each (step, stored) from walk
        alt stored is not None
            BW->>FV: as_view()(POST, stored_data)
            FV-->>BW: 3xx valid → continue
        else stored is None
            BW->>FV: as_view()(GET)
            FV-->>BW: 200 rendered step
        end
    end
    BW-->>WVS: rendered response
    WVS-->>Django: response
```

### POST — step submission

```mermaid
sequenceDiagram
    participant Django
    participant WVS as WizardViewSet
    participant BW as BoundWizard
    participant SS as SessionStorage
    participant WS as WizardState
    participant FV as GeneratedFormView

    Django->>WVS: POST /wizard/<run_id>/
    WVS->>BW: get_bound_wizard(request)
    WVS->>BW: retrieve(run_id)
    BW->>SS: retrieve_run(run_id)
    WVS->>BW: submit(request.POST.dict())
    BW->>SS: get_state(run_id) → old entries
    BW->>BW: _rebuild_at(tree, old_entries, submission)
    Note over BW: Walks tree + old entries in lockstep.<br/>Replays each stored submission through its FormView<br/>to validate. Appends new submission at the first empty slot.
    BW->>FV: as_view()(POST, stored) [validate old step]
    FV-->>BW: 3xx valid → keep, continue
    BW->>SS: set_state(run_id, new_entries)
    WVS->>BW: replay()
    BW->>SS: get_state(run_id) → new entries
    BW->>WS: WizardState(entries).walk(tree, select_arm)
    loop replay to find next step
        BW->>FV: as_view()(POST, stored) [replay old]
        FV-->>BW: 3xx valid → continue
    end
    BW->>FV: as_view()(GET) [first unstored step]
    FV-->>BW: 200 rendered step
    BW-->>WVS: response
    WVS-->>Django: response
```

---

## State storage shape

State is stored in `request.session["gandalf_runs"][run_id]["state"]` as a list that **mirrors the shape of the wizard tree**. Each entry is one of:

```python
{"step": {…form_data…}}         # a tree.Step node — holds submitted form data
{"branch": [{…sub-entries…}]}   # a tree.Branch node — sub-entries record the taken arm
```

Branch decisions are **never persisted**. On every replay `WizardState` re-derives which arm was taken by re-evaluating the branch predicate against the submissions accumulated so far.

### Example — branching wizard state after three steps

```python
# wizard declaration
from django import forms
from gandalf.wizards import Wizard, condition

wizard = (
    Wizard()
    .step(AccountTypeForm)
    .branch(
        condition(is_business, Wizard().step(BusinessDetailsForm)),
        default=Wizard().step(PersonalDetailsForm),
    )
    .step(ReviewForm)
).configure(template_name="wizard/step.html")
```

After the user completes all three steps via the business arm:

```python
[
    {"step": {"account_type": "business"}},
    {"branch": [{"step": {"business_name": "Acme Ltd"}}]},
    {"step": {"confirmed": True}},
]
```

---

## Branch arm selection

Branch predicates receive a thin request-like object whose `.wizard.get_submissions()` returns the list of form-data dicts submitted so far in the current run.

```python
from gandalf.wizards import Wizard, condition

def is_business(request):
    return request.wizard.get_submissions()[0]["account_type"] == "business"

wizard = (
    Wizard()
    .step(AccountTypeForm)
    .branch(
        condition(is_business, Wizard().step(BusinessDetailsForm)),
        default=Wizard().step(PersonalDetailsForm),
    )
    .step(ReviewForm)
)
```

`BoundWizard._select_branch_arm()` constructs the `_BranchView` wrapper and evaluates each arm predicate in declaration order, returning the first matching arm's subtree or `Branch.default`.
