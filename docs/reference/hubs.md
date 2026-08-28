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
    HubMixin,
    HubView,
    JourneyMemberMixin,
    Member,
    MemberNotFound,
    MemberRow,
    WizardMemberMixin,
)
```

A hub lists *members*. Each member is a wizard (`WizardMemberMixin` on its
viewset), another hub, or a link to a page the hub does not run. The hub
renders one `MemberRow` per member — title, status, one URL — wrapped in a
`Hub` that says how far the whole page has got. A row costs two storage
reads and a `reverse()`, never a walk; the walk happens once, on the way
in, for the one member the user clicked.

Everything a hub keeps lives in a journey store scoped to one *journey* —
see [Journey store](journey-store.md). A hub's members can themselves be
hubs; nesting is a key namespace over the same record, and only the root
hub ends the journey.

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
| The member's `hidden()` (or the hub's `member_hidden()`) is true | The member is not in `hub.rows` at all — hidden outranks everything |
| `Member.status` is set | Whatever that callable returns; nothing below runs |
| The member's `blocked()` (or the hub's `member_blocked()`) is true | `BLOCKED` — outranks a stash, so a member whose prerequisite was withdrawn after it was answered reports what the user can do now |
| The member is a hub | That hub's `status_for()` — derived from its own rows |
| A stash is held under the member's full key | `COMPLETE` — the member ran to its own end and `done()` fired |
| A run is recorded for the member and its state holds at least one entry | `INCOMPLETE` |
| Everything else | `NOT_STARTED` — including a run opened and never answered, and a recorded run the storage has forgotten or tombstoned |

Whether stored answers still *validate* is never asked; it would cost a
form `clean()` per answered step and would not change the row.

### `Member(key, viewset=None, title=None, label=None, reopen_step=None, url_kwargs={}, url_name=None, status=None)`

A frozen dataclass declaring one spoke of a hub.

**Parameters**

- `key` — the member's identity: the segment the door routes on and, once
  prefixed by any nested hub above (`full_key()`), the key its run and
  stash are kept under. Relative to the hub that lists it.
- `viewset` — the class that runs it: a `WizardMemberMixin` viewset, or a
  `HubMixin` view (a nested hub or a collection). `None` for a member the
  hub does not run — then `url_name` and `status` are both required.
- `title` — what the row renders. Default: the key made readable
  (`"home_address"` → `"Home address"`).
- `label` — the label the member's stash is expected to carry; checked
  when the stash is re-opened. Default: the full key. Bump it when a
  deploy reshapes the wizard so an old-shape payload is refused rather than
  walked into a tree it no longer fits.
- `reopen_step` — the step a completed member re-opens at. Default `None`:
  the first step on the route.
- `url_kwargs` — mount-prefix kwargs the member's own view is mounted
  under (a tenant slug), forwarded into every URL the hub builds for it.
  Excluded from equality and hashing.
- `url_name` — where the row links instead of the hub's door, for a
  member with no run to walk.
- `status` — `callable(request, url_kwargs) -> str`, deciding the status
  when the hub cannot derive one. Handed `member_url_kwargs()`. Excluded
  from equality and hashing.

### `MemberRow`

One row of the page, as the template sees it. Frozen.

**Attributes** — `member` (the underlying `Member`), `status`, `title`,
`status_label`, `url`, and the property `key` (`member.key`, the short
key). Boolean properties: `is_not_started`, `is_incomplete`,
`is_complete`, `is_blocked`.

### `Hub`

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

`LookupError` raised by `get_member(key)` when the key names no member the
hub lists for this request — never declared, renamed, or hidden. The door
turns it into `member_unavailable()`.

### `JourneyMemberMixin`

What a wizard member and a hub have in common: being a member of a journey.
`WizardMemberMixin` and `HubMixin` (and so a collection) both derive from
it. Not mixed in directly.

**Attributes**

| Attribute | Default | Meaning |
| --- | --- | --- |
| `member_key` | `None` | The *full* key this member finishes under — `"referees"` under a root hub, `"supporting:referees"` under a hub keyed `"supporting"`. `None` for a root hub. |
| `hub_url_name` | `None` | The URL name of the hub that lists this member, where finishing returns to. `None` for a root hub. |
| `journey_store_class` | `SessionJourneyStore` | The store the journey's bookkeeping lives in. Must satisfy `gandalf.types.JourneyStore`. |
| `journey` | `"default"` | The fixed journey used when the URL carries none. |
| `journey_url_kwarg` | `"journey"` | The URL kwarg the journey is read from when mounted under one. |
| `key_separator` | `":"` | What joins a hub's prefix to a member's key. |

**Methods**

- `compose_key(prefix, key)` — `f"{prefix}{key_separator}{key}"`.
- `blocked(cls, request, member, store)` — classmethod. `True` when the
  member is listed but not open yet: the row reads **Cannot start yet**
  and the door refuses it. Default `False`. Called once per row at render
  and once more at the door; read `store.data` and `store.has_stash()`,
  never a stash's state.
- `hidden(cls, request, member, store)` — classmethod. `True` when the
  member should not be listed for this request: not in `rows`, not in the
  counts, unknown to the door. Default `False`.
- `get_journey()` — the URL's `journey_url_kwarg` when present, otherwise
  `journey`, as a string.
- `get_journey_store()` — `journey_store_class(WizardContext.from_request(request), get_journey())`.
- `get_hub_url()` — `reverse(hub_url_name, kwargs=get_hub_url_kwargs())`.
  Raises `ImproperlyConfigured` when `hub_url_name` is `None`.
- `get_hub_url_kwargs()` — abstract; each kind of member supplies its own.
- `dispatch()` — reads `store.is_complete()` once per request and, for a
  submitted journey, returns `journey_completed(store)` instead of
  dispatching. Every member checks, so a bookmarked step URL cannot re-open
  a member into a tombstone.
- `journey_completed(store)` — the response after submission. Default:
  `redirect(get_hub_url())`, up to the hub above.

### `WizardMemberMixin`

Mix into a member's `WizardViewSet`, before it in the bases, so finishing
registers with the hub.

**Attributes** — everything on `JourneyMemberMixin`, plus:

- `member_label` — the label stamped into the stash. Default `None`: the
  member key.
- `dynamic_member_key` — default `False`. Set `True` on a viewset that
  derives its key per request by overriding `get_member_key()` (one wizard
  mounted per item of a collection); the misconfiguration message then says
  so instead of telling you to set a class attribute.

**Methods**

- `get_member_key()` — `member_key`, or `ImproperlyConfigured` when unset.
- `get_member_label()` — `member_label`, or `default_member_label()`.
- `default_member_label()` — `get_member_key()`.
- `get_hub_url_kwargs()` — the wizard's own `get_url_kwargs()`, the journey
  among them.
- `done(bound_wizard)` — **this mixin's; do not override.** In order:
  `store.put_stash(key, bound_wizard.stash(label=...))`;
  `run_recorded(bound_wizard, store, key)`; `response = run_done(bound_wizard)`;
  `store.clear_run(key)`; return the response. A `run_done()` that raises
  leaves the run id in place, so the member stays resumable.
- `run_recorded(bound_wizard, store, key)` — library-side bookkeeping that
  must read the finished run: sits between the stash and `run_done()`,
  inside the window where the run's state is still readable. A plain member
  records nothing; a collection item caches its title here. Not for
  application work.
- `run_done(bound_wizard)` — **the hook to override.** Runs once per
  completion, including each re-save of a re-opened member. Write what the
  rest of the journey needs into `self.get_journey_store().data` here.
  Default: `redirect(get_hub_url())`.

Re-opening a completed member seeds a fresh run from its stash with every
answer already valid, so the next successful submission walks to the end
and fires `done()` again — edit-and-re-save. Give the wizard a review step
if the user should get a confirm gate first.

### `HubMixin`

Adds `hub` to a view's template context and owns the door each row links
to. Mix into a `TemplateView`, or use `HubView`.

**Attributes** — everything on `JourneyMemberMixin`, plus:

| Attribute | Default | Meaning |
| --- | --- | --- |
| `members` | `None` | A list of `Member`. Required unless `get_members()` is overridden. |
| `url_name` | `None` | The page's URL name. `HubView.urls()` requires it; `get_page_url()` requires it; and it is what a member's `hub_url_name` is checked against. |
| `member_url_name` | `None` | The door's URL name. `HubView.urls()` publishes it as `f"{url_name}-member"`. Required by `get_member_url()` for wizard members. |
| `member_url_kwarg` | `"member"` | The URL kwarg the door reads the member key from. |
| `hub_context_name` | `"hub"` | Where the `Hub` lands in the context. `None` publishes nothing. |
| `template_name` | — | The `TemplateView`'s; yours to set. |

For a nested hub also set `member_key` (its prefix) and `hub_url_name`
(the parent's `url_name`).

**Identity and nesting**

- `get_member_key()` — `member_key`; `None` for a root hub.
- `is_nested` — property; `hub_url_name is not None`.
- `full_key(member)` — the member's key in the store: `member.key` under a
  root hub, `compose_key(member_key, member.key)` under a nested one. Every
  read and write about a member goes through here.
- `stash_label(member)` — `member.label`, or `full_key(member)`.
- `status_for(cls, request, url_kwargs)` — classmethod; this hub's status
  as a row on the hub above, built from its own rows under the given URL
  kwargs. Costs this hub's rows' storage reads; still no walk.
- `is_hub(member)` — staticmethod; whether `member.viewset` is a `HubMixin`.

**Members**

- `get_members()` — the members in display order. Default: `list(members)`;
  `ImproperlyConfigured` when `members` is `None`. Override to choose per
  request (by user, plan, feature flag).
- `get_member(key)` — the listed member `key` names, after validation and
  hiding. Raises `MemberNotFound`.
- `get_journey_url_kwargs()` — `{journey_url_kwarg: value}` when the
  request carried one, else `{}`.
- `member_url_kwargs(member)` — `{**get_journey_url_kwargs(), **member.url_kwargs}`;
  what a member's view is run, reversed and asked with.
- `member_viewset(member)` — `member.viewset` narrowed to a wizard viewset.

**Validation.** The declaration is checked once per request, on the rows
and on the door, before anything is hidden. Every failure is
`ImproperlyConfigured`:

| Condition | Message begins |
| --- | --- |
| Two members share a key | *Hub member keys must be unique* |
| `viewset=None` without both `url_name` and `status` | *A hub member that is not a wizard must declare both url_name and status* |
| A hub member whose viewset has no `url_name` | *A hub listed as a member must declare url_name* |
| A hub member whose viewset leaves `member_key` or `hub_url_name` unset | *A hub listed as a member must declare member_key … and hub_url_name* |
| A viewset's `member_key` differs from `full_key(member)` | *A hub member's key must match its viewset's member_key* — "Mismatched" |
| The hub has a `url_name` and a viewset's `hub_url_name` differs from it | *A hub member's viewset must return to the hub that lists it* — "Mispointed" |
| A viewset's `journey` or `journey_url_kwarg` differs from the hub's | *A hub member's viewset must be on the same journey as its hub* — "Astray" |

The key and return checks skip a wizard viewset that declares `None` for
them (a plain `WizardViewSet` doing its own bookkeeping); a hub member is
never skipped. The return check is skipped entirely when the hub itself has
no `url_name`.

**The page**

- `get_hub()` — `Hub(rows, status, status_label)`.
- `get_hub_status(rows)` — see `Hub` above. Override where an optional
  member should not hold the page back.
- `get_member_rows()` — the rows, built once per request and cached on the
  view instance.
- `build_member_rows()` / `build_member_row(member, store)` — what
  `get_member_rows()` builds.
- `get_member_status(member, store)` — the derivation table above.
- `member_blocked(member, store)` — asks `member.viewset.blocked()`;
  `False` for a member with no viewset. Override for a rule one member
  cannot answer alone; an override *replaces* the members' answers, so call
  `super()` where they should still count.
- `member_hidden(member, store)` — the mirror, asking `hidden()`.
- `get_member_state(member, store)` — the raw state list of the member's
  recorded run, read straight off its `storage_class`; `[]` with no run or
  a forgotten one.
- `get_member_title(member)` — `member.title`, or the key with `_` and `-`
  turned to spaces and its first letter capitalised.
- `get_status_label(status)` — the wording in the constants table, via
  `gettext`. Override to reword.
- `get_member_url(member)` — a hub member links to its own page; a member
  with `url_name` links there; anything else links to the door:
  `reverse(member_url_name, kwargs={**get_page_url_kwargs(), member_url_kwarg: member.key})`.
  `ImproperlyConfigured` when `member_url_name` is `None`.
- `get_page_url_kwargs()` — everything the request captured except
  `member_url_kwarg`; used for the hub's own URLs.
- `get_page_url()` — `reverse(url_name, kwargs=get_page_url_kwargs())`, this
  hub's own page. Not `get_hub_url()`, which is the hub *above*.
- `get_hub_url_kwargs()` — `get_page_url_kwargs()`; a nested hub and its
  parent share a mount.
- `get_context_data(**kwargs)` — adds `get_hub()` under `hub_context_name`.

**The door**

- `enter(member)` — the URL that puts the user inside the member, or
  `None` when there is nowhere to send them. In order: `None` for a member
  with no viewset; `None` when `get_member_status()` is `BLOCKED`; a hub
  member's page URL; `resume_member()` → `entry_url()`; `reopen_member()`
  → `entry_url(member.reopen_step)` (an `InvalidStash` goes to
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

**The journey**

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
- `journey_completed(store)` — after submission, for the page and the door
  alike. A nested hub redirects to the hub above; a root hub raises
  `Http404` by default. Override on the root to render a done page from
  `store.data`.

### `HubView`

`HubMixin` over `TemplateView`, one view over two routes.

- `urls()` — classmethod. Requires `url_name`. Publishes:

  | Pattern | Name |
  | --- | --- |
  | `""` | `url_name` — the page |
  | `"<slug:member>/"` (the `member_url_kwarg`) | `f"{url_name}-member"` — the door |

- `get()` — without a member kwarg, renders the page. With one:
  `get_member(key)` (`MemberNotFound` → `member_unavailable()`), then
  `enter(member)` (`None` → `member_unavailable()`), else `redirect(url)`.
- `post()` — on the page, `submit()`. On the door, `405 Method Not Allowed`
  (`GET` only): the route that opens a member never finishes anything.

**Mounting.** Mount every member *beside* the hub, never beneath it. The
door's `<slug:member>/` matches any single segment and would swallow a
member mounted under the hub's prefix:

```python
path("apply/", include(GrantHubView.urls())),
path("apply-contact/", include(ContactMemberViewSet.urls())),   # sibling
```

**Nesting.** A hub listed by another declares `member_key` (its key on the
parent, under the parent's prefix if any) and `hub_url_name` (the parent's
`url_name`). Every member it lists is keyed under that prefix in the same
journey record — a wizard two hubs down declares its full key,
`member_key = "supporting:referees"`, and the hub checks it agrees. Its
row on the parent is `status_for()`, its row's link and its door both land
on its page, its submit is `hub_done()`, and it tombstones nothing. The
root's `submit()` ends the journey and takes every nested run and stash
with it.

---

## Usage

### A task list of two members

```python
from django.urls import include, path

from gandalf.hubs import HubView, Member, WizardMemberMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class ContactMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "grant-contact"
    template_name = "grant/wizard.html"
    member_key = "contact"
    hub_url_name = "grant-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        .step(ReviewStepView, name="review")
    )


class OrganisationMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "grant-organisation"
    template_name = "grant/wizard.html"
    member_key = "organisation"
    hub_url_name = "grant-hub"
    wizard = (
        Wizard()
        .step(OrganisationForm, name="organisation", label="Organisation")
        .step(ReviewStepView, name="review")
    )


class GrantHubView(HubView):
    template_name = "grant/hub.html"
    url_name = "grant-hub"
    member_url_name = "grant-hub-member"
    members = [
        Member("contact", ContactMemberViewSet, title="Contact details", reopen_step="review"),
        Member("organisation", OrganisationMemberViewSet, title="Your organisation", reopen_step="review"),
    ]


urlpatterns = [
    path("grant/", include(GrantHubView.urls())),
    path("grant-contact/", include(ContactMemberViewSet.urls())),
    path("grant-organisation/", include(OrganisationMemberViewSet.urls())),
]
```

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
from gandalf.hubs import WizardMemberMixin
from gandalf.viewsets import WizardViewSet


class ProjectMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "project"
    hub_url_name = "grant-hub"
    wizard = ...

    def run_done(self, bound_wizard):
        project = bound_wizard.path.find_step(name="project")
        amount = int(project.form.cleaned_data["amount"])
        self.get_journey_store().data["amount"] = amount
        return super().run_done(bound_wizard)   # back to the hub
```

### A member that unlocks, and one that appears

```python
from gandalf.hubs import WizardMemberMixin
from gandalf.viewsets import WizardViewSet


class RefereesMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "referees"
    hub_url_name = "grant-hub"
    wizard = ...

    @classmethod
    def blocked(cls, request, member, store):
        return not store.has_stash("contact")      # Cannot start yet


class MatchFundingMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "match_funding"
    hub_url_name = "grant-hub"
    wizard = ...

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("amount", 0) <= 10_000   # not listed at all
```

### Ending the journey

```python
from django.shortcuts import redirect, render

from gandalf.hubs import HubView, Member


class GrantApplicationHubView(HubView):
    template_name = "grant/hub.html"
    url_name = "grant-hub"
    member_url_name = "grant-hub-member"
    members = [...]

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
two records: `path("apply/<slug:journey>/", include(GrantApplicationHubView.urls()))`,
with every member under the same `<slug:journey>` segment.

### A hub inside a hub

```python
from gandalf.hubs import HubView, Member, WizardMemberMixin
from gandalf.viewsets import WizardViewSet


class RefereesMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "supporting:referees"          # the full key
    hub_url_name = "grant-supporting"
    wizard = ...


class SupportingHubView(HubView):
    template_name = "grant/hub.html"
    url_name = "grant-supporting"
    member_url_name = "grant-supporting-member"
    member_key = "supporting"                   # the prefix
    hub_url_name = "grant-hub"                  # the parent
    members = [Member("referees", RefereesMemberViewSet, title="Referees")]


class GrantApplicationHubView(HubView):
    ...
    members = [
        ...,
        Member("supporting", SupportingHubView, title="Supporting information"),
    ]
```

---

## Troubleshooting

### A member completes but its row still says Not started

The hub reads a stash under `full_key(member)` and the member stashes under
its own `member_key`; the two have drifted. The hub raises
`ImproperlyConfigured` ("Mismatched") for a `WizardMemberMixin` viewset, so
this usually means the viewset overrides `done()` instead of `run_done()` —
the mixin's `done()` is what stashes — or the viewset is a plain
`WizardViewSet` doing its own bookkeeping under another key.

### `ImproperlyConfigured: … Mispointed: contact (its viewset returns to 'other-hub')`

The member's `hub_url_name` must equal the `url_name` of the hub that lists
it. Under a nested hub, that is the nested hub's `url_name`, not the root's.

### `ImproperlyConfigured: … Astray: contact (its viewset declares journey='default', journey_url_kwarg='application')`

Every member's viewset must declare the same `journey` and
`journey_url_kwarg` as its hub, or it finishes into a record the hub never
reads.

### Clicking a member row starts a fresh run beside the one I was editing

The row links to the wizard's start URL instead of the hub's door. Use
`row.url` as built by `get_member_url()`; if you overrode it, make it reverse
`member_url_name` with `member_url_kwarg`.

### Every request to a member 404s or bounces after mounting it under the hub

The door's `<slug:member>/` pattern matched the member's mount prefix first.
Mount members as siblings of the hub.

### `InvalidStash` when re-opening a member

The stash's `label` no longer matches `stash_label(member)` — the member
was reshaped and `label` / `member_label` bumped. Override
`stash_unusable()` to delete the stash and `enter()` again, or to send the
user somewhere that explains.

### `ImproperlyConfigured: GrantHubView has nothing to do when its journey is submitted`

A POST reached a complete root hub with no `journey_done()`. Override it —
a hub with nothing to do at submit should not render a submit button — or
give the hub a `hub_url_name` if it is meant to be nested.

### `Http404: Journey 'app-1' has been submitted.`

The default `journey_completed()` on a root hub. Override it to render a
done page from `store.data`.

### POST to the door returns 405

By design: the door is `GET`-only. Submit by POSTing to the page URL.

---

**Learn:** [Chapter 11 — Hubs](../learn/11-hubs.md), [Chapter 13 — Blocked and hidden](../learn/13-blocked-and-hidden.md), [Chapter 14 — Journeys](../learn/14-journeys.md) · **Related:** [Journey store](journey-store.md), [Collections](collections.md), [Stashing](stashing.md), [`WizardViewSet`](viewsets.md), [Run metadata](run-metadata.md)
