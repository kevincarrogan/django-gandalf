# django-gandalf examples

A guided tour of `django-gandalf`'s feature surface. Every recipe runs
against the bundled test app, and every recipe is also a functional test
that asserts the same behavior — so the recipes can't drift from reality
without breaking the suite.

## Running the gallery

```
just examples
```

Boots a Django dev server at <http://127.0.0.1:8000/>. The index page
groups every wizard by category; each recipe below tells you which URL
to visit and walks you through the inputs.

For deeper internals — the cursor walker, state shape, edit semantics —
see [ARCHITECTURE.md](ARCHITECTURE.md). For the API surface up front,
see [README.md](README.md).

---

## 1. Merge a two-step linear wizard into one payload

**What this shows:** the simplest interesting flow — two steps, then a
`done()` that uses `MergeCleanedData` to fold `cleaned_data` from every
visited step into a single dict. This is the shape most real wizards
start from.

**Run it:**
1. `just examples`
2. Open <http://127.0.0.1:8000/merged-payload-wizard/>
3. Enter a name (e.g. `Frodo`), submit.
4. Enter an email (e.g. `frodo@example.com`), submit.
5. Final page shows `completed name=Frodo email=frodo@example.com`.

**The code:**
- Viewset — `tests/testapp/views.py::MergedPayloadLinearWizardViewSet`
- Forms — `tests/testapp/forms.py::FirstStepForm`, `SecondStepForm`
- Functional test — `tests/functional/test_wizard_viewset.py::test_linear_wizard_done_can_merge_cleaned_data_across_path`

```python
from django.http import HttpResponse
from django.urls import reverse
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard

from .forms import FirstStepForm, SecondStepForm


class MergedPayloadLinearWizardViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(FirstStepForm).step(SecondStepForm)

    def get_wizard_url(self, run_id):
        return reverse("merged-payload-wizard-run", kwargs={"run_id": run_id})

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"completed name={payload['name']} email={payload['email']}"
        )
```

**Why it works this way:** `bound_wizard.path` is the chain of completed
steps in execution order. `MergeCleanedData` is a `tree.Reducer` that
folds each step's `cleaned_data` together (last-write-wins). Subclass
it or write your own `Reducer` for a different policy — see recipe 6.

---

## 2. Branch on a form choice and merge both arms back into one payload

**What this shows:** the headline feature — branching as an explicit
tree, with each arm contributing its own cleaned data. `done()` doesn't
need to know which arm was taken; `MergeCleanedData` walks whichever
path was actually executed.

**Run it:**
1. Open <http://127.0.0.1:8000/branching-merged-payload-wizard/>
2. Choose `Business`, submit.
3. Enter a business name (e.g. `Shire LLC`), submit.
4. Enter an email (e.g. `frodo@shire.example`), submit.
5. Confirm the review checkbox, submit.
6. Final page shows
   `account_type=business business_name=Shire LLC email=frodo@shire.example confirmed=True`.

Try it again with `Personal` at step 1 — you go through a one-step arm
(`preferred_name`) instead of the two-step business arm, and the merged
payload changes shape accordingly.

**The code:**
- Viewset — `tests/testapp/views.py::BranchingMergedPayloadWizardViewSet`
- Branch predicate — `tests/testapp/views.py::is_business_account`
- Forms — `tests/testapp/forms.py::AccountTypeForm`,
  `BusinessDetailsForm`, `SecondStepForm`, `PersonalDetailsForm`,
  `ReviewForm`
- Functional test — `tests/functional/test_wizard_viewset.py::test_branching_wizard_done_merges_cleaned_data_across_multi_step_arm_path`

```python
from django.http import HttpResponse
from django.urls import reverse
from gandalf import wizard
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, condition

from .forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    PersonalDetailsForm,
    ReviewForm,
    SecondStepForm,
)


def is_business_account(request):
    account_step = request.wizard.find_step(step_name="account_type")
    return account_step.form.cleaned_data["account_type"] == "business"


class BranchingMergedPayloadWizardViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = (
        wizard.step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            condition(
                is_business_account,
                wizard.step(BusinessDetailsForm).step(SecondStepForm),
            ),
            default=wizard.step(PersonalDetailsForm),
        )
        .step(ReviewForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "branching-merged-payload-wizard-run",
            kwargs={"run_id": run_id},
        )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"account_type={payload['account_type']} "
            f"business_name={payload['business_name']} "
            f"email={payload['email']} "
            f"confirmed={payload['confirmed']}"
        )
```

**Why it works this way:** Branch predicates run after their preceding
steps have completed, so `is_business_account` can read
`cleaned_data` via `request.wizard.find_step(step_name="account_type")`.
First-match-wins; only the matching arm is walked, so `path` only
contains the steps the user actually saw.

---

## 3. Edit an earlier step and keep later answers

**What this shows:** the smart-preservation half of editing. When an
edit doesn't invalidate downstream steps (same branch arm, same
validation), the cursor walker re-validates each downstream step
against the new state and **keeps** what still fits.

**Run it:**
1. Open <http://127.0.0.1:8000/editing-branching-wizard/>
2. Choose `Business`, submit.
3. Enter business name `Shire LLC`, submit.
4. You're now on the review step. Click `Edit business name`.
5. Change the name to `Bag End Inc`, submit.
6. You're back on the review step — the arm didn't change, so the
   wizard parks you at the leaf again. Confirm, submit. Final page
   shows `completed <run_id>`.

**The code:**
- Viewset — `tests/testapp/views.py::EditingBranchingWizardViewSet`
- Template — `tests/testapp/templates/testapp/editing_wizard.html`
  (renders `?gandalf_edit_step=<step_name>` links)
- Functional test — `tests/functional/test_wizard_viewset.py::test_editing_branching_wizard_post_edit_keeping_arm_preserves_downstream`

```python
from django.http import HttpResponse
from django.urls import reverse
from gandalf import wizard
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard, condition

from .forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    PersonalDetailsForm,
    ReviewForm,
)


class EditingBranchingWizardViewSet(WizardViewSet):
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm,
                    context={"step_name": "business_name"},
                ),
            ),
            default=Wizard().step(
                PersonalDetailsForm,
                context={"step_name": "preferred_name"},
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "editing-branching-wizard-run",
            kwargs={"run_id": run_id},
        )

    def done(self, bound_wizard):
        return HttpResponse(f"completed {bound_wizard.run_id}")
```

**Why it works this way:** The default `StepNameEditResolver` reads
`gandalf_edit_step` from the query string (GET-side) or POST body
(POST-side) and looks it up against each step's
`context={"step_name": ...}`. After the edit splice, `CursorWalker`
re-validates every downstream step against the new state; anything that
still validates is kept.

---

## 4. Switch arms mid-edit and drop stale downstream answers

**What this shows:** the other half of editing. When an edit changes
the answer to a step that downstream steps depended on (here: the
branch decision), the cursor walker drops the steps that no longer fit
and re-runs the wizard from that point.

**Run it:**
1. Open <http://127.0.0.1:8000/editing-branching-wizard/>
2. Choose `Business`, enter business name `Shire LLC`, submit.
3. On the review page, click `Edit account type`.
4. Change the choice to `Personal`, submit.
5. You land on the **personal details** form, not review — the
   business-arm answer was dropped because the branch decision
   changed. Enter `Frodo`, submit, confirm review.

**The code:** same viewset and test fixture as recipe 3. The
behavior is asserted by
`tests/functional/test_wizard_viewset.py::test_editing_branching_wizard_post_edit_changing_arm_truncates_downstream`.

**Why it works this way:** When the cursor walker re-validates after a
splice and finds the old arm's stored data no longer applies (because
the branch predicate now selects a different arm), the trailing entries
are truncated. The user re-runs the wizard from the first step that
wasn't preserved — see [ARCHITECTURE.md](ARCHITECTURE.md) for the
cursor walker's truncation logic in detail.

---

## 5. Generate a variable number of steps per run

**What this shows:** dynamic flow shape — the wizard isn't a class-level
constant, it's built per request from prior submissions via
`get_wizard(bound_wizard)`. Here, the first step picks a count and the
wizard then generates that many follow-up steps.

**Run it:**
1. Open <http://127.0.0.1:8000/dynamic-wizard/>
2. Enter a count between 1 and 5 (say `3`), submit.
3. Enter item names one at a time (`Sting`, `Sword`, `Ring`), submit
   each.
4. Final page shows `completed Sting, Sword, Ring`.

Try it again with a different count — the wizard regenerates each
request from the stored count, so the tree shape is genuinely
data-driven.

**The code:**
- Viewset — `tests/testapp/views.py::DynamicWizardViewSet`
- Forms — `tests/testapp/forms.py::ItemCountForm`, `ItemForm`
- Functional test — `tests/functional/test_wizard_viewset.py::test_dynamic_wizard_generates_step_per_chosen_count`

```python
from django.http import HttpResponse
from django.urls import reverse
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .forms import ItemCountForm, ItemForm


class DynamicWizardViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, bound_wizard):
        state = bound_wizard.get_state()
        wizard = Wizard().step(ItemCountForm, context={"step_name": "count"})
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(ItemForm, context={"index": index})
        return wizard

    def get_wizard_url(self, run_id):
        return reverse("dynamic-wizard-run", kwargs={"run_id": run_id})

    def done(self, bound_wizard):
        node = bound_wizard.runtime_tree.next
        names = []
        while node is not None:
            names.append(node.data["name"])
            node = node.next
        return HttpResponse(f"completed {', '.join(names)}")
```

**Why it works this way:** `WizardViewSet` looks up the wizard via
`get_wizard()` on every request. Reading `bound_wizard.get_state()` and
shaping the returned `Wizard` accordingly means the tree is rebuilt
from stored state each time — no need to persist the generated
structure. Note that branch decisions inside the rebuilt tree are still
re-evaluated from submissions; gandalf never persists tree shape.

---

## 6. Fold dynamic steps into one list payload via a custom `Reducer`

**What this shows:** how `MergeCleanedData` is meant to be subclassed
when last-write-wins doesn't fit. Here, each repeated `ItemForm` step
contributes to a single `items` list rather than overwriting earlier
items.

**Run it:**
1. Open <http://127.0.0.1:8000/dynamic-list-payload-wizard/>
2. Enter count `3`, submit.
3. Enter item names (`Sting`, `Sword`, `Ring`), submit each.
4. Final page shows JSON like
   `{"count": 3, "items": [{"name": "Sting"}, {"name": "Sword"}, {"name": "Ring"}]}`.

**The code:**
- Viewset — `tests/testapp/views.py::DynamicListPayloadWizardViewSet`
- Reducer — `tests/testapp/views.py::MergeWithLists`
- Functional test — `tests/functional/test_wizard_viewset.py::test_dynamic_list_payload_wizard_condenses_items_into_list`

```python
import json

from django.http import HttpResponse
from django.urls import reverse
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard

from .forms import ItemCountForm, ItemForm


class MergeWithLists(MergeCleanedData):
    """Steps tagged `context={"list_key": "items"}` contribute their
    cleaned_data as `{"items": [cleaned]}`; combine concatenates lists
    under the same key. Untagged steps behave like the base reducer."""

    def visit_step(self, runtime_step):
        cleaned = runtime_step.form.cleaned_data
        list_key = (runtime_step.declaration.context or {}).get("list_key")
        if list_key is None:
            return cleaned
        return {list_key: [cleaned]}

    def combine(self, accumulator, value):
        merged = {**accumulator}
        for key, incoming in value.items():
            existing = merged.get(key)
            if isinstance(existing, list) and isinstance(incoming, list):
                merged[key] = existing + incoming
            else:
                merged[key] = incoming
        return merged


class DynamicListPayloadWizardViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, bound_wizard):
        state = bound_wizard.get_state()
        wizard = Wizard().step(ItemCountForm, context={"step_name": "count"})
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(
                    ItemForm,
                    context={"list_key": "items", "index": index},
                )
        return wizard

    def get_wizard_url(self, run_id):
        return reverse(
            "dynamic-list-payload-wizard-run",
            kwargs={"run_id": run_id},
        )

    def done(self, bound_wizard):
        payload = MergeWithLists().reduce(bound_wizard.path)
        return HttpResponse(json.dumps(payload, sort_keys=True))
```

**Why it works this way:** A `Reducer` has two hooks: `visit_step`
shapes the value a step contributes, and `combine` folds two
contributions together. The base `MergeCleanedData` uses `cleaned_data`
verbatim and last-write-wins; `MergeWithLists` reads each step's
declared `context` to decide whether to wrap into a list. Step
`context` is user-space metadata — gandalf doesn't interpret it — so
you can use it to drive any per-step policy you need.

---

## 7. Upload a file, survive replay, clean up on completion

**What this shows:** how gandalf handles `forms.FileField`: the session
stores only a ref (key + original filename, content-type, size,
charset), the bytes live in `WizardFileStorage`, and the file is
re-injected into `request.FILES` on every replay so validators see the
same data.

**Run it:**
1. Open <http://127.0.0.1:8000/file-uploading-wizard/>
2. Choose any small file in the photo field, submit.
3. You advance to step 2 (a plain name field).
4. **Hit back, then forward** — gandalf replays the file step from
   storage without asking you to re-upload.
5. Enter a name on step 2, submit.
6. Final page shows `completed <your-filename>`. The `gandalf/<run_id>/`
   directory in the configured file storage is now empty —
   `WizardViewSet` calls `bound_wizard.cleanup_files()` after `done()`
   returns.

**The code:**
- Viewset — `tests/testapp/views.py::FileUploadingWizardViewSet`
- Form — `tests/testapp/forms.py::ProfilePhotoForm`
- Template (note `enctype="multipart/form-data"`) —
  `tests/testapp/templates/testapp/file_upload_wizard.html`
- Functional tests —
  `tests/functional/test_wizard_viewset.py::test_file_uploading_wizard_persists_upload_and_advances`,
  `::test_file_uploading_wizard_done_cleans_up_files`,
  `::test_file_uploading_wizard_replay_after_upload_re_renders_next_step`

```python
from django.http import HttpResponse
from django.urls import reverse
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .forms import FirstStepForm, ProfilePhotoForm


class FileUploadingWizardViewSet(WizardViewSet):
    template_name = "testapp/file_upload_wizard.html"
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, context={"step_name": "photo"})
        .step(FirstStepForm)
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "file-uploading-wizard-run",
            kwargs={"run_id": run_id},
        )

    def done(self, bound_wizard):
        photo_step = bound_wizard.find_step(step_name="photo")
        filename = photo_step.files["photo"]["name"]
        return HttpResponse(f"completed {filename}")
```

**Why it works this way:** The `CursorWalker.visit_step` hook opens
each stored ref via `file_storage.open(ref)`, rebuilds an
`InMemoryUploadedFile` with the original metadata, and injects it into
`request.FILES` before dispatching the step view. That means
content-type-sniffing validators see the same value on replay as on the
original POST. Cleanup runs unconditionally after `done()` — see the
"File uploads" section of [README.md](README.md) for swapping the
backend per tenant.

---

## 8. Edit a file step: keep existing vs replace

**What this shows:** files participate in editing the same way regular
fields do. The edit GET pre-populates the form's `initial` with the
existing file (so the widget shows it); the edit POST chooses per
field: no new upload → keep the ref; new upload → save the new bytes
and delete the old ones in the same operation.

**Run it:**
1. Open <http://127.0.0.1:8000/file-editing-wizard/>
2. Enter a label (e.g. `Avatar`), upload a file, submit.
3. Confirm the review step. The wizard completes.
4. Start again. Enter `Avatar`, upload `photo-a.png`, submit, then go
   back to edit the photo step.
5. Upload `photo-b.png`, submit. The new file replaces the old one
   (the bytes from `photo-a.png` are deleted from storage in the same
   step).

**The code:**
- Viewset — `tests/testapp/views.py::FileEditingWizardViewSet`
- Form (`photo` is optional) —
  `tests/testapp/forms.py::OptionalPhotoForm`
- Functional tests —
  `tests/functional/test_wizard_viewset.py::test_file_editing_wizard_edit_replaces_photo_and_deletes_old`,
  `::test_file_editing_wizard_edit_adds_photo_to_step_without_one`,
  `::test_file_editing_wizard_edit_get_renders_existing_photo`

```python
from django.http import HttpResponse
from django.urls import reverse
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard

from .forms import OptionalPhotoForm, ReviewForm


class FileEditingWizardViewSet(WizardViewSet):
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, context={"step_name": "photo"})
        .step(ReviewForm, context={"step_name": "review"})
    )

    def get_wizard_url(self, run_id):
        return reverse(
            "file-editing-wizard-run",
            kwargs={"run_id": run_id},
        )

    def done(self, bound_wizard):
        photo_step = bound_wizard.find_step(step_name="photo")
        photo_ref = (photo_step.files or {}).get("photo")
        filename = photo_ref["name"] if photo_ref else "no-photo"
        return HttpResponse(f"completed {filename}")
```

**Why it works this way:** `bound_wizard.render_edit(...)` opens stored
refs and merges them into `initial`, so a `ClearableFileInput` widget
shows the existing file. `bound_wizard.edit` runs per-field: a field
with no new upload preserves its ref unchanged; a field with a new
upload saves the new file via the configured `WizardFileStorage` and
deletes the old ref atomically in the same step.

---

## More recipes in the gallery

The index lists more curated examples that didn't make this guided tour
in depth — each one still has a `description` on the viewset and is
covered by a functional test:

- **Pre-fill a downstream step from earlier answers**
  (`PathAwareLinearWizardViewSet`, `/path-aware-linear-wizard/`) — a
  step's `FormView.get_initial()` reads `self.request.wizard.path` to
  seed initial values from previous steps' `cleaned_data`.
- **Look up steps by name in `done()`**
  (`NamedHelperWizardViewSet`, `/named-helper-wizard/`) — uses the
  `named()` helper and `bound_wizard.find_step(step_name=...)` instead
  of walking the runtime tree manually.
- **Customize the edit resolver**
  (`SectionEditingWizardViewSet`, `/section-editing-wizard/`) — swaps
  `StepNameEditResolver` for a `section`-keyed resolver via
  `configure(edit_resolver_class=...)`.
- **First step backed by a `FormView`**
  (`FormViewStepWizardViewSet`) — passing a `FormView` instead of a
  plain `Form` to `.step()` when you need view-level customization.
- **Branch on a shared review** (`BranchingWizardViewSet`,
  `/branching-wizard/`) — minimal version of recipe 2 without
  `MergeCleanedData`.

The gallery's "Other" group collapses pure mechanics demos (empty
wizards, duplicate step names, missing templates) that exist only to
exercise edge cases in the runtime.

---

## How to add a new example

1. Add a `WizardViewSet` to `tests/testapp/views.py` with a
   `description = "..."` attribute. Add `category = "..."` and
   `example = True` to surface it in the gallery's grouped sections.
2. Wire URL patterns into `tests/testapp/urls.py` following the
   `wizard/`, `wizard/<uuid:run_id>/` pair convention.
3. Add a functional test in `tests/functional/test_wizard_viewset.py`
   that drives the wizard through its happy path.
4. If the recipe is worth a guided walkthrough, add a section to this
   file using the same five-part shape: *What this shows / Run it /
   The code / Why it works this way*.

Recipes are kept honest by the tests — when a viewset or test changes,
the recipe is updated alongside it.
