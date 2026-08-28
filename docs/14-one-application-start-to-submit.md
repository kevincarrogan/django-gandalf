# Chapter 14 — One application, start to submit

Everything so far, put together. A hub's sections add up to something — this
application — and that something is a **journey**. It has three things a
single hub does not: a scope, a memory, and an ending.

### A scope

Everything a hub keeps — which run each section is being answered in, the
stash a finished one left, a collection's items, what the sections decided —
lives in one record per journey. A hub mounted under a `<journey>` segment
reads its journey off the URL, and so does every section, collection page and
item wizard mounted under the same segment, so two applications in two tabs
are two URLs and two records in one session that never see each other:

```python
urlpatterns = [
    path("readme/apply/new/", include(ApplicationStartViewSet.urls())),
    path("readme/apply/<slug:journey>/", include(GrantApplicationHubView.urls())),
    path("readme/apply-setup/<slug:journey>/", include(SetupSectionViewSet.urls())),
    path("readme/apply-contact/<slug:journey>/", include(ContactSectionViewSet.urls())),
    path("readme/apply-project/<slug:journey>/", include(ProjectSectionViewSet.urls())),
    path("readme/apply-budget/<slug:journey>/", include(BudgetCollectionView.urls())),
    path("readme/apply-budget-line/<slug:journey>/<uuid:item>/", include(BudgetLineViewSet.urls())),
    path("readme/apply-match-funding/<slug:journey>/", include(MatchFundingSectionViewSet.urls())),
    path("readme/apply-referees/<slug:journey>/", include(RefereesSectionViewSet.urls())),
    path("readme/apply-documents/<slug:journey>/", include(DocumentsSectionViewSet.urls())),
]
```

Siblings, as always. A hub not mounted under a journey uses the one it
declares, `journey = "default"` — one per session, which is what chapters
11 to 13 were. Every section's viewset declares the same pair (`journey`,
`journey_url_kwarg`), and the hub refuses one that does not, since it would
finish into a record the hub never reads.

### Somewhere to be minted

The library does not decide when a journey begins; the first wizard does. It
has no journey yet, so its `done()` mints one, stashes its own answers as the
journey's first section, and sends the applicant to the hub under the new id:

```python
def record_applying_as(store, bound_wizard):
    step = bound_wizard.path.find_step(name="applying_as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]


class ApplicationStartViewSet(WizardViewSet):
    url_name = "readme-apply-start"
    wizard = (
        Wizard()
        .step(ApplyingAsForm, name="applying_as", label="Applying as")
        .configure(
            template_name="testapp/linear_wizard.html",
            observer_class=CountRejections,      # chapter 15
        )
    )

    def done(self, bound_wizard):
        journey = uuid.uuid4().hex
        store = SessionSectionStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applying_as(store, bound_wizard)
        return redirect("readme-apply-hub", journey=journey)


class SetupSectionViewSet(SectionMixin, WizardViewSet):
    """The same wizard, once a journey exists."""

    url_name = "readme-apply-setup"
    section_key = "setup"
    hub_url_name = "readme-apply-hub"
    wizard = ApplicationStartViewSet.wizard

    def section_done(self, bound_wizard):
        record_applying_as(self.get_section_store(), bound_wizard)
        return super().section_done(bound_wizard)
```

The hub then lists `Section("setup", SetupSectionViewSet, title="Applying
as")` — the same wizard as a `SectionMixin` viewset mounted under the journey
— so the setup answers are re-openable like any other section.

### A memory

`store.data` is the journey's record of what its sections decided: a
JSON-safe mapping written through on every assignment, with
`for_section(key)` sub-bags so sections cannot tread on each other or on the
journey. It is the same bag chapter 9's `bound_wizard.metadata` is, kept for
the journey rather than for one run, and it is the answer to the question a
stash cannot answer cheaply. `record_applying_as` writes *individual* or
*organisation* there, and the governing document section reads it back:

```python
class DocumentsSectionViewSet(SectionMixin, WizardViewSet):
    section_key = "documents"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(GoverningDocumentForm, name="document", label="Document")

    @classmethod
    def hidden(cls, request, section, store):
        return store.data.get("applying_as") != "organisation"
```

The project section writes the amount and match funding reads it, exactly as
in chapter 13; referees lock on `has_stash("contact")`. It is the bargain a
collection strikes to name its rows — one walk at completion, none per render
— generalised from one cached title to the whole journey.

### An ending

`hub.is_complete` says the submit button may appear; a POST to the hub page
presses it:

```python
class GrantApplicationHubView(HubView):
    template_name = "testapp/journey_hub.html"
    url_name = "readme-apply-hub"
    section_url_name = "readme-apply-hub-section"
    sections = [
        Section("setup", SetupSectionViewSet, title="Applying as"),
        Section("contact", ContactSectionViewSet, title="Contact details", reopen_step="review"),
        Section("project", ProjectSectionViewSet, title="Project", reopen_step="review"),
        BudgetCollectionView.as_section("budget", title="Budget"),
        Section("match_funding", MatchFundingSectionViewSet, title="Match funding"),
        Section("referees", RefereesSectionViewSet, title="Referees"),
        Section("documents", DocumentsSectionViewSet, title="Governing document"),
    ]

    def journey_done(self, hub, store):
        contact = store.get_stash("contact")
        application = Application.objects.create()
        application.submit(contact["state"][1]["step"]["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_hub_url())

    def journey_completed(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )
```

```django
{% if hub.is_complete %}
  <form method="post">
    {% csrf_token %}
    <button type="submit">Submit application</button>
  </form>
{% endif %}
```

`submit()` refuses if any row is not complete (`hub_incomplete()`, which
sends the user back to the hub by default), then runs `journey_done()` — the
application's work, and the one thing with no default — and only once that
has returned tombstones the journey, exactly as `SectionMixin.done()` runs
`section_done()` before clearing the run. A `journey_done()` that raises
leaves every section resumable. It runs inside the window where the stashes
are still readable; anything the done page needs goes in `store.data`, which
the tombstone keeps.

After that, the runs and stashes are gone, so a submitted journey can neither
be edited nor keep growing the session. The hub page and every door answer
with `journey_completed()` — `Http404` until you say what a submitted journey
looks like — a collection page sends the user on to its `continue_url`, and
each section's own wizard sends a bookmarked step URL back to the hub. Only
the ten most recently completed journeys are kept per session.

### Beyond the session

The store behind all of this is one class,
`SessionSectionStore(context, journey)`, and the contract it satisfies is
written down as `gandalf.types.SectionStore` (and `CollectionStore` for a
collection): the section runs and stashes, `data`, `complete()` and
`is_complete()`, plus a collection's registry. An application of seven
sections is a lot to hold in a cookie; the day it outgrows the session, a
store that keeps the same things in a table drops in by `section_store_class`
alone — [`tests/testapp/durable.py`](../tests/testapp/durable.py) is that store,
scoped by owner and by journey, and the swap is the same one chapter 9
described for runs.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/apply/new/ &nbsp;·&nbsp; **Source:** [`ch14_journey.py`](../tests/testapp/readme/ch14_journey.py)

---

[← Chapter 13 — Locked and hidden](13-locked-and-hidden.md) · [README](../README.md) · [Chapter 15 — Knowing what you built →](15-knowing-what-you-built.md)
