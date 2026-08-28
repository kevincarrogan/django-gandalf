# Collections

`gandalf.collections` — the *add another* pattern: a page listing items the
user grows, one wizard run per item, with **Change** and **Remove** on each
row and an **Add another** question underneath.

```python
from gandalf.collections import (
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnotherForm,
    Collection,
    CollectionMixin,
    CollectionRow,
    CollectionView,
    ItemMemberMixin,
    ItemNotFound,
)
```

A collection is a [hub](hubs.md) whose members are *built* rather than
declared: one `Member` per id in an ordered registry. The status derivation,
the row building, the resume-before-reopen door and the
never-a-bare-run-URL guarantee are `HubMixin`'s, unchanged. What a collection
adds is the two things a hub has no notion of: completeness is *declared* by
the user rather than derived from storage, and a row is a thing that can be
*destroyed*.

`COMPLETE`, `INCOMPLETE` and `NOT_STARTED` are re-exported from
`gandalf.hubs` and mean exactly what they mean there.

---

## Reference

### `CollectionView`

`CollectionMixin` over `django.views.generic.TemplateView`, with the three URL
patterns published. `HubView` is deliberately not in its ancestry: the hub's
two patterns and its GET-only door are precisely what a collection replaces.

```python
class BudgetCollectionView(CollectionView):
    url_name = "budget"
    member_key = "budget"
    item_viewset = BudgetLineViewSet
    template_name = "grants/budget.html"
    remove_template_name = "grants/budget_remove.html"
    hub_url_name = "application-hub"
```

**Attributes** — all of `CollectionMixin`'s (below), plus `template_name`
from `TemplateView`.

**Methods**

- `urls()` *(classmethod)* — the three patterns, derived from `url_name`.
  Raises `ImproperlyConfigured` when `url_name` is `None`.
- `get(request, ...)` — the page with no item kwarg; the door or the
  confirmation page with one.
- `post(request, ...)` — answers *add another* on the page; removes on the
  remove route; `405` on the door.
- `get_template_names()` — `[remove_template_name]` on the remove route
  (raising `ImproperlyConfigured` if it is `None`), else `TemplateView`'s.
- `row(item_id)` — the one `CollectionRow` a confirmation page is about.
  Assumes `get_item()` has already vouched for the id.

#### The three routes

| Pattern | Name | Kwargs | GET | POST |
| --- | --- | --- | --- | --- |
| `""` | `<url_name>` | mount prefix | renders the page with `collection` and `form` in context | validates `AddAnotherForm`: `yes` → `add_item()` and redirect into the new item; `no` → `declare_done()`; invalid → re-render with `form` errors |
| `<uuid:item>/` | `<url_name>-item` | `item` | the door: `enter()` the item and redirect to its step URL | `405 Method Not Allowed` (`Allow: GET`) |
| `<uuid:item>/remove/` | `<url_name>-remove` | `item` | renders `remove_template_name` with `collection`, `form` and `row` in context | `remove_item()` and redirect to the page |

The item kwarg is a `uuid`, never a slug — that is what lets `remove/` be a
safe sibling of the door. A slug would swallow it and every verb after it.

On either item route, an id the collection does not list
(`ItemNotFound`) is answered by `member_unavailable(item_id)` — a redirect
to the page by default. A door whose `enter()` returns `None` (a
`member_blocked()` item) is answered the same way. The view tells the
door from the remove route by `request.resolver_match.url_name`, so it has
to be reached through the URLconf.

#### `CollectionMixin` attributes

Everything `HubMixin` declares, with these defaults and additions:

| Attribute | Default | Meaning |
| --- | --- | --- |
| `url_name` | `None` | Name of the page pattern; `-item` and `-remove` are derived from it. Required for `urls()`, `get_page_url()` and every row link. |
| `member_key` | `None` | The key items are registered and keyed under, and the key a parent hub lists this collection by. **Required** — a collection's key is never `None`, whether or not a hub above lists it. |
| `item_viewset` | `None` | The `ItemMemberMixin` viewset that collects one item. **Required.** |
| `item_name` | `None` | What one item is called in a positional title (`Budget line 2`). `None` derives it from the key: underscores and hyphens to spaces, a trailing `s` dropped, first letter capitalised (`budget_lines` → `Budget line`). |
| `item_label` | `None` | The stash label every item stamps. `None` uses the collection key. Must agree with the item viewset's `member_label`, if declared. |
| `item_reopen_step` | `None` | The step a finished item re-opens at (its review step, usually). `None` re-opens at the first step. |
| `min_items` | `0` | Items required before *no more to add* counts as complete. |
| `hub_url_name` | `None` | The `url_name` of the hub that lists this collection. `None` makes the collection a *root*: `submit()` then ends the journey and requires `journey_done()`. |
| `template_name` | — | The page (from `TemplateView`). |
| `remove_template_name` | `None` | The confirmation page. Required on the remove route. |
| `form_class` | `AddAnotherForm` | The form the page POST is validated with. |
| `collection_context_name` | `"collection"` | Where the `Collection` lands in the template context. |
| `hub_context_name` | `None` | Suppresses `HubMixin`'s `hub` context object: one page, one status. |
| `member_url_kwarg` | `"item"` | The URL kwarg carrying the item id on the door and remove routes. |
| `journey_store_class` | `SessionCollectionStore` | Must satisfy `gandalf.types.CollectionStore`. |
| `journey` | `"default"` | The journey this collection belongs to when not mounted under a `<journey>` segment. |
| `journey_url_kwarg` | `"journey"` | The URL kwarg read for the journey when present. |
| `key_separator` | `":"` | Joins the collection key to an item id: `budget:<uuid>`. |
| `members` | `None` | Unused — `get_members()` answers from the registry. |
| `member_url_name` | `None` | Unused — `get_member_url()` answers with the door. |

#### `CollectionMixin` hooks

Items and identity:

| Hook | Default | Override to |
| --- | --- | --- |
| `get_member_key()` | `member_key`, or `ImproperlyConfigured` | — |
| `get_collection_key()` | `get_member_key()` | — |
| `get_collection_store()` | `get_journey_store()` cast to `CollectionStore` | — |
| `get_item_viewset()` | `item_viewset`, or `ImproperlyConfigured` | choose the wizard per request |
| `get_item_ids()` | `store.item_ids(key)` | build the list from your own records instead of the registry; `get_item()` and `get_members()` both read it |
| `new_item_id()` | `str(uuid.uuid4())` | mint identity yourself. Must be opaque and unique; a positional id would renumber survivors on removal, and the routes match `<uuid:item>` |
| `get_item_label()` | `item_label`, else the collection key | — |
| `get_item_member(item_id)` | a `Member(key=item_id, viewset=item_viewset, label=item_label, reopen_step=item_reopen_step, url_kwargs={**page kwargs, "item": item_id})` | — |
| `get_members()` | one `get_item_member()` per `get_item_ids()` | — |
| `get_item(item_id)` | the member, or `ItemNotFound` if `get_item_ids()` does not list it | — |
| `item_id_for(member)` | `member.url_kwargs["item"]` | — |

The page:

| Hook | Default | Override to |
| --- | --- | --- |
| `get_collection()` | builds the `Collection` from `get_member_rows()`, `get_collection_status()`, `store.is_declared_done()` and `min_items` | — |
| `get_hub()` | `get_collection()` — a collection's `Hub` *is* its `Collection`, so a parent hub's `status_for()` and `submit()` read the declared status | — |
| `build_member_rows()` | one `build_collection_row()` per vetted member, in registry order | — |
| `build_collection_row(member, store, position)` | a `CollectionRow` | add fields on a `CollectionRow` subclass |
| `get_item_title(item_id, store, position)` | the cached title, else `get_placeholder_title(position)` | — |
| `get_placeholder_title(position)` | `"<item name> <position + 1>"` | other wording |
| `get_item_name()` | `item_name`, else derived from the key | — |
| `get_collection_status(rows, store)` | the table below | another rule |
| `get_status_label(status)` | *Not started* / *Incomplete* / *Complete* / *Cannot start yet* | your own wording |
| `get_member_url(member)` | `get_item_url()` — the door, never the wizard's own URL | — |
| `get_item_url(item_id)` | `reverse("<url_name>-item", kwargs={**page kwargs, "item": item_id})` | — |
| `get_item_remove_url(item_id)` | `reverse("<url_name>-remove", ...)` | — |
| `get_form_class()` | `form_class` | — |
| `get_form(data=None)` | `get_form_class()(data=data)` | — |
| `get_context_data(**kwargs)` | adds `collection` and, unless given, `form` | — |
| `member_blocked(member, store)` | asks `item_viewset.blocked()` | gate every item at once; call `super()` where the items should still get their say |
| `member_hidden(member, store)` | asks `item_viewset.hidden()` | hide every item at once |

The actions:

| Hook | Default | Override to |
| --- | --- | --- |
| `add_item()` | register a new id, withdraw *declared done*, then `enter()` the item. Returns the step URL, or `None` if entry was refused | — |
| `declare_done()` | record *declared done*, then `submit()` | — |
| `remove_item(item_id)` | destroy the item in the order below; redirect to the page | — |
| `discard_item_run(member, store)` | `inspect()` the item's recorded run and `obliterate()` it; a run the storage has forgotten is not an error | — |
| `item_removed(item_id, member, store)` | nothing | delete whatever the item's `run_done()` saved. Runs while the item is still listed |
| `submit()` | `hub_incomplete()` unless `collection.is_complete`; else `hub_done()` when nested, `journey_done()` then `store.complete()` at a root | — |
| `hub_done(hub, store)` | redirect to `get_hub_url()` | work that runs once per submit of this part |
| `hub_incomplete(hub)` | redirect to `get_page_url()` | render the page with an error |
| `journey_done(hub, store)` | `ImproperlyConfigured` | required on a root collection |
| `journey_completed(store)` | nested: redirect up; root: `Http404` | a done page |
| `member_unavailable(key)` | redirect to `get_page_url()` | raise `Http404` |
| `enter(member)` / `resume_member()` / `reopen_member()` / `start_member()` / `stash_unusable()` | `HubMixin`'s | see [Hubs](hubs.md) |

#### The add order

`add_item()` writes the registry **first**, withdraws the user's *no more*
answer, and only then starts the wizard. A start that raises or is refused
leaves a listed, removable, not-started row rather than a live run nothing
points at. Pressing *Add another* is the user withdrawing their answer to
*any more?* — so a complete collection goes back to incomplete.

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
5. `item_removed(item_id, member, store)` — the application's own work.
6. `store.remove_item(key, item_id)` — the registry entry, last.

Removal answers no question: the user's *no more to add* stands. Three lines
minus one is still "and no more". The remove route asks first — GET confirms,
POST removes.

#### Status derivation

`get_collection_status(rows, store)`:

| Declared done? | Rows | Result |
| --- | --- | --- |
| no | none | `NOT_STARTED` |
| no | any | `INCOMPLETE` |
| yes | fewer than `min_items` | `INCOMPLETE` |
| yes | any row not `is_complete` (blocked, incomplete or not started) | `INCOMPLETE` |
| yes | otherwise | `COMPLETE` |

So an empty collection the user has declared done is `COMPLETE` when
`min_items` is `0` ("any other income?") and `INCOMPLETE` when it is `1`. A
user can answer *no more* while an item sits half-finished — the page only
shows the question beside the rows — and the honest report is then
*Incomplete*, not *Complete* over answers nobody gave.

Each row's status is `HubMixin.get_member_status()`: `BLOCKED` if
`member_blocked()`, else `COMPLETE` if a stash exists under the item's full
key, else `INCOMPLETE` if a recorded run holds at least one submission, else
`NOT_STARTED`. A seeded item whose run the storage has forgotten reads as
not started — it still has a row, because a row exists from the moment the
item is registered.

### `Collection`

A frozen dataclass and a `gandalf.hubs.Hub`. What the page and a parent
hub's row both read.

**Attributes**

| Attribute | Type | Meaning |
| --- | --- | --- |
| `rows` | `tuple[CollectionRow, ...]` | one per item, in the order the user added them |
| `status` | `str` | `NOT_STARTED`, `INCOMPLETE` or `COMPLETE` |
| `status_label` | `str` | display text for `status` |
| `key` | `str` | the collection key |
| `url` | `str` | the page's own URL |
| `declared_done` | `bool` | whether the user has said there are no more to add |
| `min_items` | `int` | the view's `min_items` |
| `count` | `int` | `len(rows)` |
| `completed` | `int` | rows that `is_complete` |
| `remaining` | `int` | `count - completed`, blocked rows included |
| `blocked` | `int` | rows that `is_blocked` |
| `is_empty` | `bool` | no rows |
| `is_not_started` / `is_incomplete` / `is_complete` | `bool` | status tests |

### `CollectionRow`

A frozen dataclass and a `gandalf.hubs.MemberRow`. One item.

**Attributes**

| Attribute | Type | Meaning |
| --- | --- | --- |
| `member` | `Member` | the underlying member (`member.key` is the item id) |
| `item_id` | `str` | the item's uuid |
| `position` | `int` | zero-based index in the registry |
| `title` | `str` | the title cached when the item last finished, else a positional name |
| `status` | `str` | `NOT_STARTED`, `INCOMPLETE`, `COMPLETE` or `BLOCKED` |
| `status_label` | `str` | display text |
| `url` | `str` | the *Change* link: this page's door for the item |
| `remove_url` | `str` | the *Remove* link: the confirmation route |
| `key` | `str` | `member.key`, the item id |
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

### `ItemMemberMixin`

Mix into the `WizardViewSet` that collects one item. Everything
[`WizardMemberMixin`](hubs.md) does, keyed per item instead of per class: the
key comes from the URL, so the wizard must be mounted under an item segment.

```python
class BudgetLineViewSet(ItemMemberMixin, WizardViewSet):
    url_name = "budget-line"
    collection_key = "budget"
    hub_url_name = "budget"
    item_title_step = "line"
    item_title_field = "item"
    wizard = Wizard().step(BudgetLineForm, name="line").step(ReviewStepView, name="review")
```

**Attributes**

| Attribute | Default | Meaning |
| --- | --- | --- |
| `collection_key` | `None` | The collection page's `member_key` — the full key when the collection is itself nested under a hub. **Required.** |
| `hub_url_name` | `None` | The collection page's `url_name`. **Required** — it is where a finished or unavailable item returns to. |
| `item_url_kwarg` | `"item"` | The URL kwarg carrying the item id. |
| `item_title_step` / `item_title_field` | `None` | The step and field whose answer names the item on the page. Both required unless `get_item_title()` is overridden. |
| `dynamic_member_key` | `True` | Declares that `member_key` is derived per request. |
| `journey_store_class` | `SessionCollectionStore` | |
| `member_label` | `None` | Bump to refuse stashes from an older shape; must match the collection's `item_label`. |

**What it adds over `WizardMemberMixin`**

| Hook | Behaviour |
| --- | --- |
| `get_collection_key()` | `collection_key`, or `ImproperlyConfigured` |
| `get_item_id()` | `self.kwargs["item"]` as a string, or `ImproperlyConfigured` when not mounted under an item segment |
| `get_member_key()` | `"<collection_key>:<item_id>"` — the same string the page's `full_key()` composes |
| `default_member_label()` | the *collection's* key, not the item's, so every item stamps one label |
| `get_item_title(bound_wizard)` | `str(cleaned_data.get(item_title_field, ""))` from the step named `item_title_step`; `""` when that step is not on the route taken. `ImproperlyConfigured` (*"cannot name its items"*) when either attribute is `None`. Costs one walk, once, at completion |
| `run_recorded(bound_wizard, store, key)` | caches `get_item_title()` (an empty title is stored as `None`) inside the window where the run's answers are still readable |
| `get_hub_url_kwargs()` | `get_url_kwargs()` without `item` — the collection page has no place for the item segment; a journey or tenant prefix is forwarded |
| `run_unavailable(bound_wizard, reason)` | redirect to the collection page rather than this wizard's start URL, which would mint a run for an item that may no longer exist |
| `dispatch()` | refuses any request for an item the registry does not list, before `WizardViewSet` sees it, with `item_unavailable()` |
| `item_unavailable()` | redirect to the collection page; override to raise `Http404` |

**Caveats**

- Override `run_done()`, never `done()`: `done()` is also where the title is
  cached, and an item that never caches one leaves a page that can only ever
  say *Budget line 1*, *Budget line 2*.
- Every item runs through the same viewset, so `blocked()` and `hidden()`
  tell items apart by `member.url_kwargs["item"]`.

### `ItemNotFound(LookupError)`

Raised by `CollectionMixin.get_item(item_id)` when the id names no item that
`get_item_ids()` lists — a removed item, a stale link, a URL typed by hand.
`CollectionView` catches it on both item routes and answers
`member_unavailable()`.

### Mounting

A collection page, its item wizard, the hub that lists the collection and
the hub's other members are **four siblings**:

```python
urlpatterns = [
    path("apply/", include(ApplicationHubView.urls())),
    path("apply-project/", include(ProjectMemberViewSet.urls())),
    path("apply-budget/", include(BudgetCollectionView.urls())),
    path("apply-budget-line/<uuid:item>/", include(BudgetLineViewSet.urls())),
]
```

Nesting fails silently, both ways:

- `HubView` publishes `<slug:member>/`, which matches any single segment. A
  collection mounted at `apply/budget/` occupies the exact path of the hub's
  door for a member named `budget`.
- `WizardViewSet.urls()` publishes `""` as its start URL. An item wizard
  mounted at `apply-budget/<uuid:item>/` occupies the exact path of the
  collection's door for that item.

Whichever `include()` is listed first wins, and the symptom is *Change
stopped working* rather than anything that looks like a URL conflict. Under a
journey the same four are mounted under `<slug:journey>/` each, with the
item wizard's segment last: `apply-budget-line/<slug:journey>/<uuid:item>/`.

### Configuration checks

`get_collection()` (and so every render, door and submit) raises
`ImproperlyConfigured` when:

- `member_key` is `None` — *"has no collection to list"*;
- `item_viewset` is `None` — *"has no wizard to collect an item with"*;
- the item viewset's `collection_key` is set and is not this page's key —
  its items would register under one prefix and stash under another, so a
  finished item never shows as complete;
- the item viewset's `member_label` is set and is not `get_item_label()` —
  a re-opened item would be refused at the door and could never be changed.

`declare_done()` on a complete collection with no `hub_url_name` raises
*"has nothing to do when its journey is submitted"* unless `journey_done()`
is overridden.

### Storage

`SessionCollectionStore` (in `gandalf.storage`) is a `SessionJourneyStore`
plus a `"collections"` mapping on the journey's record:

```python
{"collections": {"budget": {"items": [{"id": "<uuid>", "title": "Paint"}, ...],
                            "declared_done": False}}}
```

The registry is explicit because the stash key space cannot stand in for
it: stashes hold only items that have *finished*, in the order they finished.
An item's run and stash live under the ordinary member key `budget:<uuid>`,
composed by the view — the store never learns the scheme, so a hub store and
a collection store share one key space.

`gandalf.types.CollectionStore` is what `journey_store_class` must provide
beyond a `JourneyStore`:

| Method | Contract |
| --- | --- |
| `item_ids(key) -> list[str]` | in the order added; `[]` for a collection never started |
| `has_item(key, item_id) -> bool` | |
| `add_item(key, item_id)` | append; an id already listed is a no-op |
| `remove_item(key, item_id)` | forget the item and its title, keeping the order of the rest; idempotent |
| `get_item_title(key, item_id) -> str \| None` | `None` until the item has finished |
| `set_item_title(key, item_id, title)` | `None` clears; an unlisted id is ignored |
| `is_declared_done(key) -> bool` | `False` until set |
| `set_declared_done(key, declared_done)` | |

Completing the journey takes the registry with it. Test helpers
`seed_collection_item()` and `stored_collection_items()` live in
`gandalf.testing` — see [Testing](testing.md).

### Why a collection and not `.expand()`

`Wizard.expand()` grows *steps* inside one run from a count the user just
gave. Its answers are positional, so deleting from the middle shifts every
answer after it; and one run means there is no such thing as a half-finished
item. A collection's identity is opaque — remove from the middle and the
survivors keep their ids, their URLs and their answers — and every item is
its own run, separately resumable, completable and destroyable. Use
`.expand()` for "how many trustees? now name each"; use a collection for
"add as many as you like, and change your mind later".

---

## Usage

### A budget the applicant grows

```python
from gandalf.collections import CollectionView, ItemMemberMixin
from gandalf.hubs import HubView, Member, WizardMemberMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class BudgetLineViewSet(ItemMemberMixin, WizardViewSet):
    url_name = "budget-line"
    template_name = "grants/step.html"
    collection_key = "budget"
    hub_url_name = "budget"
    item_title_step = "line"
    item_title_field = "item"
    wizard = (
        Wizard()
        .step(BudgetLineForm, name="line", label="Budget line")
        .step(ReviewStepView, name="review")
    )


class BudgetCollectionView(CollectionView):
    template_name = "grants/budget.html"
    remove_template_name = "grants/budget_remove.html"
    url_name = "budget"
    member_key = "budget"
    item_viewset = BudgetLineViewSet
    item_name = "Budget line"
    item_reopen_step = "review"
    min_items = 1
    hub_url_name = "application-hub"


class ApplicationHubView(HubView):
    template_name = "grants/hub.html"
    url_name = "application-hub"
    member_url_name = "application-hub-member"
    members = [
        Member("project", ProjectMemberViewSet, title="Project", reopen_step="review"),
        Member("budget", BudgetCollectionView, title="Budget"),
    ]
```

The hub's `Budget` row links straight at the collection page and reads the
collection's own declared status.

### The page template

```django
{% if collection.is_empty %}
  <h1>You have not added any budget lines</h1>
{% else %}
  <h1>You have added {{ collection.count }} budget line{{ collection.count|pluralize }}</h1>
  <p>You have completed {{ collection.completed }} of {{ collection.count }}.</p>
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

The confirmation page gets `row` as well:

```django
<h1>Are you sure you want to remove {{ row.title }}?</h1>
<form method="post">
  {% csrf_token %}
  <button type="submit">Remove {{ row.title }}</button>
</form>
<a href="{{ collection.url }}">Cancel</a>
```

### Saving each line, and deleting it on removal

```python
from django.shortcuts import redirect

from gandalf.collections import CollectionView, ItemMemberMixin
from gandalf.viewsets import WizardViewSet


class BudgetLineViewSet(ItemMemberMixin, WizardViewSet):
    ...

    def run_done(self, bound_wizard):
        line = bound_wizard.path.find_step(name="line").form.cleaned_data
        BudgetLine.objects.update_or_create(
            item_id=self.get_item_id(),
            defaults={"item": line["item"], "cost": line["cost"]},
        )
        return super().run_done(bound_wizard)


class BudgetCollectionView(CollectionView):
    ...

    def item_removed(self, item_id, member, store):
        BudgetLine.objects.filter(item_id=item_id).delete()
```

`item_removed()` runs before the registry entry goes, so a delete that
raises leaves the line listed and removable.

### Naming an item from more than one field

```python
class TrusteeViewSet(ItemMemberMixin, WizardViewSet):
    collection_key = "trustees"
    hub_url_name = "trustees"

    def get_item_title(self, bound_wizard):
        step = bound_wizard.path.find_step(name="name")
        if step is None:
            return ""
        data = step.form.cleaned_data
        return f"{data['first_name']} {data['last_name']}"
```

Returning `""` lets the row fall back to `Trustee 2` rather than inventing a
name.

### Gating every item until the project is described

```python
class BudgetCollectionView(CollectionView):
    ...

    def member_blocked(self, member, store):
        return not store.has_stash("project") or super().member_blocked(member, store)
```

Blocked rows read *Cannot start yet*, the door refuses them, and *Add
another* still registers a row — the user is returned to the page with a
listed, removable, not-started item.

---

## Troubleshooting

### Clicking Change lands on the wizard's start page, or on the wrong item's step

The item wizard is mounted under the collection's prefix
(`budget/<uuid:item>/`), so its start URL and the collection's door share a
path, and whichever `include()` came first is answering. Mount the wizard
beside the collection: `budget-line/<uuid:item>/`.

### The hub's Budget row links to a member door, not the collection page

The collection is mounted under the hub (`apply/budget/`), where the hub's
`<slug:member>/` door matches first. Mount it as a sibling.

### A finished item stays Incomplete

`collection_key` on the item viewset disagrees with the page's `member_key`,
so the item stashed under one prefix and the page reads another. The check
in `_validate_members()` raises `ImproperlyConfigured` for this when
`collection_key` is set; it cannot catch a viewset that leaves it `None` and
overrides `get_collection_key()`.

### I said No and the page came straight back instead of continuing

`submit()` was refused with `hub_incomplete()`: an item is unfinished, or
there are fewer than `min_items`. The declaration was still recorded, so
finishing the item (or adding one) and pressing *Continue* again completes
the collection. Override `hub_incomplete()` to render the page with an
explanation instead of a bare redirect.

### `ImproperlyConfigured: ... has nothing to do when its journey is submitted`

The collection has no `hub_url_name`, so it is a root and *Continue* ends
the journey. Either set `hub_url_name` to the hub that lists it, or override
`journey_done(hub, store)`.

### A POST to `<url_name>-item` returns 405

By design. The door is GET-only so that a form posting to the URL its own
row links to cannot remove the item it meant to open. Removal is
`<url_name>-remove`, and only that route destroys anything.

### `ImproperlyConfigured: ... cannot name its items`

The item finished and `run_recorded()` asked for a title, but neither
`item_title_step`/`item_title_field` nor a `get_item_title()` override is in
place. Set both attributes, or override the method.

### `ImproperlyConfigured: ... is not mounted under an item segment`

The item wizard is mounted without `<uuid:item>/` in its path, so no request
can say which item it is answering.

### Removing an item took the user to the page, but its wizard URL still works

It should not: `ItemMemberMixin.dispatch()` refuses any request for an
unregistered item with `item_unavailable()`. If the wizard is reachable,
it is a `WizardViewSet` without `ItemMemberMixin`, or its `collection_key`
names a different collection.

### `ImproperlyConfigured: Set ... remove_template_name`

The remove route was reached and there is no confirmation page to render.
Set `remove_template_name`.

---

**Learn:** [Chapter 12 — Collections: add another](../learn/12-collections.md) · **Related:** [Hubs](hubs.md), [Journey store](journey-store.md), [Stashing](stashing.md), [Testing](testing.md), [`WizardViewSet`](viewsets.md)
