# Chapter 12 — Budget lines

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
    hub_url_name = "readme-budget"
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
    section_key = "budget"
    item_viewset = BudgetLineViewSet
    item_name = "Budget line"
    item_reopen_step = "review"
    min_items = 1
    hub_url_name = "readme-project-hub"


class ProjectHubView(HubView):
    template_name = "testapp/readme_hub.html"
    url_name = "readme-project-hub"
    section_url_name = "readme-project-hub-section"
    sections = [
        Section("project", ProjectSectionViewSet, title="Project", reopen_step="review"),
        # A collection page is not a wizard, so the row links straight at it
        # and answers for its own status.
        Section("budget", BudgetCollectionView, title="Budget"),
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

> ▶ **Try it live:** http://127.0.0.1:8000/readme/project/ &nbsp;·&nbsp; **Source:** [`ch12_budget.py`](../tests/testapp/readme/ch12_budget.py)

---

[← Chapter 11 — A task list](11-a-task-list.md) · [README](../README.md) · [Chapter 13 — Locked and hidden →](13-locked-and-hidden.md)
