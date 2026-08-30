# Chapter 13 — Add another: a list the user grows

A budget is not one answer but a list of them, and the applicant decides how
long the list is. `AddAnother` is the "add another" pattern — a page
listing what has been added so far, with **Change** and **Remove** on each
row, an **Add another** question, and one item wizard behind all of them.

An add-another page is a task list whose entries are *built* rather than
declared: one per id in an ordered registry the user grows. Everything the
task list does — the status derivation, the resume-before-reopen door, the
no-bare-run-URL guarantee — applies unchanged. It is declared as an entry
of the list, beside the sections.

```python
from gandalf.tasklists import AddAnother, Section, TaskList, TaskListViewSet


project = (
    Wizard()
    .step(ProjectForm, name="project", label="Project")
    .step(ReviewStepView, name="review")
)

budget_line = (
    Wizard()
    .step(BudgetLineForm, name="line", label="Budget line")
    .step(ReviewStepView, name="review")
)


class Project(TaskList):
    project = Section(project, title="Project", reopen_at="review")
    # An add-another row is an entry like any other: the row links straight
    # at its page and reads its own status.
    budget = AddAnother(
        budget_line,
        title="Budget",
        # The answer that names a row, cached when the line finishes.
        item_title="item",
        min_items=1,
        reopen_at="review",
    )


class ProjectViewSet(TaskListViewSet):
    template_name = "testapp/readme_hub.html"
    section_template_name = "testapp/linear_wizard.html"
    add_another_template_name = "testapp/budget.html"
    remove_template_name = "testapp/budget_remove.html"
    url_name = "readme-project"
    task_list = Project
```

One mount, as before. The list puts the budget page at
`readme/project/budget/`, and each line's wizard beneath the door for that
line.

```python
urlpatterns = [
    path("readme/project/", include(ProjectViewSet.urls())),
]
```

```django
{% if items.is_empty %}
  <h1>You have not added any budget lines</h1>
{% else %}
  <h1>You have added {{ items.count }} budget line{{ items.count|pluralize }}</h1>
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

The view reads one POST field, so two submit buttons carry the answer and
the question needs no widget of its own.

### Identity is opaque, so removing renumbers nothing

An item is a uuid, never a position. Delete from the middle and the
survivors keep their ids, their URLs and their answers. This is the single
biggest reason an add-another list is not `.expand()`: an expansion's
answers are one positional list, and every item lives in one run, so there
is no such thing as a half-finished *item*. Use `.expand()` for "how many
trustees? now name each"; use add another for "add as many as you like, and
change your mind later".

### A row costs no walk

An item is titled by the answer named in `item_title`, worked out once,
when the item finishes, and cached. The page reads a string. An item that
has never finished falls back to a positional name (`Budget line 2`), which
is honest: nothing it has answered is known to name it.

### Completeness is declared, not derived

No reading of storage can say whether the applicant has more lines to add.
Only they can, so the page asks and the answer is stored: the list is
**Complete** when the user has said *no more*, every item has finished, and
there are at least `min_items`. Pressing **Add another** again withdraws it —
that *is* the user changing their mind. *Continue* is the page's submit:
with an item half-done or `min_items` unmet it is refused and the page
shows why; otherwise it goes up to the task list that lists it.

The three URLs the page publishes, the exact order a removal takes, how to
give an item behaviour of its own, how to mount a page on its own, and
every hook are in the [Add another reference](../reference/add-another.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/project/ &nbsp;·&nbsp; **Source:** [`ch13_budget.py`](../../tests/testapp/readme/ch13_budget.py)

---

[← Chapter 12 — Task lists: sections in any order](12-task-lists.md) · [Learn](README.md) · [Chapter 14 — Blocked and hidden sections →](14-blocked-and-hidden.md)
