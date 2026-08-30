# Task lists

`gandalf.tasklists` — a page of sections the user finishes in any order,
and the journey their answers add up to.

```python
from gandalf.tasklists import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    AddAnother,
    Entry,
    EntryNotFound,
    Group,
    Journey,
    Link,
    Row,
    Section,
    SectionViewSet,
    TaskList,
    TaskListPage,
    TaskListViewSet,
)
```

A task list is declared as a class body — a set of entries, in the order
the page lists them — and mounted by a viewset. The same split a wizard
has: `TaskList` is a value, `TaskListViewSet` is the view. An entry carries
*facts* (a title, where a finished section re-opens); the thing in its
slot carries *behaviour* — a `Wizard`, which the library wraps in a
`SectionViewSet`, or your own `SectionViewSet` subclass — the same rule a
`Form` and a `FormView` follow.

The viewset renders one `Row` per entry — title, status, one URL — wrapped
in a `TaskListPage` that says how far the whole page has got. A row costs
two storage reads and a `reverse()`, never a walk; the walk happens once,
on the way in, for the one section the user clicked. The viewset owns the
URL tree beneath its page: every entry is mounted under it, keyed and
pointed back at it by construction. Everything a page keeps lives in a
journey store scoped to one *journey* — see [Journey store](journey-store.md).
A group is a key namespace over the same record, and only the root ends
the journey.

---

## Reference

### Status constants

| Constant | Value | Label (`get_status_label()`) |
| --- | --- | --- |
| `NOT_STARTED` | `"not-started"` | Not started |
| `INCOMPLETE` | `"incomplete"` | Incomplete |
| `COMPLETE` | `"complete"` | Complete |
| `BLOCKED` | `"blocked"` | Cannot start yet |

Plain strings, so a template can compare them and render them directly
(`tag--{{ row.status }}`).

How an entry's status is derived, in precedence order:

| Checked | Result |
| --- | --- |
| The section's `hidden()` (or the page's `entry_hidden()`) is true | The entry is not in `tasklist.rows` at all — hidden outranks everything |
| The entry is a `Link` | Whatever its `status` callable returns; nothing below runs |
| The section's `blocked()` (or the page's `entry_blocked()`) is true | `BLOCKED` — outranks a stash, so a section whose prerequisite was withdrawn after it was answered reports what the user can do now |
| The entry is a group or an add-another | That page's `status_for()` — derived from its own rows |
| A stash is held under the entry's full key | `COMPLETE` — the section ran to its own end and its answers were stashed |
| A run is recorded for the entry and its state holds at least one answer | `INCOMPLETE` |
| Everything else | `NOT_STARTED` — including a run opened and never answered, and a recorded run the storage has forgotten or tombstoned |

Whether stored answers still *validate* is never asked; it would cost a
form `clean()` per answered step and would not change the row.

### `TaskList`

What a task list is: its entries, in order. A value, not a view.

```python
class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details", reopen="review")
    address = Section(address, title="Address", reopen="review")
```

The attribute name is the entry's key — the URL segment it is mounted at
and, once prefixed by any group above (`full_key()`), the key its run and
stash are kept under. The body's order is the page's order, the way a
form's fields are. A subclass inherits its base's entries and may add to
them.

- `entries` — `{key: Entry}` in definition order, unbound.
- `viewset` — the `TaskListViewSet` that mounted this list, once one has.
- `begin(request, journey=None, **url_kwargs)` *(classmethod)* — begin a
  journey on this list through its viewset; see `Journey` below. Raises
  `ImproperlyConfigured` (*"… is not mounted"*) until a viewset declares
  `tasklist = …`.

### Entries

Every entry is a frozen dataclass with `title` and `label`, and, once the
page has built it, `key` and `viewset`. The key is the attribute name the
entry is declared under, unless `key=` is given — the key is also the URL
segment, and an attribute name cannot carry a hyphen, so
`match_funding = Section(..., key="match-funding")` is how that section
gets the URL it should. Two entries under one key raise
`ImproperlyConfigured`. `title` is what the row renders;
default: the key made readable (`"home_address"` → `"Home address"`).
`label` is the label the entry's stash is expected to carry, checked when
the stash is re-opened; default: the full key. Bump it when a deploy
reshapes the wizard so an old-shape payload is refused rather than walked
into a tree it no longer fits.

#### `Section(wizard, *, title=None, reopen=None, label=None)`

A wizard the user finishes on its own and can come back to.

- `wizard` — a `Wizard` or `ConfiguredWizard`; or a `SectionViewSet`
  subclass, for a section with behaviour: `run_done()` when it finishes,
  `blocked()` / `hidden()` for when it may be opened, `run_started()`, a
  per-request `get_wizard()`. A viewset's own `template_name` and `wizard`
  are used as declared.
- `reopen` — the step a completed section re-opens at. Default `None`: the
  first step on the route.

#### `AddAnother(wizard, *, title=None, item_name=None, item_title=None, min_items=0, reopen=None, label=None, template_name=None, remove_template_name=None)`

A list the user grows, one run of `wizard` per item. The row links straight
at the list's page and reads its declared status. The keyword arguments
are [Add another](add-another.md)'s.

#### `Group(tasklist, *, title=None, template_name=None)`

A task list within this one. Its sections are keyed under this entry's key
in the same journey record, its row here reads its own rows' status, and
its Continue returns here rather than ending anything. `template_name` is
the group's page — a group has no viewset of its own to set one on.

#### `Link(url_name, *, title=None, status)`

A row that links somewhere the task list does not run — a payment page, a
page in another app. `status` is `callable(request, url_kwargs) -> str`,
handed `entry_url_kwargs()`, and is required: without it the page would
derive a status from a stash key nothing writes. `ImproperlyConfigured`
at declaration otherwise.

#### `Entry`

The base. `bound(key, viewset=None)` returns the entry with its key and
viewset set — what `TaskListViewSet.materialise()` does. `reopen_step`,
`url_name` and `status` are properties every kind answers (a `Section`'s
`reopen`, a `Link`'s target and callable, `None` elsewhere), so the page
reads one shape. `url_kwargs` are the extra kwargs an entry's own URLs take
beyond the page's — an item's id.

### `TaskListViewSet`

The page listing a `TaskList`'s entries, the door into each, and the whole
URL tree beneath the page. Set `tasklist` and `url_name`; the entries,
their viewsets, their keys, their return URLs and their routes are built
when the class is created.

```python
class GrantApplicationViewSet(TaskListViewSet):
    template_name = "grant/tasklist.html"
    section_template_name = "grant/step.html"
    url_name = "grant"
    tasklist = GrantApplication
```

**Attributes**

| Attribute | Default | Meaning |
| --- | --- | --- |
| `tasklist` | `None` | The `TaskList`. Required. |
| `url_name` | `None` | The page's URL name, and the prefix of every name beneath it. Required. |
| `template_name` | — | The page (from `TemplateView`). |
| `section_template_name` | `None` | The template this list's sections render with when their `Wizard` carries none. |
| `storage_class` | `SessionStorage` | The run storage every section of the tree uses. |
| `journey_store_class` | `SessionCollectionStore` | The store the journey's bookkeeping lives in, for the whole tree. Must satisfy `gandalf.types.JourneyStore` — `CollectionStore` if the tree has an add-another. |
| `add_another_viewset_class` | `None` | The base every add-another page in the tree is built on; `None` means `AddAnotherViewSet`. |
| `journey` | `"default"` | The fixed journey used when the URL carries none. |
| `journey_url_kwarg` | `"journey"` | The URL kwarg the journey is read from when mounted under one. |
| `key_separator` | `":"` | What joins a group's prefix to an entry's key. |
| `key` | `None` | The prefix this page keys its entries under — set by the parent on a group's page; `None` at the root. |
| `tasklist_url_name` | `None` | The URL name of the page above — set by the parent on a group's page; `None` at the root. |
| `entry_url_kwarg` | `"entry"` | The URL kwarg the door reads the entry key from. |
| `page_context_name` | `"tasklist"` | Where the `TaskListPage` lands in the context. `None` publishes nothing. |
| `entries` | `[]` | The entries, bound. Read through `get_entries()`. |

A subclass with a task list and a `url_name` is materialised when the
class is created, and again on any further subclass — so a subclass that
swaps `storage_class` or `journey_store_class` gets sections on the same
stores, and one that changes `url_name` gets URL names derived from the new
one. A root viewset registers itself as its list's `viewset`, which is what
`TaskList.begin()` goes through.

**What is generated.** For each entry of the list, in order:

| Declared as | Built | URL name | Mounted at |
| --- | --- | --- | --- |
| `Section(wizard)` | a `SectionViewSet` subclass with the wizard, the full `key`, `tasklist_url_name` and the stores | `<url_name>-<key>`; its runs `-run` and `-step` | `<key>/` — the bare URL is this page's door for the section; `<key>/<uuid:run_id>/…` is the run |
| `AddAnother(wizard, …)` | an `AddAnotherViewSet` subclass with the entry, the full `key` and the stores | `<url_name>-<key>`; its item `-item`, `-remove`, `-item-run`, `-item-step` | `<key>/` — the list's page |
| `Group(tasklist)` | a subclass of **this** viewset class over the group's list, with the full `key` and `tasklist_url_name` | `<url_name>-<key>`, and `<url_name>-<key>-<subkey>` beneath it | `<key>/` — the group's page |
| `Link(url_name, status=…)` | nothing | — | — |

A group's page is a subclass of its root, so an override on the root — a
status label, a title rule, `stash_unusable()` — applies to the whole tree.
`journey_done()` and `submitted()` are the root's alone: a group's page
never runs them.

- `urls()` *(classmethod)* — requires `url_name`. Publishes the page, then
  every entry's routes under its segment, then the door last:

  | Pattern | Name |
  | --- | --- |
  | `""` | `<url_name>` — the page |
  | `<key>/…` | each entry's routes, in declaration order |
  | `<slug:entry>/` | `<url_name>-entry` — the door |

  The door comes last so an entry's own segment — a group's page, an
  add-another page — is reached directly, and a section's segment is
  published as the door under the section's own URL name.

- `viewset_for(key)` *(classmethod)* — the generated viewset behind one
  entry, for a test or a driver that needs to address it directly. Raises
  `EntryNotFound`.
- `begin(request, journey=None, **url_kwargs)` *(classmethod)* — a
  `Journey` on this page; see below.
- `declared_entries()` *(classmethod)* — `tasklist.entries`, or `None`.
- `materialise()` / `materialise_entry()` / `build_section()` /
  `build_add_another()` / `build_group()` *(classmethods)* — the
  generation, one hook per kind, for a subclass that needs a different base.

**Identity and nesting**

- `get_key()` — `key`; `None` for a root.
- `is_nested` — property; `tasklist_url_name is not None`.
- `full_key(entry)` — the entry's key in the store: `entry.key` under a
  root, `compose_key(key, entry.key)` under a group. Every read and write
  about an entry goes through here.
- `stash_label(entry)` — `entry.label`, or `full_key(entry)`.
- `status_for(request, url_kwargs)` *(classmethod)* — this page's status
  as a row on the page above, built from its own rows under the given URL
  kwargs. Costs this page's rows' storage reads; still no walk.
- `is_group(entry)` *(staticmethod)* — whether `entry.viewset` is a
  `TaskListViewSet` (an add-another page is one).

**The journey**

- `get_journey()` — the URL's `journey_url_kwarg` when present, otherwise
  `journey`, as a string.
- `get_journey_store()` — `journey_store_class(WizardContext.from_request(request), get_journey())`.
- `get_tasklist_url()` — `reverse(tasklist_url_name, kwargs=get_tasklist_url_kwargs())`,
  the page *above*. Raises `ImproperlyConfigured` when `tasklist_url_name`
  is `None`.
- `dispatch()` — reads `store.is_complete()` once per request. For a
  submitted journey a group's page redirects to the page above, and the
  root returns `submitted(store)`, instead of dispatching.

**Entries**

- `get_entries()` — the entries in display order. Default:
  `list(entries)`; `ImproperlyConfigured` when there is no task list.
  Override to choose among them per request (by user, plan, feature flag).
- `get_entry(key)` — the listed entry `key` names, after hiding. Raises
  `EntryNotFound`.
- `entry_url_kwargs(entry)` — `{**get_page_url_kwargs(), **entry.url_kwargs}`;
  what an entry's view is run, reversed and asked with. Every entry is
  mounted beneath the page, so the page's own kwargs — a tenant prefix, the
  journey — reach every URL the page builds without being declared.
- `entry_viewset(entry)` — `entry.viewset` narrowed to a wizard viewset.

**The page**

- `get_page()` — `TaskListPage(rows, status, status_label)`.
- `get_page_status(rows)` — see `TaskListPage` below. Override where an
  optional section should not hold the page back.
- `get_rows()` — the rows, built once per request and cached on the view
  instance.
- `build_rows()` / `build_row(entry, store)` — what `get_rows()` builds.
- `get_entry_status(entry, store)` — the derivation table above.
- `entry_blocked(entry, store)` — the section viewset's `blocked(store)`;
  `False` for an entry with none. Override for a rule spanning rows, or
  one that needs `self.request`; an override *replaces* the section's own
  answer, so call `super()` where it should still count.
- `entry_hidden(entry, store)` — the mirror, asking `hidden(store)`.
- `get_entry_state(entry, store)` — the raw state list of the entry's
  recorded run, read straight off its `storage_class`; `[]` with no run or
  a forgotten one.
- `get_entry_title(entry)` — `entry.title`, or the key with `_` and `-`
  turned to spaces and its first letter capitalised.
- `get_status_label(status)` — the wording in the constants table, via
  `gettext`. Override to reword.
- `get_entry_url(entry)` — a group or add-another links to its own page; a
  link to its `url_name`; a section to the door:
  `reverse(entry_url_name, kwargs={**get_page_url_kwargs(), entry_url_kwarg: entry.key})`.
- `get_page_url_kwargs()` — everything the request captured except
  `entry_url_kwarg`; used for the page's own URLs.
- `get_page_url()` — `reverse(url_name, kwargs=get_page_url_kwargs())`,
  this page. Not `get_tasklist_url()`, which is the page *above*.
- `get_tasklist_url_kwargs()` — `get_page_url_kwargs()`; a group's page
  and its parent share a mount.
- `get_context_data(**kwargs)` — adds `get_page()` under
  `page_context_name`.

**The door**

- `enter(entry)` — the URL that puts the user inside the entry, or `None`
  when there is nowhere to send them. In order: `None` for a link; `None`
  when `get_entry_status()` is `BLOCKED`; a group's page URL;
  `resume_section()` → `entry_url()`; `reopen_section()` →
  `entry_url(entry.reopen_step)` (an `InvalidStash` goes to
  `stash_unusable()`); else `start_section()` → `entry_url()`. Re-opened
  and started runs are recorded with `store.set_run(full_key(entry), run_id)`.
  Every arm ends at a step URL, never a bare run URL — a run whose every
  answer validates completes on a GET.
- `resume_section(entry, store)` — the section's live run via
  `viewset.inspect()`, or `None` with no recorded run, a run storage no
  longer holds, or a tombstoned one. Tried before re-opening so at most one
  live run per section exists.
- `reopen_section(entry, store)` — a fresh run seeded from the stash via
  `viewset.reopen(request, payload, expected_label=stash_label(entry), **entry_url_kwargs)`,
  or `None` with nothing stashed. The stash is read, never popped.
- `start_section(entry)` — `viewset.begin(request, **entry_url_kwargs)`.
- `stash_unusable(entry, error)` — called with the `InvalidStash`. Default
  re-raises. Override to delete the stash and `enter()` again, or return a
  URL that explains; returning `None` lands on `entry_unavailable()`.
- `entry_unavailable(key)` — the response for a key the page will not open
  (unknown, hidden, blocked, or nowhere to go). Default
  `redirect(get_page_url())`. Override to raise `Http404`.

**The ending**

- `submit()` — refuses with `page_incomplete(page)` unless
  `page.is_complete`. A group's page returns `group_done(page, store)` and
  tears nothing down. A root runs `response = journey_done(page, store)`,
  then `store.complete()`, then returns the response — so a
  `journey_done()` that raises leaves every section resumable, and it runs
  while the stashes are still readable.
- `group_done(page, store)` — a group's Continue. Default
  `redirect(get_tasklist_url())`.
- `journey_done(page, store)` — the root's submit. No default: raises
  `ImproperlyConfigured` (*"… has nothing to do when its journey is
  submitted"*). Anything the done page needs goes into `store.data`, which
  the tombstone keeps.
- `page_incomplete(page)` — default `redirect(get_page_url())`.
- `submitted(store)` — the page a submitted journey shows, for the root's
  page and every door beneath it. Raises `Http404` by default. Override to
  render a done page from `store.data`.

**HTTP**

- `get()` — without an entry kwarg, renders the page. With one:
  `get_entry(key)` (`EntryNotFound` → `entry_unavailable()`), then
  `enter(entry)` (`None` → `entry_unavailable()`), else `redirect(url)`.
- `post()` — on the page, `submit()`. On the door, `405 Method Not Allowed`
  (`GET` only): the route that opens a section never finishes anything.

### `SectionViewSet`

The viewset a task list runs a section with. A `Section(wizard)` gets one
built for it; a section with behaviour declares its own subclass and puts
that in the slot instead:

```python
class ProjectSection(SectionViewSet):
    wizard = project

    def run_done(self, run):
        record_amount(self.get_journey_store(), run)
        return super().run_done(run)

    @classmethod
    def hidden(cls, store):
        return store.data.get("amount", 0) <= 10_000
```

Nothing about the task list changes between the two. Reach a built one
with `viewset_for(key)`.

**Attributes** — `tasklist_viewset` (the page that built it), `key` (the
full key), `tasklist_url_name`, `label`, and the journey and store
attributes of its page.

**Methods**

- `blocked(store)` / `hidden(store)` *(classmethods)* — whether the
  section is listed but locked, or not listed at all, for this request.
  `False` by default. One read of the store each: use `store.data` and
  `store.has_stash()`, never a stash's state — they run inside the row's
  no-walk promise. Classmethods because the page asks before any instance
  exists; a rule that needs the request goes on the page's
  `entry_blocked()` / `entry_hidden()` instead.
- `get_key()` / `get_label()` / `default_label()` — the key, and the label
  stamped into the stash (`label`, else the key).
- `get_tasklist_url_kwargs()` — the wizard's own `get_url_kwargs()`, the
  journey and any mount prefix among them.
- `done(run)` — in order: `store.put_stash(key, run.stash(label=...))`;
  `run_recorded(run, store, key)`; `response = run_done(run)`;
  `store.clear_run(key)`; return the response. A `run_done()` that raises
  leaves the run id in place, so the section stays resumable.
- `run_recorded(run, store, key)` — library-side bookkeeping that
  must read the finished run, inside the window where the run's state is
  still readable. A plain section records nothing; an item caches its
  title.
- `run_done(run)` — what the section does when it finishes,
  beyond being recorded. Runs on every completion — the first and each
  re-save — after the stash is written. Write what the rest of the journey
  needs into `store.data` here; the run is still readable. Default
  `redirect(get_tasklist_url())`.
- `dispatch()` / `submitted(store)` — a bookmarked run URL under a
  submitted journey is sent back to the page.

Re-opening a completed section seeds a fresh run from its stash with every
answer already valid, so the next successful submission walks to the end
and fires `done()` again — edit-and-re-save. Give the wizard a review step
if the user should get a confirm gate first.

### `Journey`

A journey begun from outside the page's own requests — what a start wizard,
an "apply again" link, a command or an agent uses:

```python
def done(self, run):
    journey = GrantApplication.begin(self.request)
    journey.finish("setup", run)
    return redirect(journey.url)
```

`TaskList.begin()` and `TaskListViewSet.begin()` both return one; the id
is made up when not given, and `url_kwargs` are the page's mount-prefix
kwargs, if any.

**Attributes** — `id`; `store` (the page's `journey_store_class` for this
id); `url` (the page under this id, or the page's one URL for a list not
mounted under a journey segment); `tasklist_viewset`; `request`.

- `finish(section, run)` — record a finished run as `section`,
  exactly as finishing it from the page would: stashed under the section's
  key and label, its `run_done()` run, its run cleared. It arrives on the
  page complete and re-openable like any other row. Raises `EntryNotFound`
  for a key the list does not declare.

### `Row`

One entry as the template sees it. Frozen.

**Attributes** — `entry` (the underlying `Entry`), `status`, `title`,
`status_label`, `url`, and the property `key` (`entry.key`, the short
key). Boolean properties: `is_not_started`, `is_incomplete`,
`is_complete`, `is_blocked`.

### `TaskListPage`

The page as a whole. Frozen.

**Attributes** — `rows` (a tuple of `Row`), `status`, `status_label`.

**Properties**

| Property | Meaning |
| --- | --- |
| `count` | How many entries are listed (hidden ones are not) |
| `completed` | How many rows are `COMPLETE` |
| `remaining` | `count - completed` — a blocked section is still remaining |
| `blocked` | How many rows are `BLOCKED` |
| `is_not_started` / `is_incomplete` / `is_complete` | `status` compared to the constant |

`tasklist.status` comes from `get_page_status()`: `COMPLETE` when there is
at least one row and every row is complete; `NOT_STARTED` when every row
is not started or blocked (so a list listing nothing, or a fresh list with
a locked section, has not started); `INCOMPLETE` otherwise. A blocked row
keeps the page off `COMPLETE` for as long as it is blocked.

### `EntryNotFound`

`LookupError` raised by `get_entry(key)`, `viewset_for(key)` and
`Journey.finish()` when the key names no entry the list has — never
declared, renamed, or hidden for this request. The door turns it into
`entry_unavailable()`.

---

## Usage

### A task list of two sections

```python
from django.urls import include, path

from gandalf.tasklists import Section, TaskList, TaskListViewSet
from gandalf.wizard import Wizard


contact = (
    Wizard()
    .step(ApplicantForm, name="name", label="Your name")
    .step(EmailForm, name="email", label="Email")
    .step(ReviewStepView, name="review")
)

organisation = (
    Wizard()
    .step(OrganisationForm, name="organisation", label="Organisation")
    .step(ReviewStepView, name="review")
)


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details", reopen="review")
    organisation = Section(organisation, title="Your organisation", reopen="review")


class GrantApplicationViewSet(TaskListViewSet):
    template_name = "grant/tasklist.html"
    section_template_name = "grant/step.html"
    url_name = "grant"
    tasklist = GrantApplication


urlpatterns = [path("grant/", include(GrantApplicationViewSet.urls()))]
```

That one `include()` publishes `grant` (the page), `grant-entry` (the
door), `grant-contact` and `grant-organisation` (each section's door under
its own name) and `grant-contact-run` / `grant-contact-step` (the runs).

```django
<p>You have completed {{ tasklist.completed }} of {{ tasklist.count }} sections.</p>
<ul>
{% for row in tasklist.rows %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
</ul>
```

### A section that does something when it finishes

```python
def record_amount(store, run):
    project = run.path.find_step(name="project")
    store.data["amount"] = int(project.form.cleaned_data["amount"])


class ProjectSection(SectionViewSet):
    wizard = project

    def run_done(self, run):
        record_amount(self.get_journey_store(), run)
        return super().run_done(run)


class GrantApplication(TaskList):
    project = Section(ProjectSection, title="Project", reopen="review")
```

The `Section` is unchanged; the richer thing goes in the slot. `run_done()`
runs after the stash is written and before the user is sent back to the
page, on every completion — the first and each re-save.

### A section that unlocks, and one that appears

```python
class RefereesSection(SectionViewSet):
    wizard = referees

    @classmethod
    def blocked(cls, store):            # Cannot start yet
        return not store.has_stash("contact")


class MatchFundingSection(SectionViewSet):
    wizard = match_funding

    @classmethod
    def hidden(cls, store):             # not listed
        return store.data.get("amount", 0) <= 10_000


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details")
    referees = Section(RefereesSection, title="Referees")
    match_funding = Section(MatchFundingSection, title="Match funding")
```

### Ending the journey

```python
from django.shortcuts import redirect, render

from gandalf.tasklists import TaskListViewSet


class GrantApplicationViewSet(TaskListViewSet):
    template_name = "grant/tasklist.html"
    url_name = "apply"
    tasklist = GrantApplication

    def journey_done(self, page, store):
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference   # the tombstone keeps this
        return redirect(self.get_page_url())

    def submitted(self, store):
        return render(self.request, "grant/done.html", {"reference": store.data["reference"]})
```

```django
{% if tasklist.is_complete %}
  <form method="post">{% csrf_token %}<button type="submit">Submit application</button></form>
{% endif %}
```

Mount the page under a journey segment so two applications in two tabs are
two records: `path("apply/<slug:journey>/", include(GrantApplicationViewSet.urls()))`.
Every entry is beneath it, so every entry reads the same segment.

### Beginning a journey from a wizard that has none yet

```python
class ApplicationStartViewSet(WizardViewSet):
    url_name = "apply-start"
    wizard = setup

    def done(self, run):
        journey = GrantApplication.begin(self.request)
        journey.finish("setup", run)
        return redirect(journey.url)
```

Mounted at `apply/new/`, before the journey segment. The same wizard is the
list's `setup` section, so it arrives complete and can be re-opened from
the page. An "apply again" link is `redirect(GrantApplication.begin(request).url)`.

### A task list inside a task list

```python
class SupportingInformation(TaskList):
    referees = Section(RefereesSection, title="Referees")
    documents = Section(DocumentsSection, title="Governing document")


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details")
    supporting = Group(
        SupportingInformation,
        title="Supporting information",
        template_name="grant/supporting.html",
    )
```

The referees section is keyed `"supporting:referees"` in the store, mounted
at `supporting/referees/`, named `apply-supporting-referees`, and returns
to `apply-supporting` when it finishes — none of it typed.

### Wording the statuses for the whole tree

```python
class GrantApplicationViewSet(TaskListViewSet):
    ...

    def get_status_label(self, status):
        if status == BLOCKED:
            return "Locked"
        return super().get_status_label(status)
```

A group's page is a subclass of the root, so the supporting-information
page says *Locked* too.

---

## Troubleshooting

### A section completes but its row still says Not started

The section's viewset overrides `done()`. `SectionViewSet.done()` is what
stashes — put the work in `run_done()` instead.

### Clicking a row starts a fresh run beside the one I was editing

A row links to the page's door, which resumes before it re-opens. If you
overrode `get_entry_url()`, make it reverse `entry_url_name` with
`entry_url_kwarg`, not the section's `-run` pattern.

### `InvalidStash` when re-opening a section

The stash's `label` no longer matches `stash_label(entry)` — the section
was reshaped and `label=` bumped. Override `stash_unusable()` to delete the
stash and `enter()` again, or to send the user somewhere that explains.

### `ImproperlyConfigured: GrantApplicationViewSet has nothing to do when its journey is submitted`

A POST reached a complete root with no `journey_done()`. Override it — a
page with nothing to do at submit should not render a submit button.

### `ImproperlyConfigured: … has no entries to list`

The viewset has no `tasklist`. Set it to a `TaskList`.

### `ImproperlyConfigured: … is not mounted`

`TaskList.begin()` was called before any `TaskListViewSet` declared
`tasklist = …`. Mount the list, or call `begin()` on the viewset.

### `Http404: Journey 'app-1' has been submitted.`

The default `submitted()` on a root. Override it to render a done page from
`store.data`.

### POST to the door returns 405

By design: the door is `GET`-only. Submit by POSTing to the page URL.

---

**Learn:** [Chapter 11 — Task lists](../learn/11-task-lists.md), [Chapter 13 — Blocked and hidden](../learn/13-blocked-and-hidden.md), [Chapter 14 — Journeys](../learn/14-journeys.md) · **Related:** [Journey store](journey-store.md), [Add another](add-another.md), [Stashing](stashing.md), [`WizardViewSet`](viewsets.md), [Run metadata](run-metadata.md)
