# Chapter 11 — Hubs: a task list of members

An application is not one wizard. Contact details, an address, the project,
the budget, referees — each is its own thing, finished on its own, in any
order, and re-opened later. Chapter 10 did the stashing by hand; a **hub** is
that pattern with the bookkeeping owned by the library. Declare the members
the way you declare steps — one value, read top-down — and the hub renders
a row per member carrying its title, its status and one URL that does the
right thing whichever state it is in.

```python
from gandalf.hubs import Hub, HubViewSet


contact = (
    Wizard()
    .step(ApplicantForm, name="name", label="Your name")
    .step(EmailForm, name="email", label="Email")
    # A review step is what makes re-opening safe: without it, one
    # successful edit walks straight through to done() again.
    .step(ReviewStepView, name="review")
)

address = (
    Wizard()
    .step(AddressForm, name="address", label="Address")
    .step(AddressReviewStepView, name="review")
)


class GrantHubViewSet(HubViewSet):
    template_name = "testapp/readme_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-hub"
    hub = (
        Hub()
        .member("contact", contact, title="Contact details", reopen="review")
        .member("address", address, title="Address", reopen="review")
    )
```

The members are plain wizards. The hub says what each is called, which
step a finished one re-opens at, and — because the members are wizards
rather than viewsets — which template they render with. A hub is mounted
exactly like a wizard, and one `include()` publishes the whole thing: the
page, a door into each member, and each member's own run URLs beneath it.

```python
urlpatterns = [
    path("readme/hub/", include(GrantHubViewSet.urls())),
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

### Every link is a step URL, never a bare run URL

This is the one thing worth understanding. A run whose every stored answer
validates **completes on a GET**. So a hub row can never point at a
wizard's own run: it would fire the member's side effects on a click. Rows
link to the hub's door, which resumes a live run, re-opens a stash, or
starts a fresh run, and lands the user on a step URL in every case.
Resuming is tried *before* re-opening, so a member already being edited
continues that edit rather than resurrecting a second run beside it.

Because the hub mounts its members itself, it goes one further: a member's
URL *is* its door. `readme/hub/contact/` opens the contact member through
the hub — there is no bare start URL for a link to reach by mistake.

A row is deliberately cheap: two storage reads and a `reverse()`, no walk.
Whether the stored answers still *validate* is not asked — it would not
change the row.

### Re-opening is edit-and-re-save

A re-opened member arrives with every answer already valid, so the next
successful submission walks to the end and saves again — the user changed
something and it saved. `reopen="review"` lands them on their answers with
a change link each, rather than at step one.

Every decision — which members appear, how a status is derived, how a row
is titled or worded, each way into a run — is a hook on the viewset, and
the classmethods the hub uses to bind a wizard from outside its own request
(`begin()`, `inspect()`, `reopen()`) are public in their own right. All of
it is in the [Hubs reference](../reference/hubs.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/hub/ &nbsp;·&nbsp; **Source:** [`ch11_hub.py`](../../tests/testapp/readme/ch11_hub.py)

---

[← Chapter 10 — Stashing: leave and come back](10-stashing.md) · [Learn](README.md) · [Chapter 12 — Collections: add another →](12-collections.md)
