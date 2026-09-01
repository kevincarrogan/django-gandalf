# Chapter 15 — Journeys: scope, memory, groups and an ending

Everything so far, put together. A task list's sections add up to
something — this application — and that something is a **journey**. It has
three things no single wizard has: a scope, a memory, and an ending. Every
section of it gets the first two; the root task list — the one no list
lists — owns the third. And because a task list is an entry like any
other, a task list can hold a task list.

### A scope

One session can hold two applications in two tabs, and they must never see
each other. Mount the page under a journey segment, and everything beneath
it — the page, every door, every section's run, the budget and its lines —
reads the same one:

```python
urlpatterns = [
    path("readme/apply/new/", include(ApplicationStartViewSet.urls())),
    path(
        "readme/apply/<slug:journey>/",
        include(GrantApplicationViewSet.urls()),
    ),
]
```

One pattern, as always. A list not mounted under a journey uses the one it
declares, `journey = "default"` — one per session, which is what chapters
11 to 13 were.

### Somewhere to begin

A journey is an id, a record kept under it, and a page to show it on. So
beginning one is minting the id, and the whole of it is a plain view
mounted at `apply/new/`, before the journey segment:

```python
def start_application(request):
    return redirect(GrantApplication.begin(request).url)
```

`begin()` is asked of the *list* — a value — and hands back the journey:
its id, its store, its page. The application arrives with every row *Not
started*, which is a real state rather than a missing one.

Nothing about beginning needs a browser either. An id and a record are not
HTTP, so a management command or an agent says the same thing to a
[context](../reference/run.md#wizardcontext) instead of a request:

```python
journey = GrantApplication.begin_for(WizardContext(actor=applicant))
```

And a list mounted without a `<journey>` segment has nowhere to put an id
at all — it reads the fixed `journey = "default"` above — so there is
nothing to begin. Link straight at the page.

### Asking for the first answer

Some journeys turn on a fact before there is a list to come back to. This
one does: whether the applicant is an individual or an organisation
decides whether a whole section exists. There are two ways to have that
answer, and only one of them is a wizard.

If the application already knows — off the account, off last year's
application, off the link they followed — it writes the answer rather than
asking for it. `store.data` is the journey's memory, the next section's
subject, and a seed written here is read by every `hidden()` and
`blocked()` on the first render:

```python
def start_application(request):
    journey = GrantApplication.begin(request)
    journey.store.data["applying_as"] = request.user.applying_as
    return redirect(journey.url)
```

If it has to be *asked* for, that is a wizard — and the point of the setup
wizard is the asking, not the beginning:

```python
def record_applying_as(store, run):
    """Read the one answer the rest of the journey turns on, once, and write
    it where every other section can read it without a walk."""
    step = run.path.find_step(name="applying-as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]
```

```python
setup = (
    Wizard()
    .step(ApplyingAsForm, name="applying-as", label="Applying as")
    .configure(
        template_name="testapp/linear_wizard.html",
        observer_class=CountRejections,
    )
)
```

Its `done()` is three lines, each saying what it does: begin a journey,
record this run as the list's `setup` section, go there.

```python
class ApplicationStartViewSet(WizardViewSet):
    """The first wizard, before there is a journey to be a section of:
    begin one, record this run as its `setup` section, go there."""

    description = (
        "Chapter 15 as a task list: the setup wizard that mints an application."
    )
    url_name = "readme-apply-start"
    wizard = setup

    def done(self, run):
        journey = GrantApplication.begin(self.request)
        journey.finish("setup", run)
        return redirect(journey.url)
```

`finish()` is the extra line the wizard needs and the plain view does not.
It records the run exactly as finishing the section from the page would —
stashed, its `run_done()` run — so the same wizard is then the journey's
first section, complete on arrival and re-openable from the page like any
other:

```python
class SetupSection(SectionViewSet):
    wizard = setup

    def run_done(self, run):
        record_applying_as(self.get_journey_store(), run)
        return super().run_done(run)
```

### A memory

`store.data` is the journey's record of what its sections decided — the
facts the rest of the journey turns on, kept where every section reads
them without a walk. It is the same bag chapter 10's `run.metadata`
is, kept for the journey rather than for one run, with per-section sub-bags
so sections cannot tread on each other. `record_applying_as` writes
*individual* or *organisation* there, and the governing document section
reads it back:

```python
class DocumentsSection(SectionViewSet):
    """Only for organisations — an answer the setup section wrote at the root."""

    wizard = documents

    @classmethod
    def hidden(cls, store):
        return store.data.get("applying_as") != "organisation"
```

The project section writes the amount and match funding reads it, exactly
as in chapter 14; contact writes the email address, which is how
`journey_done()` below can submit without reading a stash. A stash is for
re-opening; `data` is for reading back.

### An ending

`task_list.is_complete` says the submit button may appear; a POST to the
page presses it:

```python
class GrantApplication(TaskList):
    """What the application is: its sections, in the order the page lists
    them. A value — `GrantApplication.begin(request)` starts one."""

    setup = Section(SetupSection, title="Applying as")
    contact = Section(ContactSection, title="Contact details", reopen_at="review")
    project = Section(ProjectSection, title="Project", reopen_at="review")
    budget = budget
    match_funding = Section(MatchFundingSection, title="Match funding", key="match-funding")
    supporting = Group(
        SupportingInformation,
        title="Supporting information",
        template_name="testapp/nested_task_list.html",
    )


class GrantApplicationViewSet(TaskListViewSet):
    """The page. Mounted under `apply/<journey>/`, so every request —
    the page, the doors, each section beneath it — reads the same journey,
    and two applications are two URLs."""

    description = "Chapter 15: the application's task list, with a submit."
    url_name = "readme-apply"
    template_name = "testapp/journey_task_list.html"
    section_template_name = "testapp/linear_wizard.html"
    task_list = GrantApplication

    def journey_done(self, page, store):
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_page_url())

    def submitted(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )
```

```django
{% if task_list.is_complete %}
  <form method="post">
    {% csrf_token %}
    <button type="submit">Submit application</button>
  </form>
{% endif %}
```

The list is the value; the viewset owns the ending, because the ending
needs a request. `submit()` refuses if any row is not complete, then runs
`journey_done()` — the application's work, and the one thing with no
default — and only once that has returned tombstones the journey. A
`journey_done()` that raises leaves every section resumable. After that,
the runs and stashes are gone; the page answers with `submitted()`, which
is `Http404` until you say what a submitted journey looks like. Anything
the done page needs goes in `store.data`, which the tombstone keeps.

### A task list within the task list

Referees and the governing document are supporting information, and a page
of their own reads better than two more rows on the application. A task
list is an entry like any other, so it is listed like any other: a `Group`.

```python
class SupportingInformation(TaskList):
    referees = Section(RefereesSection, title="Referees")
    documents = Section(DocumentsSection, title="Governing document")
```

```python
class RefereesSection(SectionViewSet):
    """Locked until contact details are finished."""

    wizard = referees

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("contact")
```

A group is a key namespace, not a second record: the group's key is the
prefix every section it lists is keyed under, so the referees section
lives at `supporting:referees` in the journey's store — composed by the
page, never typed. Everything still lives in the one journey record —
`blocked()` reads `contact`, a root key, from two levels down, and the
governing document's `hidden()` reads `store.data["applying_as"]`, written
by the setup wizard at the root. A group has no viewset of its own, so its
page template goes on the `Group`; its page is built as a subclass of the
root's, so a hook you override on `GrantApplicationViewSet` applies to it
too; its row on the parent is its own rows' status; and only the root ends
the journey: a POST to the supporting page goes back up to the application.

### Beyond the session

The store behind all of this is `SessionItemStore(context, journey)`,
and the contract it satisfies is written down as a protocol. The day an
application outgrows the session, a store that keeps the same things in a
table drops in by `journey_store_class` on the root alone — every section
beneath it gets the same one. The
[Journey store reference](../reference/journey-store.md) has the contract
and points at the worked durable store in the test app.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/apply/new/ &nbsp;·&nbsp; **Source:** [`ch15_journey.py`](../../tests/testapp/readme/ch15_journey.py) &nbsp;·&nbsp; **Reference:** [Task lists](../reference/tasklists.md)

---

[← Chapter 14 — Blocked and hidden sections](14-blocked-and-hidden.md) · [Learn](README.md) · [Chapter 16 — Outline, observers and the driver →](16-outline-observers-and-the-driver.md)
