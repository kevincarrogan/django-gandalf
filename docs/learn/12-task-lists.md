# Chapter 12 — Task lists: sections in any order

An application is not one wizard. Contact details, an address, the project,
the budget, referees — each is its own thing, finished on its own, in any
order, and re-opened later. Chapter 11 did the stashing by hand; a **task
list** is that pattern with the bookkeeping owned by the library. Declare
the sections, and the page renders a row per section carrying its title,
its status and one URL that does the right thing whichever state it is in.

```python
from gandalf.tasklists import Section, TaskList, TaskListViewSet

from .ch07_review import AddressStepView, ReviewStepView


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
    .step(AddressStepView, name="address", label="Address")
    .step(ReviewStepView, name="review")
)


class GrantApplication(TaskList):
    contact = Section(contact, title="Contact details", reopen_at="review")
    address = Section(address, title="Address", reopen_at="review")


class GrantApplicationViewSet(TaskListViewSet):
    template_name = "testapp/readme_task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    url_name = "readme-task-list"
    task_list = GrantApplication
```

Two sections, two shapes, **one review view** — [chapter
7's](07-the-summary.md#the-summary-page), reused unchanged. It knows nothing
about either section, and that is what makes it reusable: the address reads
as one line because `AddressStepView` says so, and a section with no address
in it needs nothing said about it at all. Shaping that lived on the review view
would have to be written once per section, and a spec naming a step the
section does not have raises `ImproperlyConfigured` — so a page carrying
specs is a page tied to one wizard's shape.

A wizard chains because it is a sequence. A task list is a *set* — the
applicant does its sections in whatever order they like — so it is a class
body, the way a form's fields are: the attribute name is the section's key
(and so its URL segment — pass `key="match-funding"` where the name would
put an underscore in the URL), and the body's order is the order on the page. Nothing about it says
"first this, then that", because nothing about a task list means that.

It is the same split a wizard has. `GrantApplication` is a value — what
the list is. `GrantApplicationViewSet` is the view that mounts it and owns
what needs a request: the page, its URL, and — because the sections are
plain wizards — the template they render with. One `include()` publishes
the whole thing: the page, a door into each section, and each section's
own run URLs beneath it.

```python
urlpatterns = [
    path("readme/task-list/", include(GrantApplicationViewSet.urls())),
]
```

```django
<p>You have completed {{ task_list.completed }} of {{ task_list.count }} sections.</p>

{% for row in task_list.rows %}
  <li>
    <a href="{{ row.url }}">{{ row.title }}</a>
    <strong class="tag tag--{{ row.status }}">{{ row.status_label }}</strong>
  </li>
{% endfor %}
```

`task_list.status` is derived for the set — **Complete** when every row
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
section's URL *is* its door. `readme/task-list/contact/` opens the contact
section through the page — there is no bare start URL for a link to reach
by mistake.

A row is deliberately cheap: two storage reads and a `reverse()`, no walk.
Whether the stored answers still *validate* is not asked — it would not
change the row.

### Re-opening is edit-and-re-save

A re-opened section arrives with every answer already valid, so the next
successful submission walks to the end and saves again — the user changed
something and it saved. `reopen_at="review"` lands them on their answers with
a change link each, rather than at step one.

Every decision — which sections appear, how a status is derived, how a row
is titled or worded, each way into a run — is a hook on the viewset, and
the classmethods the page uses to bind a wizard from outside its own
request (`begin()`, `inspect()`, `reopen()`) are public in their own
right. All of it is in the [Task lists reference](../reference/tasklists.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/task-list/ &nbsp;·&nbsp; **Source:** [`ch12_task_list.py`](../../tests/testapp/readme/ch12_task_list.py)

---

[← Chapter 11 — Stashing: leave and come back](11-stashing.md) · [Learn](README.md) · [Chapter 13 — Add another: a list the user grows →](13-add-another.md)
