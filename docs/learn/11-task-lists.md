# Chapter 11 — Task lists: sections in any order

An application is not one wizard. Contact details, an address, the project,
the budget, referees — each is its own thing, finished on its own, in any
order, and re-opened later. Chapter 10 did the stashing by hand; a **task
list** is that pattern with the bookkeeping owned by the library. Declare
the sections, and the page renders a row per section carrying its title,
its status and one URL that does the right thing whichever state it is in.

```python
from gandalf.tasklists import Section, TaskList, TaskListViewSet


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


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details", reopen="review")
    address = Section(address, title="Address", reopen="review")


class GrantApplicationViewSet(TaskListViewSet):
    template_name = "testapp/readme_hub.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-hub"
    tasklist = GrantApplication
```

A wizard chains because it is a sequence. A task list is a *set* — the
applicant does its sections in whatever order they like — so it is a class
body, the way a form's fields are: the attribute name is the section's key,
and the body's order is the order on the page. Nothing about it says
"first this, then that", because nothing about a task list means that.

It is the same split a wizard has. `GrantApplication` is a value — what
the list is. `GrantApplicationViewSet` is the view that mounts it and owns
what needs a request: the page, its URL, and — because the sections are
plain wizards — the template they render with. One `include()` publishes
the whole thing: the page, a door into each section, and each section's
own run URLs beneath it.

```python
urlpatterns = [
    path("readme/hub/", include(GrantApplicationViewSet.urls())),
]
```

```django
<p>You have completed {{ tasklist.completed }} of {{ tasklist.count }} sections.</p>

{% for row in tasklist.rows %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
```

`tasklist.status` is derived for the set — **Complete** when every row
is, **Not started** when none has been touched, **Incomplete** in between —
so the button that submits the whole thing reads one flag rather than
counting rows.

### Every link is a step URL, never a bare run URL

This is the one thing worth understanding. A run whose every stored answer
validates **completes on a GET**. So a row can never point at a wizard's
own run: it would fire the section's side effects on a click. Rows link to
the page's door, which resumes a live run, re-opens a stash, or starts a
fresh run, and lands the user on a step URL in every case. Resuming is
tried *before* re-opening, so a section already being edited continues
that edit rather than resurrecting a second run beside it.

Because the page mounts its sections itself, it goes one further: a
section's URL *is* its door. `readme/hub/contact/` opens the contact
section through the page — there is no bare start URL for a link to reach
by mistake.

A row is deliberately cheap: two storage reads and a `reverse()`, no walk.
Whether the stored answers still *validate* is not asked — it would not
change the row.

### Re-opening is edit-and-re-save

A re-opened section arrives with every answer already valid, so the next
successful submission walks to the end and saves again — the user changed
something and it saved. `reopen="review"` lands them on their answers with
a change link each, rather than at step one.

Every decision — which sections appear, how a status is derived, how a row
is titled or worded, each way into a run — is a hook on the viewset, and
the classmethods the page uses to bind a wizard from outside its own
request (`begin()`, `inspect()`, `reopen()`) are public in their own
right. All of it is in the [Task lists reference](../reference/tasklists.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/hub/ &nbsp;·&nbsp; **Source:** [`ch11_hub.py`](../../tests/testapp/readme/ch11_hub.py)

---

[← Chapter 10 — Stashing: leave and come back](10-stashing.md) · [Learn](README.md) · [Chapter 12 — Add another: a list the user grows →](12-add-another.md)
