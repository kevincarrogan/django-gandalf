# Hubs

`gandalf.hubs` — a page of parallel wizards the user drops in and out of,
and the journey their answers add up to.

```python
from gandalf.hubs import (
    BLOCKED,
    COMPLETE,
    INCOMPLETE,
    NOT_STARTED,
    Hub,
    HubPage,
    HubViewSet,
    Member,
    MemberNotFound,
    MemberRow,
    MemberViewSet,
)
```

A hub is declared the way a wizard is — one immutable `Hub()` value, read
top-down — and mounted once. Each member is a wizard, a collection, another
hub, or a link to a page the hub does not run. `HubViewSet` renders one
`MemberRow` per member — title, status, one URL — wrapped in a `HubPage`
that says how far the whole page has got. A row costs two storage reads and
a `reverse()`, never a walk; the walk happens once, on the way in, for the
one member the user clicked.

The viewset owns the URL tree beneath its page. Every member is mounted
under the hub, keyed and pointed back at it by construction, so nothing is
declared twice. Everything a hub keeps lives in a journey store scoped to
one *journey* — see [Journey store](journey-store.md). Nesting is a key
namespace over the same record, and only the root hub ends the journey.

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

How a member's status is derived, in precedence order:

| Checked | Result |
| --- | --- |
| The member's `hidden` rule (or the hub's `member_hidden()`) is true | The member is not in `hub.rows` at all — hidden outranks everything |
| The member is a link with a `status` callable | Whatever that callable returns; nothing below runs |
| The member's `blocked` rule (or the hub's `member_blocked()`) is true | `BLOCKED` — outranks a stash, so a member whose prerequisite was withdrawn after it was answered reports what the user can do now |
| The member is a hub or a collection | That page's `status_for()` — derived from its own rows |
| A stash is held under the member's full key | `COMPLETE` — the member ran to its own end and its answers were stashed |
| A run is recorded for the member and its state holds at least one entry | `INCOMPLETE` |
| Everything else | `NOT_STARTED` — including a run opened and never answered, and a recorded run the storage has forgotten or tombstoned |

Whether stored answers still *validate* is never asked; it would cost a
form `clean()` per answered step and would not change the row.

### `Hub()`

The declaration: which members a task list has, in what order, and what
each one is. Immutable — every method returns a new `Hub`, so a declaration
can be shared, extended and nested without side effects.

#### `.member(key, wizard, *, title=None, reopen=None, done=None, blocked=None, hidden=None, label=None)`

A wizard the user finishes on its own and can come back to.

- `key` — the member's identity: the URL segment it is mounted at, and,
  once prefixed by any hub above (`full_key()`), the key its run and stash
  are kept under.
- `wizard` — a `Wizard` or `ConfiguredWizard`; or a `WizardViewSet`
  subclass, for a member that needs a hook a declaration cannot carry
  (`run_started()`, a per-request `get_wizard()`). A viewset's own
  `template_name` and `wizard` are used as declared.
- `title` — what the row renders. Default: the key made readable
  (`"home_address"` → `"Home address"`).
- `reopen` — the step a completed member re-opens at. Default `None`: the
  first step on the route.
- `done` — `callable(store, bound_wizard)`, run once per completion —
  including each re-save of a re-opened member — after the stash is written
  and before the user is sent back to the hub. Write what the rest of the
  journey needs into `store.data` here; the run is still readable.
- `blocked` — `callable(store) -> bool`. `True` lists the member locked:
  the row reads **Cannot start yet** and the door refuses it.
- `hidden` — `callable(store) -> bool`. `True` leaves the member out for
  this request: not in the rows, not in the counts, unknown to the door.
- `label` — the label the member's stash is expected to carry, checked
  when the stash is re-opened. Default: the full key. Bump it when a deploy
  reshapes the wizard so an old-shape payload is refused rather than walked
  into a tree it no longer fits.

Both rules are handed the journey's store and nothing else, so they stay
the one read a row can afford: use `store.data` and `store.has_stash()`,
never a stash's state. A rule that needs the request goes on the hub's
`member_blocked()` / `member_hidden()` instead.

#### `.collection(key, collection, *, title=None, blocked=None, hidden=None, **options)`

An *add another* list. `collection` is a
[`Collection`](collections.md), or a wizard together with the `Collection`
keyword arguments to build one from (`item_name=`, `min_items=`, …). Passing
both a `Collection` and options raises `ImproperlyConfigured`. The row links
straight at the collection's page and reads its declared status.

#### `.hub(key, hub, *, title=None, blocked=None, hidden=None)`

A task list within this one. Its members are keyed under `key` in the same
journey record, its row here reads its own rows' status, and its submit
returns here rather than ending anything.

#### `.link(key, url_name, *, title=None, status)`

A row that links somewhere the hub does not run — a payment page, a page in
another app. `status` is `callable(request, url_kwargs) -> str`, handed
`member_url_kwargs()`, and is required: without it the hub would derive a
status from a stash key nothing writes.

#### `.configure(**configuration)`

Page settings for a hub that has no viewset of its own — a nested one:
`template_name` for its page, and `member_template_name`, the template its
wizard members render with unless their `Wizard` carries one. On the root
the same two are class attributes of the viewset.

Duplicate keys raise `ImproperlyConfigured` at declaration.

### `HubViewSet`

The page listing a `Hub`'s members, the door into each, and the whole URL
tree beneath the page. Set `hub` and `url_name`; the members, their
viewsets, their keys, their return URLs and their routes are derived when
the class is created.

```python
class GrantHubViewSet(HubViewSet):
    template_name = "grant/hub.html"
    member_template_name = "grant/wizard.html"
    url_name = "grant"
    hub = Hub().member("contact", contact, title="Contact details", reopen="review")
```

**Attributes**

| Attribute | Default | Meaning |
| --- | --- | --- |
| `hub` | `None` | The declaration. Required. |
| `url_name` | `None` | The page's URL name, and the prefix of every name beneath it. Required. |
| `template_name` | — | The page (from `TemplateView`). |
| `member_template_name` | `None` | The template this hub's wizard members render with when their `Wizard` carries none. |
| `storage_class` | `SessionStorage` | The run storage every wizard member of the tree uses. |
| `journey_store_class` | `SessionCollectionStore` | The store the journey's bookkeeping lives in, for the whole tree. Must satisfy `gandalf.types.JourneyStore` — `CollectionStore` if the tree has a collection. |
| `collection_viewset_class` | `None` | The base every collection in the tree is built on; `None` means `CollectionViewSet`. Set a subclass to give the tree's collections a hook. |
| `journey` | `"default"` | The fixed journey used when the URL carries none. |
| `journey_url_kwarg` | `"journey"` | The URL kwarg the journey is read from when mounted under one. |
| `key_separator` | `":"` | What joins a hub's prefix to a member's key. |
| `member_key` | `None` | The prefix this hub keys its members under — set by the parent on a nested hub; `None` at the root. |
| `hub_url_name` | `None` | The URL name of the hub above — set by the parent on a nested hub; `None` at the root. |
| `member_url_kwarg` | `"member"` | The URL kwarg the door reads the member key from. |
| `hub_context_name` | `"hub"` | Where the `HubPage` lands in the context. `None` publishes nothing. |
| `members` | `[]` | The `Member`s built from the declaration. Read through `get_members()`. |

A subclass with a declaration and a `url_name` is materialised when the
class is created, and again on any further subclass — so a subclass that
swaps `storage_class` or `journey_store_class` gets members on the same
stores, and a subclass that changes `url_name` gets member URL names
derived from the new one.

**What is generated.** For each member of the declaration, in order:

| Declared as | Built | URL name | Mounted at |
| --- | --- | --- | --- |
| `.member(key, wizard)` | a `MemberViewSet` subclass with the wizard, `member_key`, `hub_url_name` and the stores | `<url_name>-<key>`; its runs `-run` and `-step` | `<key>/` — the bare URL is this hub's door for the member; `<key>/<uuid:run_id>/…` is the run |
| `.collection(key, …)` | a `CollectionViewSet` subclass with the `Collection`, `member_key` and the stores | `<url_name>-<key>`; its item `-item`, `-remove`, `-item-run`, `-item-step` | `<key>/` — the collection's page |
| `.hub(key, hub)` | a subclass of **this** viewset class with the nested `Hub`, `member_key` and `hub_url_name` | `<url_name>-<key>`, and `<url_name>-<key>-<subkey>` beneath it | `<key>/` — the nested page |
| `.link(key, url_name, status=…)` | nothing | — | — |

A nested hub is a subclass of its root, so an override on the root — a
status label, a title rule, `stash_unusable()` — applies to the whole tree.
`journey_done()` and `journey_completed()` are the root's alone: a nested
hub never runs them.

- `urls()` *(classmethod)* — requires `url_name`. Publishes the page, then
  every member's routes under its segment, then the door last:

  | Pattern | Name |
  | --- | --- |
  | `""` | `<url_name>` — the page |
  | `<key>/…` | each member's routes, in declaration order |
  | `<slug:member>/` | `<url_name>-member` — the door |

  The door comes last so a member's own segment — a nested hub's page, a
  collection's page — is reached directly, and a wizard member's segment is
  published as the door under the wizard's own URL name.

- `viewset_for(key)` *(classmethod)* — the generated viewset behind one
  member, for a test or a driver that needs to address it directly. Raises
  `MemberNotFound`.
- `declaration()` *(classmethod)* — `hub`.
- `materialise()` / `materialise_member()` / `build_member_viewset()` /
  `build_collection()` / `build_nested_hub()` *(classmethods)* — the
  generation, one hook per kind, for a subclass that needs a different base.

**Identity and nesting**

- `get_member_key()` — `member_key`; `None` for a root hub.
- `is_nested` — property; `hub_url_name is not None`.
- `full_key(member)` — the member's key in the store: `member.key` under a
  root hub, `compose_key(member_key, member.key)` under a nested one. Every
  read and write about a member goes through here.
- `stash_label(member)` — `member.label`, or `full_key(member)`.
- `status_for(request, url_kwargs)` *(classmethod)* — this hub's status as
  a row on the hub above, built from its own rows under the given URL
  kwargs. Costs this hub's rows' storage reads; still no walk.
- `is_hub(member)` *(staticmethod)* — whether `member.viewset` is a
  `HubViewSet` (a collection is one).

**The journey**

- `get_journey()` — the URL's `journey_url_kwarg` when present, otherwise
  `journey`, as a string.
- `get_journey_store()` — `journey_store_class(WizardContext.from_request(request), get_journey())`.
- `get_hub_url()` — `reverse(hub_url_name, kwargs=get_hub_url_kwargs())`,
  the hub *above*. Raises `ImproperlyConfigured` when `hub_url_name` is
  `None`.
- `dispatch()` — reads `store.is_complete()` once per request. For a
  submitted journey a nested hub redirects to the hub above, and the root
  returns `journey_completed(store)`, instead of dispatching.

**Members**

- `get_members()` — the members in display order. Default:
  `list(members)`; `ImproperlyConfigured` when there is no declaration.
  Override to choose among them per request (by user, plan, feature flag).
- `get_member(key)` — the listed member `key` names, after hiding. Raises
  `MemberNotFound`.
- `member_url_kwargs(member)` — `{**get_page_url_kwargs(), **member.url_kwargs}`;
  what a member's view is run, reversed and asked with. Every member is
  mounted beneath the page, so the page's own kwargs — a tenant prefix, the
  journey — reach every URL the hub builds without being declared.
- `member_viewset(member)` — `member.viewset` narrowed to a wizard viewset.

**The page**

- `get_hub()` — `HubPage(rows, status, status_label)`.
- `get_hub_status(rows)` — see `HubPage` below. Override where an optional
  member should not hold the page back.
- `get_member_rows()` — the rows, built once per request and cached on the
  view instance.
- `build_member_rows()` / `build_member_row(member, store)` — what
  `get_member_rows()` builds.
- `get_member_status(member, store)` — the derivation table above.
- `member_blocked(member, store)` — the member's declared `blocked` rule;
  `False` without one. Override for a rule spanning rows, or one that needs
  `self.request`; an override *replaces* the rules, so call `super()` where
  they should still count.
- `member_hidden(member, store)` — the mirror, reading `hidden`.
- `get_member_state(member, store)` — the raw state list of the member's
  recorded run, read straight off its `storage_class`; `[]` with no run or
  a forgotten one.
- `get_member_title(member)` — `member.title`, or the key with `_` and `-`
  turned to spaces and its first letter capitalised.
- `get_status_label(status)` — the wording in the constants table, via
  `gettext`. Override to reword.
- `get_member_url(member)` — a hub or collection member links to its own
  page; a link to its `url_name`; a wizard member to the door:
  `reverse(member_url_name, kwargs={**get_page_url_kwargs(), member_url_kwarg: member.key})`.
- `get_page_url_kwargs()` — everything the request captured except
  `member_url_kwarg`; used for the hub's own URLs.
- `get_page_url()` — `reverse(url_name, kwargs=get_page_url_kwargs())`, this
  hub's own page. Not `get_hub_url()`, which is the hub *above*.
- `get_hub_url_kwargs()` — `get_page_url_kwargs()`; a nested hub and its
  parent share a mount.
- `get_context_data(**kwargs)` — adds `get_hub()` under `hub_context_name`.

**The door**

- `enter(member)` — the URL that puts the user inside the member, or
  `None` when there is nowhere to send them. In order: `None` for a link;
  `None` when `get_member_status()` is `BLOCKED`; a hub member's page URL;
  `resume_member()` → `entry_url()`; `reopen_member()` →
  `entry_url(member.reopen_step)` (an `InvalidStash` goes to
  `stash_unusable()`); else `start_member()` → `entry_url()`. Re-opened and
  started runs are recorded with `store.set_run(full_key(member), run_id)`.
  Every arm ends at a step URL, never a bare run URL — a run whose every
  answer validates completes on a GET.
- `resume_member(member, store)` — the member's live run via
  `viewset.inspect()`, or `None` with no recorded run, a run storage no
  longer holds, or a tombstoned one. Tried before re-opening so at most one
  live run per member exists.
- `reopen_member(member, store)` — a fresh run seeded from the stash via
  `viewset.reopen(request, payload, expected_label=stash_label(member), **member_url_kwargs)`,
  or `None` with nothing stashed. The stash is read, never popped.
- `start_member(member)` — `viewset.begin(request, **member_url_kwargs)`.
- `stash_unusable(member, error)` — called with the `InvalidStash`. Default
  re-raises. Override to delete the stash and `enter()` again, or return a
  URL that explains; returning `None` lands on `member_unavailable()`.
- `member_unavailable(key)` — the response for a key the hub will not open
  (unknown, hidden, blocked, or nowhere to go). Default
  `redirect(get_page_url())`. Override to raise `Http404`.

**The ending**

- `submit()` — refuses with `hub_incomplete(hub)` unless `hub.is_complete`.
  A nested hub returns `hub_done(hub, store)` and tears nothing down. A root
  hub runs `response = journey_done(hub, store)`, then `store.complete()`,
  then returns the response — so a `journey_done()` that raises leaves
  every member resumable, and it runs while the stashes are still readable.
- `hub_done(hub, store)` — a nested hub's submit. Default
  `redirect(get_hub_url())`.
- `journey_done(hub, store)` — the root hub's submit. No default: raises
  `ImproperlyConfigured` (*"… has nothing to do when its journey is
  submitted"*). Anything the done page needs goes into `store.data`, which
  the tombstone keeps.
- `hub_incomplete(hub)` — default `redirect(get_page_url())`.
- `journey_completed(store)` — the root's response after submission, for
  the page and every door beneath it. Raises `Http404` by default. Override
  to render a done page from `store.data`.

**HTTP**

- `get()` — without a member kwarg, renders the page. With one:
  `get_member(key)` (`MemberNotFound` → `member_unavailable()`), then
  `enter(member)` (`None` → `member_unavailable()`), else `redirect(url)`.
- `post()` — on the page, `submit()`. On the door, `405 Method Not Allowed`
  (`GET` only): the route that opens a member never finishes anything.

### `MemberViewSet`

The viewset a hub runs a wizard member with. Built by `HubViewSet` from the
member's declaration — one subclass per member — and never written by hand;
reach one with `viewset_for(key)`.

**Attributes** — `hub_viewset` (the class that built it), `member_key` (the
full key), `hub_url_name`, `member_label`, `member_done` (the declared
`done`), and the journey and store attributes of its hub.

**Methods**

- `get_member_key()` / `get_member_label()` / `default_member_label()` —
  the key, and the label stamped into the stash (`member_label`, else the
  key).
- `get_hub_url_kwargs()` — the wizard's own `get_url_kwargs()`, the journey
  and any mount prefix among them.
- `done(bound_wizard)` — in order: `store.put_stash(key, bound_wizard.stash(label=...))`;
  `run_recorded(bound_wizard, store, key)`; `response = run_done(bound_wizard)`;
  `store.clear_run(key)`; return the response. A `done` that raises leaves
  the run id in place, so the member stays resumable.
- `run_recorded(bound_wizard, store, key)` — library-side bookkeeping that
  must read the finished run, inside the window where the run's state is
  still readable. A plain member records nothing; an item caches its title.
- `run_done(bound_wizard)` — the declared `done`, then
  `redirect(get_hub_url())`.
- `dispatch()` / `journey_completed(store)` — a bookmarked run URL under a
  submitted journey is sent back to the hub.

Re-opening a completed member seeds a fresh run from its stash with every
answer already valid, so the next successful submission walks to the end
and fires `done()` again — edit-and-re-save. Give the wizard a review step
if the user should get a confirm gate first.

### `Member`

One spoke of a hub, as materialised from its declaration. Frozen.

**Attributes** — `key` (relative to the hub that lists it), `viewset` (a
`MemberViewSet`, a `HubViewSet`, or `None` for a link), `title`, `label`,
`reopen_step`, `url_kwargs` (extra kwargs the member's own URLs take beyond
the page's — an item's id), `url_name` and `status` (a link's), `blocked`
and `hidden` (the declared rules). The callables and `url_kwargs` are
excluded from equality and hashing.

### `MemberRow`

One row of the page, as the template sees it. Frozen.

**Attributes** — `member` (the underlying `Member`), `status`, `title`,
`status_label`, `url`, and the property `key` (`member.key`, the short
key). Boolean properties: `is_not_started`, `is_incomplete`,
`is_complete`, `is_blocked`.

### `HubPage`

The page as a whole. Frozen.

**Attributes** — `rows` (a tuple of `MemberRow`), `status`, `status_label`.

**Properties**

| Property | Meaning |
| --- | --- |
| `count` | How many members are listed (hidden ones are not) |
| `completed` | How many rows are `COMPLETE` |
| `remaining` | `count - completed` — a blocked member is still remaining |
| `blocked` | How many rows are `BLOCKED` |
| `is_not_started` / `is_incomplete` / `is_complete` | `status` compared to the constant |

`hub.status` comes from `get_hub_status()`: `COMPLETE` when there is at
least one row and every row is complete; `NOT_STARTED` when every row is
not started or blocked (so a hub listing nothing, or a fresh list with a
locked member, has not started); `INCOMPLETE` otherwise. A blocked row keeps
the hub off `COMPLETE` for as long as it is blocked.

### `MemberNotFound`

`LookupError` raised by `get_member(key)` and `viewset_for(key)` when the
key names no member the hub lists — never declared, renamed, or hidden for
this request. The door turns it into `member_unavailable()`.

---

## Usage

### A task list of two members

```python
from django.urls import include, path

from gandalf.hubs import Hub, HubViewSet
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


class GrantHubViewSet(HubViewSet):
    template_name = "grant/hub.html"
    member_template_name = "grant/wizard.html"
    url_name = "grant"
    hub = (
        Hub()
        .member("contact", contact, title="Contact details", reopen="review")
        .member("organisation", organisation, title="Your organisation", reopen="review")
    )


urlpatterns = [path("grant/", include(GrantHubViewSet.urls()))]
```

That one `include()` publishes `grant` (the page), `grant-member` (the
door), `grant-contact` and `grant-organisation` (each member's door under
its own name) and `grant-contact-run` / `grant-contact-step` (the runs).

```django
<p>You have completed {{ hub.completed }} of {{ hub.count }} sections.</p>
<ul>
{% for row in hub.rows %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
</ul>
```

### Saving on completion and writing a decided fact

```python
def record_amount(store, bound_wizard):
    project = bound_wizard.path.find_step(name="project")
    store.data["amount"] = int(project.form.cleaned_data["amount"])


hub = Hub().member("project", project, title="Project", reopen="review", done=record_amount)
```

`done` runs after the stash is written and before the user is sent back to
the hub, on every completion — the first and each re-save.

### A member that unlocks, and one that appears

```python
hub = (
    Hub()
    .member("contact", contact, title="Contact details")
    .member(
        "referees",
        referees,
        title="Referees",
        blocked=lambda store: not store.has_stash("contact"),   # Cannot start yet
    )
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        hidden=lambda store: store.data.get("amount", 0) <= 10_000,   # not listed
    )
)
```

### Ending the journey

```python
from django.shortcuts import redirect, render

from gandalf.hubs import HubViewSet


class GrantApplicationViewSet(HubViewSet):
    template_name = "grant/hub.html"
    url_name = "apply"
    hub = application

    def journey_done(self, hub, store):
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference   # the tombstone keeps this
        return redirect(self.get_page_url())

    def journey_completed(self, store):
        return render(self.request, "grant/done.html", {"reference": store.data["reference"]})
```

```django
{% if hub.is_complete %}
  <form method="post">{% csrf_token %}<button type="submit">Submit application</button></form>
{% endif %}
```

Mount the hub under a journey segment so two applications in two tabs are
two records: `path("apply/<slug:journey>/", include(GrantApplicationViewSet.urls()))`.
Every member is beneath it, so every member reads the same segment.

### A hub inside a hub

```python
supporting = (
    Hub()
    .member("referees", referees, title="Referees")
    .member("documents", documents, title="Governing document")
    .configure(template_name="grant/supporting.html")
)

application = (
    Hub()
    .member("contact", contact, title="Contact details")
    .hub("supporting", supporting, title="Supporting information")
)
```

The referees member is keyed `"supporting:referees"` in the store, mounted
at `supporting/referees/`, named `apply-supporting-referees`, and returns
to `apply-supporting` when it finishes — none of it typed.

### A member with a hook of its own

```python
class ContactViewSet(WizardViewSet):
    template_name = "grant/wizard.html"
    wizard = contact

    def run_started(self, bound_wizard):
        bound_wizard.metadata["opened_at"] = timezone.now().isoformat()


hub = Hub().member("contact", ContactViewSet, title="Contact details")
```

The hub builds its member viewset on top of the class given, so the hook
runs and the class's own `template_name` and `wizard` stand.

### Wording the statuses for the whole tree

```python
class GrantApplicationViewSet(HubViewSet):
    ...

    def get_status_label(self, status):
        if status == BLOCKED:
            return "Locked"
        return super().get_status_label(status)
```

Nested hubs are subclasses of the root, so the supporting-information page
says *Locked* too.

---

## Troubleshooting

### A member completes but its row still says Not started

The member's viewset overrides `done()`. `MemberViewSet.done()` is what
stashes — put the work in the declared `done=` (or `run_done()` on a
viewset passed as the member's wizard) instead.

### Clicking a member row starts a fresh run beside the one I was editing

A row links to the hub's door, which resumes before it re-opens. If you
overrode `get_member_url()`, make it reverse `member_url_name` with
`member_url_kwarg`, not the member's `-run` pattern.

### `InvalidStash` when re-opening a member

The stash's `label` no longer matches `stash_label(member)` — the member
was reshaped and `label=` bumped. Override `stash_unusable()` to delete the
stash and `enter()` again, or to send the user somewhere that explains.

### `ImproperlyConfigured: GrantHubViewSet has nothing to do when its journey is submitted`

A POST reached a complete root hub with no `journey_done()`. Override it —
a hub with nothing to do at submit should not render a submit button.

### `ImproperlyConfigured: … has no members to list`

The viewset has no `hub`. Set `hub` to a `Hub()` declaration.


### `Http404: Journey 'app-1' has been submitted.`

The default `journey_completed()` on a root hub. Override it to render a
done page from `store.data`.

### POST to the door returns 405

By design: the door is `GET`-only. Submit by POSTing to the page URL.

---

**Learn:** [Chapter 11 — Hubs](../learn/11-hubs.md), [Chapter 13 — Blocked and hidden](../learn/13-blocked-and-hidden.md), [Chapter 14 — Journeys](../learn/14-journeys.md) · **Related:** [Journey store](journey-store.md), [Collections](collections.md), [Stashing](stashing.md), [`WizardViewSet`](viewsets.md), [Run metadata](run-metadata.md)
