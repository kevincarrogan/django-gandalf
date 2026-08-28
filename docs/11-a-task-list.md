# Chapter 11 — A task list

> **Optional module.** `gandalf.sections` is a pattern built on everything
> above, with its own vocabulary and a second storage seam. Nothing in the
> core depends on it.

An application is not one wizard. Contact details, an address, the project,
the budget, referees — each is its own thing, finished on its own, in any
order, and re-opened later. Chapter 10 did the stashing by hand; a **hub** is
that pattern with the bookkeeping owned by the library: declare the sections,
mix `SectionMixin` into each section's viewset, and the hub renders a row per
section carrying its title, its status and one URL that does the right thing
whichever state it is in.

```python
from gandalf.sections import HubView, Section, SectionMixin


class ContactSectionViewSet(SectionMixin, WizardViewSet):
    url_name = "readme-hub-contact"
    template_name = "testapp/linear_wizard.html"
    section_key = "contact"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(ApplicantForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        # A review step is what makes re-opening safe: without it, one
        # successful edit walks straight through to done() again.
        .step(ReviewStepView, name="review")
    )


class AddressSectionViewSet(SectionMixin, WizardViewSet):
    url_name = "readme-hub-address"
    template_name = "testapp/linear_wizard.html"
    section_key = "address"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="address", label="Address")
        .step(AddressReviewStepView, name="review")
    )


class GrantHubView(HubView):
    template_name = "testapp/readme_hub.html"
    url_name = "readme-hub"
    section_url_name = "readme-hub-section"
    sections = [
        Section("contact", ContactSectionViewSet, title="Contact details", reopen_step="review"),
        Section("address", AddressSectionViewSet, title="Address", reopen_step="review"),
    ]
```

A hub is mounted exactly like a wizard, and publishes two patterns from
`url_name` — the page, and the door into one section. **Mount the sections
beside it, never beneath it:** the hub's `<slug:section>/` door matches any
single segment and would swallow them.

```python
urlpatterns = [
    path("readme/hub/", include(GrantHubView.urls())),
    path("readme/hub-contact/", include(ContactSectionViewSet.urls())),
    path("readme/hub-address/", include(AddressSectionViewSet.urls())),
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

`hub.count`, `hub.completed` and `hub.remaining` are the task list heading;
`hub.status` is derived for the set — **Complete** when every row is, **Not
started** when none has been touched, **Incomplete** in between — so the
button that submits the whole thing reads one flag rather than counting rows
in the view. The rows are built once per request, so asking is free.

**Sections override `section_done()`, never `done()`.** `done()` belongs to
the mixin: it stashes the finished answers under `section_key`, which is the
only thing that can tell the hub the section is finished, then hands off to
`section_done()` for what runs once per edit — saving to your models, say —
whose default sends the user back to the hub. A subclass that replaced
`done()` would leave the section reading as not started forever.

The two strings a section repeats back to its hub — `section_key` and
`hub_url_name` — are checked against the hub's own declaration when it
renders, because each holds only for as long as both sides stay typed the
same. A drifted key means the hub reads a stash nothing writes; a drifted
`hub_url_name` means finishing quietly deposits the user somewhere that does
not list the section they just finished.

### What each status means

| Status | Comes from |
| --- | --- |
| **Complete** | A stash under the section's key — the section ran to its own end and `done()` fired |
| **Incomplete** | A recorded run holding at least one submission |
| **Not started** | Everything else, including a section opened and left unanswered, and one whose run has expired |
| **Cannot start yet** | The section's own `blocked()` — chapter 13 |

A row is deliberately cheap: two storage reads and a `reverse()`, no walk, so
a hub of six sections costs six dict lookups rather than a form `clean()` per
answered step per row. Whether the stored answers still *validate* is not
asked — it would not change the row.

### Every link is a step URL, never a bare run URL

This is the one thing worth understanding. A run whose every stored answer
validates **completes on a GET**. So a hub row can never point at the
wizard's own URL: it would fire the section's side effects on a click. Rows
link to the hub's own door, which is the only place that can afford to ask
what exists: it resumes a live run, re-opens a stash, or starts a fresh run,
and every arm ends at `BoundWizard.entry_url()` — a step URL by construction.
Resuming is tried *before* re-opening, so a section already being edited
continues that edit rather than resurrecting a second run beside it.

### Re-opening is edit-and-re-save

A re-opened section arrives with every answer already valid, so **the next
successful submission walks to the end and fires `done()` again** — the user
changed something and it saved. `reopen_step="review"` lands them on their
answers with a change link each, rather than at step one.

### Reaching a run from outside its own request

The hub is built on three classmethods that bind a wizard outside its own
dispatch, and they are public API in their own right:

| Method | Returns |
| --- | --- |
| `MyViewSet.begin(request, **url_kwargs)` | A fresh run — the start URL minus the redirect |
| `MyViewSet.inspect(request, run_id, **url_kwargs)` | An existing run, bound and ready to read. Walks nothing; raises `RunNotFound` |
| `MyViewSet.reopen(request, payload, ...)` | A run seeded from a stash — the run behind `resurrect()` |

Each hands back a `BoundWizard`. A tombstoned run is *found*, not missing, so
check `is_complete` before running one.

### Customising

Every decision is a hook. `get_sections()` chooses the sections per request,
`get_section_status()` decides how far one has got, `get_hub_status()` how
far they have got between them — override it where an optional section should
not hold the whole page back — `get_section_title()` names it,
`get_status_label()` reworks the wording, and `resume_section()` /
`reopen_section()` / `start_section()` each own one way into a run.
`stash_unusable()` handles a payload whose `label` no longer matches — it
re-raises by default, because silently starting over looks to the user
exactly like their answers vanishing.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/hub/ &nbsp;·&nbsp; **Source:** [`ch11_hub.py`](../tests/testapp/readme/ch11_hub.py)

---

[← Chapter 10 — Coming back later](10-coming-back-later.md) · [README](../README.md) · [Chapter 12 — Budget lines →](12-budget-lines.md)
