# Chapter 11 — Hubs: a task list of members

An application is not one wizard. Contact details, an address, the project,
the budget, referees — each is its own thing, finished on its own, in any
order, and re-opened later. Chapter 10 did the stashing by hand; a **hub** is
that pattern with the bookkeeping owned by the library. Declare the members,
mix `WizardMemberMixin` into each member's viewset, and the hub renders a
row per member carrying its title, its status and one URL that does the
right thing whichever state it is in.

```python
from gandalf.hubs import HubView, Member, WizardMemberMixin


class ContactMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "readme-hub-contact"
    template_name = "testapp/linear_wizard.html"
    member_key = "contact"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        # A review step is what makes re-opening safe: without it, one
        # successful edit walks straight through to done() again.
        .step(ReviewStepView, name="review")
    )


class AddressMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "readme-hub-address"
    template_name = "testapp/linear_wizard.html"
    member_key = "address"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class GrantHubView(HubView):
    template_name = "testapp/readme_hub.html"
    url_name = "readme-hub"
    member_url_name = "readme-hub-member"
    members = [
        Member("contact", ContactMemberViewSet, title="Contact details", reopen_step="review"),
        Member("address", AddressMemberViewSet, title="Address", reopen_step="review"),
    ]
```

A hub is mounted exactly like a wizard, and publishes two patterns from
`url_name` — the page, and the door into one member. **Mount the members
beside it, never beneath it:** the hub's `<slug:member>/` door matches any
single segment and would swallow them.

```python
urlpatterns = [
    path("readme/hub/", include(GrantHubView.urls())),
    path("readme/hub-contact/", include(ContactMemberViewSet.urls())),
    path("readme/hub-address/", include(AddressMemberViewSet.urls())),
]
```

```django
<p>You have completed {{ hub.completed }} of {{ hub.count }} sections.</p>

{% for row in hub.rows %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
```

The word on the page is yours — a task list says *sections* to the person
filling it in, whatever the code calls a member. `hub.status` is derived for
the set — **Complete** when every row is, **Not started** when none has
been touched, **Incomplete** in between — so the button that submits the
whole thing reads one flag rather than counting rows.

### Members override `run_done()`, never `done()`

`done()` belongs to the mixin: it stashes the finished answers under
`member_key`, which is the only thing that can tell the hub the member is
finished, then hands off to `run_done()` for what runs once per edit —
saving to your models, say — whose default sends the user back to the hub.
A subclass that replaced `done()` would leave the member reading as not
started forever.

The two strings a member repeats back to its hub — `member_key` and
`hub_url_name` — are checked against the hub's own declaration, because
each holds only for as long as both sides stay typed the same.

### Every link is a step URL, never a bare run URL

This is the one thing worth understanding. A run whose every stored answer
validates **completes on a GET**. So a hub row can never point at the
wizard's own URL: it would fire the member's side effects on a click. Rows
link to the hub's own door, which resumes a live run, re-opens a stash, or
starts a fresh run, and lands the user on a step URL in every case. Resuming
is tried *before* re-opening, so a member already being edited continues
that edit rather than resurrecting a second run beside it.

A row is deliberately cheap: two storage reads and a `reverse()`, no walk.
Whether the stored answers still *validate* is not asked — it would not
change the row.

### Re-opening is edit-and-re-save

A re-opened member arrives with every answer already valid, so the next
successful submission walks to the end and fires `done()` again — the user
changed something and it saved. `reopen_step="review"` lands them on their
answers with a change link each, rather than at step one.

Every decision — which members appear, how a status is derived, how a row
is titled or worded, each way into a run — is a hook, and the classmethods
the hub uses to bind a wizard from outside its own request (`begin()`,
`inspect()`, `reopen()`) are public in their own right. All of it is in the
[Hubs reference](../reference/hubs.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/hub/ &nbsp;·&nbsp; **Source:** [`ch11_hub.py`](../../tests/testapp/readme/ch11_hub.py)

---

[← Chapter 10 — Stashing: leave and come back](10-stashing.md) · [Learn](README.md) · [Chapter 12 — Collections: add another →](12-collections.md)
