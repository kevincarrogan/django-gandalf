# Chapter 12 — Collections: add another

A budget is not one answer but a list of them, and the applicant decides how
long the list is. `gandalf.collections` is the "add another" pattern — a page
listing what has been added so far, with **Change** and **Remove** on each
row, an **Add another** question, and one item wizard behind all of them.

A collection is a hub whose members are *built* rather than declared: one
per id in an ordered registry the user grows. Everything the hub does — the
status derivation, the resume-before-reopen door, the no-bare-run-URL
guarantee — applies unchanged. It is declared as a value, like a hub, and
listed on one like any other member.

```python
from gandalf.collections import Collection
from gandalf.hubs import Hub, HubViewSet


project = (
    Wizard()
    .step(ProjectForm, name="project", label="Project")
    .step(ReviewStepView, name="review")
)

budget = Collection(
    Wizard()
    .step(BudgetLineForm, name="line", label="Budget line")
    .step(ReviewStepView, name="review"),
    item_name="Budget line",
    # The answer that names a row, cached when the line finishes.
    item_title=("line", "item"),
    min_items=1,
    reopen="review",
    template_name="testapp/budget.html",
    remove_template_name="testapp/budget_remove.html",
)


class ProjectHubViewSet(HubViewSet):
    template_name = "testapp/readme_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-project"
    hub = (
        Hub()
        .member("project", project, title="Project", reopen="review")
        # A collection is a member like any other: the row links straight
        # at its page and reads its own status.
        .collection("budget", budget, title="Budget")
    )
```

One mount, as before. The hub puts the budget page at `readme/project/budget/`,
and each line's wizard beneath the door for that line.

```python
urlpatterns = [
    path("readme/project/", include(ProjectHubViewSet.urls())),
]
```

```django
{% if collection.is_empty %}
  <h1>You have not added any budget lines</h1>
{% else %}
  <h1>You have added {{ collection.count }} budget line{{ collection.count|pluralize }}</h1>
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

The view reads one POST field, so two submit buttons carry the answer and
the question needs no widget of its own.

### Identity is opaque, so removing renumbers nothing

An item is a uuid, never a position. Delete from the middle and the
survivors keep their ids, their URLs and their answers. This is the single
biggest reason a collection is not `.expand()`: an expansion's answers are
one positional list, and every item lives in one run, so there is no such
thing as a half-finished *item*. Use `.expand()` for "how many trustees? now
name each"; use a collection for "add as many as you like, and change your
mind later".

### A row costs no walk

An item is titled by the answer named in `item_title`, worked out once,
when the item finishes, and cached. The page reads a string. An item that
has never finished falls back to a positional name (`Budget line 2`), which
is honest: nothing it has answered is known to name it.

### Completeness is declared, not derived

No reading of storage can say whether the applicant has more lines to add.
Only they can, so the page asks and the answer is stored: the collection is
**Complete** when the user has said *no more*, every item has finished, and
there are at least `min_items`. Pressing **Add another** again withdraws it —
that *is* the user changing their mind. *Continue* is the collection's
submit: with an item half-done or `min_items` unmet it is refused and the
page shows why; otherwise it goes up to the hub that lists the collection.

The three URLs a collection publishes, the exact order a removal takes, how
to mount one on its own, and every hook are in the
[Collections reference](../reference/collections.md).

> ▶ **Try it live:** http://127.0.0.1:8000/readme/project/ &nbsp;·&nbsp; **Source:** [`ch12_budget.py`](../../tests/testapp/readme/ch12_budget.py)

---

[← Chapter 11 — Hubs: a task list of members](11-hubs.md) · [Learn](README.md) · [Chapter 13 — Blocked and hidden members →](13-blocked-and-hidden.md)
