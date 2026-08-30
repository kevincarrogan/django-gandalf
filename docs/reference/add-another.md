# Add another

`gandalf.add_another` — the *add another* pattern: a page listing items the
user grows, one wizard run per item, with **Change** and **Remove** on each
row and an **Add another** question underneath.

```python
from gandalf.add_another import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnotherForm,
    AddAnotherPage,
    AddAnotherViewSet,
    ItemNotFound,
    ItemRow,
    ItemViewSet,
)
from gandalf.tasklists import AddAnother
```

An add-another page is a [task list](tasklists.md) whose entries are
*built* rather than declared: one per id in an ordered registry. The status
derivation, the row building, the resume-before-reopen door and the
never-a-bare-run-URL guarantee are `TaskListViewSet`'s, unchanged. What
the page adds is the two things a task list has no notion of: completeness
is *declared* by the user rather than derived from storage, and a row is a
thing that can be *destroyed*.

`COMPLETE`, `INCOMPLETE` and `NOT_STARTED` are re-exported from
`gandalf.tasklists` and mean exactly what they mean there.

---

## Reference

### `AddAnother(wizard, *, title=None, item_name=None, item_title=None, min_items=0, reopen_at=None, label=None, template_name=None, remove_template_name=None)`

The entry: one *add another* list. Declared in a `TaskList` body, which
mounts the page beneath the list, or set as `add_another` on a root
`AddAnotherViewSet`. A frozen dataclass, so `dataclasses.replace()` makes a
variant.

- `wizard` — runs one item: a `Wizard` or `ConfiguredWizard`, or an
  `ItemViewSet` subclass for an item with behaviour of its own
  (`run_done()`, `item_removed()`).
- `title` — what the row on the task list above renders.
- `item_name` — what an unfinished item is called in a positional title
  (`Budget line 2`). `None` derives it from the key: underscores and
  hyphens to spaces, a trailing `s` dropped, first letter capitalised
  (`budget_lines` → `Budget line`).
- `item_title` — what names a finished item on the page: a
  `(step, field)` pair, read off the finished run, or
  `callable(run) -> str`. Return `""` and the row keeps its
  positional name. Required by the time an item finishes.
- `min_items` — items required before *no more to add* counts as complete.
  Zero is right for "any other income?"; one for "add at least one".
- `reopen_at` — the step a finished item re-opens at (its review step,
  usually). `None` re-opens at the first step.
- `label` — the stash label every item stamps and the page expects; one
  value for both halves. `None` uses the list's key. Bump it when a deploy
  reshapes the item wizard.
- `template_name` / `remove_template_name` — the page and the confirmation
  page. A root viewset that sets either on the class keeps its own.

### `AddAnotherViewSet`

A `TaskListViewSet` whose entries are the registry's items, with the three
URL patterns published and the item wizard mounted beneath the door.

```python
class BudgetViewSet(AddAnotherViewSet):
    url_name = "budget"
    key = "budget"
    add_another = budget
    task_list_url_name = "apply"      # where Continue goes
```

A page listed by a task list is built by the list, which sets all four. A
root page sets them itself: `task_list_url_name` is where *Continue*
returns to — a task list, or any page — and leaving it `None` makes the
page end the journey, which requires `journey_done()`.

**Attributes** — everything `TaskListViewSet` declares, with these
defaults and additions:

| Attribute | Default | Meaning |
| --- | --- | --- |
| `add_another` | `None` | The entry. Required. |
| `url_name` | `None` | Name of the page pattern; `-item`, `-remove`, `-item-run` and `-item-step` are derived from it. Required. |
| `key` | `None` | The key items are registered and keyed under, and the key a parent task list lists this page by. **Required** — never `None`, whether or not a task list above lists it. |
| `item_viewset` | generated | The `ItemViewSet` subclass built from `add_another.wizard`, for a driver that addresses an item. |
| `task_list_url_name` | `None` | Where *Continue* goes. `None` makes the page a *root*: `submit()` then ends the journey. |
| `template_name` / `remove_template_name` | from the entry | The page and the confirmation page. |
| `section_template_name` | `None` | The template the item wizard renders with when its `Wizard` carries none. |
| `form_class` | `AddAnotherForm` | The form the page POST is validated with. |
| `items_context_name` | `"items"` | Where the `AddAnotherPage` lands in the template context. |
| `page_context_name` | `None` | Suppresses the task list's `task_list` context object: one page, one status. |
| `entry_url_kwarg` | `"item"` | The URL kwarg carrying the item id on the door and remove routes. |
| `journey_store_class` | `SessionCollectionStore` | Must satisfy `gandalf.types.CollectionStore`. |

#### The routes

| Pattern | Name | Kwargs | GET | POST |
| --- | --- | --- | --- | --- |
| `""` | `<url_name>` | mount prefix | renders the page with `items` and `form` in context | validates `AddAnotherForm`: `yes` → `add_item()` and redirect into the new item; `no` → `declare_done()`; invalid → re-render with `form` errors |
| `<uuid:item>/` | `<url_name>-item` | `item` | the door: `enter()` the item and redirect to its step URL | `405 Method Not Allowed` (`Allow: GET`) |
| `<uuid:item>/remove/` | `<url_name>-remove` | `item` | renders `remove_template_name` with `items`, `form` and `row` in context | `remove_item()` and redirect to the page |
| `<uuid:item>/<uuid:run_id>/…` | `<url_name>-item-run`, `<url_name>-item-step` | `item`, `run_id`, `gandalf_step` | the item wizard's own routes | |

The item kwarg is a `uuid`, never a slug — that is what lets `remove/` be a
safe sibling of the door. The item wizard's bare start URL is not
published: the door *is* the item's URL, so there is no bare run URL to
link.

On either item route, an id the page does not list (`ItemNotFound`) is
answered by `entry_unavailable(item_id)` — a redirect to the page by
default. A door whose `enter()` returns `None` (an `entry_blocked()` item)
is answered the same way. The view tells the door from the remove route by
`request.resolver_match.url_name`, so it has to be reached through the
URLconf.

#### Hooks

Items and identity:

| Hook | Default | Override to |
| --- | --- | --- |
| `get_list_key()` | `key` | — |
| `get_store()` | `get_journey_store()` cast to `CollectionStore` | — |
| `get_item_viewset()` | `item_viewset` | — |
| `get_item_ids()` | `store.item_ids(key)` | build the list from your own records instead of the registry; `get_item()` and `get_entries()` both read it |
| `new_item_id()` | `str(uuid.uuid4())` | choose identity yourself. Must be opaque and unique; a positional id would renumber survivors on removal, and the routes match `<uuid:item>` |
| `get_item_label()` | `add_another.label`, else the key | — |
| `get_item_entry(item_id)` | a `Section` bound to `item_id`, the item viewset, the label, `reopen_at` and `url_kwargs={"item": item_id}` | — |
| `get_entries()` | one `get_item_entry()` per `get_item_ids()` | — |
| `get_item(item_id)` | the entry, or `ItemNotFound` if `get_item_ids()` does not list it | — |
| `item_id_for(entry)` | `entry.url_kwargs["item"]` | — |

The page:

| Hook | Default | Override to |
| --- | --- | --- |
| `get_items()` | builds the `AddAnotherPage` from `get_rows()`, `get_items_status()`, `store.is_declared_done()` and `min_items` | — |
| `get_page()` | `get_items()` — the page's `TaskListPage` *is* its `AddAnotherPage`, so a parent's `status_for()` and `submit()` read the declared status | — |
| `build_rows()` | one `build_item_row()` per vetted entry, in registry order | — |
| `build_item_row(entry, store, position)` | an `ItemRow` | add fields on an `ItemRow` subclass |
| `get_item_title(item_id, store, position)` | the cached title, else `get_placeholder_title(position)` | — |
| `get_placeholder_title(position)` | `"<item name> <position + 1>"` | other wording |
| `get_item_name()` | `add_another.item_name`, else derived from the key | — |
| `get_items_status(rows, store)` | the table below | another rule |
| `get_status_label(status)` | *Not started* / *Incomplete* / *Complete* / *Cannot start yet* | your own wording |
| `get_entry_url(entry)` | `get_item_url()` — the door | — |
| `get_item_url(item_id)` | `reverse("<url_name>-item", kwargs={**page kwargs, "item": item_id})` | — |
| `get_item_remove_url(item_id)` | `reverse("<url_name>-remove", ...)` | — |
| `get_form_class()` | `form_class` | — |
| `get_form(data=None)` | `get_form_class()(data=data)` | — |
| `get_context_data(**kwargs)` | adds `items` and, unless given, `form` | — |
| `entry_blocked(entry, store)` | `False` — items answer no gate | gate every item at once |
| `entry_hidden(entry, store)` | `False` | hide items |

The actions:

| Hook | Default | Override to |
| --- | --- | --- |
| `add_item()` | register a new id, withdraw *declared done*, then `enter()` the item. Returns the step URL, or `None` if entry was refused | — |
| `declare_done()` | record *declared done*, then `submit()` | — |
| `remove_item(item_id)` | destroy the item in the order below; redirect to the page | — |
| `discard_item_run(entry, store)` | `inspect()` the item's recorded run and `obliterate()` it; a run the storage has forgotten is not an error | — |
| `submit()` | `page_incomplete()` unless `items.is_complete`; else `group_done()` when nested, `journey_done()` then `store.complete()` at a root | — |
| `group_done(page, store)` | redirect to `get_tasklist_url()` | work that runs once per Continue |
| `page_incomplete(page)` | redirect to `get_page_url()` | render the page with an error |
| `journey_done(page, store)` | `ImproperlyConfigured` | required on a root page |
| `submitted(store)` | root: `Http404`; nested: redirect up | a done page |
| `entry_unavailable(key)` | redirect to `get_page_url()` | raise `Http404` |
| `enter(entry)` / `resume_section()` / `reopen_section()` / `start_section()` / `stash_unusable()` | `TaskListViewSet`'s | see [Task lists](tasklists.md) |

An item's own behaviour — saving it, forgetting it — lives on the
`ItemViewSet` in the entry's slot, beside its wizard. A hook every
add-another page in a tree shares — `get_placeholder_title()`, say — goes
on an `AddAnotherViewSet` subclass set as the root's
`add_another_viewset_class`.

#### The add order

`add_item()` writes the registry **first**, withdraws the user's *no more*
answer, and only then starts the wizard. A start that raises or is refused
leaves a listed, removable, not-started row rather than a live run nothing
points at. Pressing *Add another* is the user withdrawing their answer to
*any more?* — so a complete list goes back to incomplete.

#### The removal order

`remove_item()` destroys everything reachable *through* the registry before
the registry entry itself, so a hook that raises leaves the item still
listed and still removable rather than vanished with its side effects
intact:

1. `discard_item_run()` — the item's live run is obliterated (state and
   uploaded files).
2. `store.clear_run(full_key)` — the run pointer is forgotten.
3. `store.delete_stash(full_key)` — the finished answers are deleted.
4. `store.set_item_title(key, item_id, None)` — the cached title is cleared.
5. the item's `item_removed(store)` — the application's own work, on an
   `ItemViewSet` set up for this item.
6. `store.remove_item(key, item_id)` — the registry entry, last.

Removal answers no question: the user's *no more to add* stands. Three lines
minus one is still "and no more". The remove route asks first — GET confirms,
POST removes.

#### Status derivation

`get_items_status(rows, store)`:

| Declared done? | Rows | Result |
| --- | --- | --- |
| no | none | `NOT_STARTED` |
| no | any | `INCOMPLETE` |
| yes | fewer than `min_items` | `INCOMPLETE` |
| yes | any row not `is_complete` (blocked, incomplete or not started) | `INCOMPLETE` |
| yes | otherwise | `COMPLETE` |

So an empty list the user has declared done is `COMPLETE` when `min_items`
is `0` ("any other income?") and `INCOMPLETE` when it is `1`. A user can
answer *no more* while an item sits half-finished — the page only shows the
question beside the rows — and the honest report is then *Incomplete*, not
*Complete* over answers nobody gave.

Each row's status is `TaskListViewSet.get_entry_status()`: `BLOCKED` if
`entry_blocked()`, else `COMPLETE` if a stash exists under the item's full
key, else `INCOMPLETE` if a recorded run holds at least one submission, else
`NOT_STARTED`. A seeded item whose run the storage has forgotten reads as
not started — it still has a row, because a row exists from the moment the
item is registered.

### `AddAnotherPage`

A frozen dataclass and a `gandalf.tasklists.TaskListPage`. What the page
and a parent's row both read.

**Attributes**

| Attribute | Type | Meaning |
| --- | --- | --- |
| `rows` | `tuple[ItemRow, ...]` | one per item, in the order the user added them |
| `status` | `str` | `NOT_STARTED`, `INCOMPLETE` or `COMPLETE` |
| `status_label` | `str` | display text for `status` |
| `key` | `str` | the list's key |
| `url` | `str` | the page's own URL |
| `declared_done` | `bool` | whether the user has said there are no more to add |
| `min_items` | `int` | the entry's `min_items` |
| `count` | `int` | `len(rows)` |
| `completed` | `int` | rows that `is_complete` |
| `remaining` | `int` | `count - completed`, blocked rows included |
| `blocked` | `int` | rows that `is_blocked` |
| `is_empty` | `bool` | no rows |
| `is_not_started` / `is_incomplete` / `is_complete` | `bool` | status tests |

### `ItemRow`

A frozen dataclass and a `gandalf.tasklists.Row`. One item.

**Attributes**

| Attribute | Type | Meaning |
| --- | --- | --- |
| `entry` | `Entry` | the underlying entry (`entry.key` is the item id) |
| `item_id` | `str` | the item's uuid |
| `position` | `int` | zero-based index in the registry |
| `title` | `str` | the title cached when the item last finished, else a positional name |
| `status` | `str` | `NOT_STARTED`, `INCOMPLETE`, `COMPLETE` or `BLOCKED` |
| `status_label` | `str` | display text |
| `url` | `str` | the *Change* link: this page's door for the item |
| `remove_url` | `str` | the *Remove* link: the confirmation route |
| `key` | `str` | `entry.key`, the item id |
| `is_not_started` / `is_incomplete` / `is_complete` / `is_blocked` | `bool` | status tests |

`title` is a cached string, not a computation: the item's own viewset
worked it out at completion, and the row reads it back. Thirty items cost
thirty dict lookups, never thirty walks.

### `AddAnotherForm`

The form a page POST is validated with.

**Fields** — `add_another`, a required `ChoiceField` with choices
`("yes", "Yes")` and `("no", "No")`, a `RadioSelect` widget and the required
message *Select yes if you want to add another*.

**Properties** — `wants_another` — `True` when the cleaned answer is
`"yes"`. Valid only once `is_valid()` has run.

Two submit buttons named `add_another` with values `yes` and `no` carry the
answer without a widget on the page. Swap the form with `form_class`; the view
only reads `is_valid()` and `wants_another`.

### `ItemViewSet`

The viewset an add-another page runs one item with. Built by
`AddAnotherViewSet` from `add_another.wizard` and mounted under
`<uuid:item>/` beneath the page, so one class serves every row; reach it as
`item_viewset`. Everything [`SectionViewSet`](tasklists.md) does, keyed per
item: the key comes from the URL. An item with behaviour declares its own
subclass and puts that in the entry's slot:

```python
class VehicleItem(ItemViewSet):
    wizard = vehicle

    def run_done(self, run):
        save_vehicle(self.request, self.get_item_id(), run)
        return super().run_done(run)

    def item_removed(self, store):
        forget_vehicle(self.request, self.get_item_id())
```

**Attributes** — `list_key` (the page's `key`), `item_url_kwarg`
(`"item"`), `item_title` (the entry's), and the journey and store
attributes of the page.

| Hook | Behaviour |
| --- | --- |
| `get_list_key()` | `list_key`, or `ImproperlyConfigured` |
| `get_item_id()` | `self.kwargs["item"]` as a string, or `ImproperlyConfigured` when not mounted under an item segment |
| `get_key()` | `"<list_key>:<item_id>"` — the same string the page's `full_key()` composes |
| `default_label()` | the *list's* key, not the item's, so every item stamps one label |
| `get_item_title(run)` | `item_title`'s field from its step, or its callable; `""` when the step is not on the route taken. `ImproperlyConfigured` (*"cannot name its items"*) when `item_title` is `None`. Costs one walk, once, at completion |
| `run_recorded(run, store, key)` | caches `get_item_title()` (an empty title is stored as `None`) inside the window where the run's answers are still readable |
| `run_done(run)` | back to the page; override to save the item first |
| `item_removed(store)` | nothing; override to undo what `run_done()` did. Runs while the item is still listed, on a viewset set up for it, so `get_item_id()` says which |
| `get_tasklist_url_kwargs()` | `get_url_kwargs()` without `item` — the page has no place for the item segment; a journey or tenant prefix is forwarded |
| `run_unavailable(run, reason)` | redirect to the page rather than start a run for an item that may no longer exist |
| `dispatch()` | refuses any request for an item the registry does not list, before `WizardViewSet` sees it, with `item_unavailable()` |
| `item_unavailable()` | redirect to the page; override to raise `Http404` |

### `ItemNotFound(LookupError)`

Raised by `get_item(item_id)` when the id names no item that
`get_item_ids()` lists — a removed item, a stale link, a URL typed by hand.
Caught on both item routes and answered with `entry_unavailable()`.

### Mounting

A page listed by a task list is mounted by the list, at `<key>/` beneath
the list's page. A root page is mounted by itself, and its item wizard is
beneath its door:

```python
urlpatterns = [path("vehicles/", include(VehiclesViewSet.urls()))]
```

Under a journey, the whole tree sits under the one `<slug:journey>/`
segment and every item URL carries it.

### Storage

`SessionCollectionStore` (in `gandalf.storage`) is a `SessionJourneyStore`
plus a `"collections"` mapping on the journey's record:

```python
{"collections": {"budget": {"items": [{"id": "<uuid>", "title": "Paint"}, ...],
                            "declared_done": False}}}
```

The registry is explicit because the stash key space cannot stand in for
it: stashes hold only items that have *finished*, in the order they finished.
An item's run and stash live under the ordinary key `budget:<uuid>`,
composed by the view — the store never learns the scheme, so a task list's
store and an add-another page's store share one key space.

`gandalf.types.CollectionStore` is what `journey_store_class` must provide
beyond a `JourneyStore`:

| Method | Contract |
| --- | --- |
| `item_ids(key) -> list[str]` | in the order added; `[]` for a list never started |
| `has_item(key, item_id) -> bool` | |
| `add_item(key, item_id)` | append; an id already listed is a no-op |
| `remove_item(key, item_id)` | forget the item and its title, keeping the order of the rest; idempotent |
| `get_item_title(key, item_id) -> str \| None` | `None` until the item has finished |
| `set_item_title(key, item_id, title)` | `None` clears; an unlisted id is ignored |
| `is_declared_done(key) -> bool` | `False` until set |
| `set_declared_done(key, declared_done)` | |

Completing the journey takes the registry with it. Test helpers
`seed_item()` and `stored_items()` live in `gandalf.testing` — see
[Testing](testing.md).

### Why add another and not `.expand()`

`Wizard.expand()` grows *steps* inside one run from a count the user just
gave. Its answers are positional, so deleting from the middle shifts every
answer after it; and one run means there is no such thing as a half-finished
item. An add-another item's identity is opaque — remove from the middle and
the survivors keep their ids, their URLs and their answers — and every item
is its own run, separately resumable, completable and destroyable. Use
`.expand()` for "how many trustees? now name each"; use add another for
"add as many as you like, and change your mind later".

---

## Usage

### A budget the applicant grows

```python
from gandalf.tasklists import AddAnother, Section, TaskList, TaskListViewSet
from gandalf.wizard import Wizard


class Project(TaskList):
    project = Section(project, title="Project", reopen_at="review")
    budget = AddAnother(
        Wizard()
        .step(BudgetLineForm, name="line", label="Budget line")
        .step(ReviewStepView, name="review"),
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen_at="review",
        template_name="grants/budget.html",
        remove_template_name="grants/budget_remove.html",
    )


class ProjectViewSet(TaskListViewSet):
    template_name = "grants/task_list.html"
    section_template_name = "grants/step.html"
    url_name = "apply"
    task_list = Project
```

The task list's `Budget` row links straight at the page (`apply/budget/`,
named `apply-budget`) and reads its declared status.

### The page template

```django
{% if items.is_empty %}
  <h1>You have not added any budget lines</h1>
{% else %}
  <h1>You have added {{ items.count }} budget line{{ items.count|pluralize }}</h1>
  <p>You have completed {{ items.completed }} of {{ items.count }}.</p>
  <ul>
    {% for row in items.rows %}
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
  {% if not items.is_empty %}
    <button type="submit" name="add_another" value="no">Continue</button>
  {% endif %}
</form>
```

The confirmation page gets `row` as well:

```django
<h1>Are you sure you want to remove {{ row.title }}?</h1>
<form method="post">
  {% csrf_token %}
  <button type="submit">Remove {{ row.title }}</button>
</form>
<a href="{{ items.url }}">Cancel</a>
```

### Saving each line, and deleting it on removal

```python
from gandalf.add_another import ItemViewSet


class BudgetLineItem(ItemViewSet):
    wizard = budget_line

    def run_done(self, run):
        line = run.path.find_step(name="line").form.cleaned_data
        BudgetLine.objects.update_or_create(
            item_id=self.get_item_id(),
            defaults={"item": line["item"], "cost": line["cost"]},
        )
        return super().run_done(run)

    def item_removed(self, store):
        BudgetLine.objects.filter(item_id=self.get_item_id()).delete()


class Project(TaskList):
    budget = AddAnother(BudgetLineItem, title="Budget", item_title=("line", "item"))
```

The entry is unchanged; the richer thing goes in the slot. `item_removed()`
runs before the registry entry goes, so a delete that raises leaves the
line listed and removable.

### A page mounted on its own

```python
class VehiclesViewSet(AddAnotherViewSet):
    url_name = "vehicles"
    key = "vehicles"
    add_another = AddAnother(VehicleItem, item_name="Vehicle", item_title=("vehicle", "registration"))
    task_list_url_name = "quote"          # Continue returns to the quote wizard


urlpatterns = [path("vehicles/", include(VehiclesViewSet.urls()))]
```

### Naming an item from more than one field

```python
def trustee_name(run):
    step = run.path.find_step(name="name")
    if step is None:
        return ""
    data = step.form.cleaned_data
    return f"{data['first_name']} {data['last_name']}"


trustees = AddAnother(trustee, item_title=trustee_name)
```

Returning `""` lets the row fall back to `Trustee 2` rather than inventing a
name.

### Gating every item until the project is described

```python
class GatedAddAnotherViewSet(AddAnotherViewSet):
    def entry_blocked(self, entry, store):
        return not store.has_stash("project")


class GrantApplicationViewSet(TaskListViewSet):
    add_another_viewset_class = GatedAddAnotherViewSet
    ...
```

Blocked rows read *Cannot start yet*, the door refuses them, and *Add
another* still registers a row — the user is returned to the page with a
listed, removable, not-started item.

---

## Troubleshooting

### I said No and the page came straight back instead of continuing

`submit()` was refused with `page_incomplete()`: an item is unfinished, or
there are fewer than `min_items`. The declaration was still recorded, so
finishing the item (or adding one) and pressing *Continue* again completes
the list. Override `page_incomplete()` to render the page with an
explanation instead of a bare redirect.

### `ImproperlyConfigured: ... has nothing to do when its journey is submitted`

The page has no `task_list_url_name`, so it is a root and *Continue* ends
the journey. Either set `task_list_url_name` to where *Continue* should go,
or override `journey_done(page, store)`.

### `ImproperlyConfigured: ... has no list to show`

A root `AddAnotherViewSet` without `key`. Set it beside `add_another` and
`url_name`.

### `ImproperlyConfigured: ... has no items to list`

The viewset has no `add_another`. Set it to an `AddAnother` entry.

### A POST to `<url_name>-item` returns 405

By design. The door is GET-only so that a form posting to the URL its own
row links to cannot remove the item it meant to open. Removal is
`<url_name>-remove`, and only that route destroys anything.

### `ImproperlyConfigured: ... cannot name its items`

The item finished and `run_recorded()` asked for a title, but the entry has
no `item_title`. Give it the `(step, field)` pair, or a callable of the
finished run.

### `ImproperlyConfigured: ... is not mounted under an item segment`

The item viewset was dispatched without an `item` kwarg. It is only ever
reached through the routes its page publishes.

### `ImproperlyConfigured: Set remove_template_name ...`

The remove route was reached and there is no confirmation page to render.
Set `remove_template_name` on the entry, or on a root viewset.

---

**Learn:** [Chapter 13 — Add another](../learn/13-add-another.md) · **Related:** [Task lists](tasklists.md), [Journey store](journey-store.md), [Stashing](stashing.md), [Testing](testing.md), [`WizardViewSet`](viewsets.md)
