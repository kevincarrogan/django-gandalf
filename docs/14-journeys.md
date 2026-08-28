# Chapter 14 — Journeys: scope, memory, nesting and an ending

Everything so far, put together. A hub's members add up to something — this
application — and that something is a **journey**. It has three things no
single wizard has: a scope, a memory, and an ending. Every member of it gets
the first two; the root hub — the one no hub lists — owns the third. And
because a hub is itself a member, a journey's task lists nest.

### A scope

Everything a hub keeps — which run each member is being answered in, the
stash a finished one left, a collection's items, what the members decided —
lives in one record per journey. A hub mounted under a `<journey>` segment
reads its journey off the URL, and so does every member, collection page and
item wizard mounted under the same segment, so two applications in two tabs
are two URLs and two records in one session that never see each other:

```python
urlpatterns = [
    path("readme/apply/new/", include(ApplicationStartViewSet.urls())),
    path("readme/apply/<slug:journey>/", include(GrantApplicationHubView.urls())),
    path("readme/apply-setup/<slug:journey>/", include(SetupMemberViewSet.urls())),
    path("readme/apply-contact/<slug:journey>/", include(ContactMemberViewSet.urls())),
    path("readme/apply-project/<slug:journey>/", include(ProjectMemberViewSet.urls())),
    path("readme/apply-budget/<slug:journey>/", include(BudgetCollectionView.urls())),
    path("readme/apply-budget-line/<slug:journey>/<uuid:item>/", include(BudgetLineViewSet.urls())),
    path("readme/apply-match-funding/<slug:journey>/", include(MatchFundingMemberViewSet.urls())),
    path("readme/apply-referees/<slug:journey>/", include(RefereesMemberViewSet.urls())),
    path("readme/apply-documents/<slug:journey>/", include(DocumentsMemberViewSet.urls())),
    path("readme/apply-supporting/<slug:journey>/", include(SupportingHubView.urls())),
]
```

Siblings, as always. A hub not mounted under a journey uses the one it
declares, `journey = "default"` — one per session, which is what chapters
11 to 13 were. Every member's viewset declares the same pair (`journey`,
`journey_url_kwarg`), and the hub refuses one that does not, since it would
finish into a record the hub never reads.

### Somewhere to be minted

The library does not decide when a journey begins; the first wizard does. It
has no journey yet, so its `done()` mints one, stashes its own answers as the
journey's first member, and sends the applicant to the hub under the new id:

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
        store = SessionJourneyStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applying_as(store, bound_wizard)
        return redirect("readme-apply-hub", journey=journey)


class SetupMemberViewSet(RunMemberMixin, WizardViewSet):
    """The same wizard, once a journey exists."""

    url_name = "readme-apply-setup"
    member_key = "setup"
    hub_url_name = "readme-apply-hub"
    wizard = ApplicationStartViewSet.wizard

    def run_done(self, bound_wizard):
        record_applying_as(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)
```

The hub then lists `Member("setup", SetupMemberViewSet, title="Applying
as")` — the same wizard as a `RunMemberMixin` viewset mounted under the journey
— so the setup answers are re-openable like any other member.

### A memory

`store.data` is the journey's record of what its members decided: a
JSON-safe mapping written through on every assignment, with
`for_member(key)` sub-bags so members cannot tread on each other or on the
journey. It is the same bag chapter 9's `bound_wizard.metadata` is, kept for
the journey rather than for one run, and it is the answer to the question a
stash cannot answer cheaply. `record_applying_as` writes *individual* or
*organisation* there, and the governing document member reads it back:

```python
class DocumentsMemberViewSet(RunMemberMixin, WizardViewSet):
    member_key = "documents"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(GoverningDocumentForm, name="document", label="Document")

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("applying_as") != "organisation"
```

The project member writes the amount and match funding reads it, exactly as
in chapter 13; referees lock on `has_stash("contact")`; contact writes the
email address, which is how `journey_done()` below can submit without
reading a stash's positional state — a stash is for re-opening, `data` is
for reading back. It is the bargain a
collection strikes to name its rows — one walk at completion, none per render
— generalised from one cached title to the whole journey.

### An ending

`hub.is_complete` says the submit button may appear; a POST to the hub page
presses it:

```python
class GrantApplicationHubView(HubView):
    template_name = "testapp/journey_hub.html"
    url_name = "readme-apply-hub"
    member_url_name = "readme-apply-hub-member"
    members = [
        Member("setup", SetupMemberViewSet, title="Applying as"),
        Member("contact", ContactMemberViewSet, title="Contact details", reopen_step="review"),
        Member("project", ProjectMemberViewSet, title="Project", reopen_step="review"),
        Member("budget", BudgetCollectionView, title="Budget"),
        Member("match_funding", MatchFundingMemberViewSet, title="Match funding"),
        Member("supporting", SupportingHubView, title="Supporting information"),
    ]

    def journey_done(self, hub, store):
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_page_url())

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
has returned tombstones the journey, exactly as `RunMemberMixin.done()` runs
`run_done()` before clearing the run. A `journey_done()` that raises
leaves every member resumable. It runs inside the window where the stashes
are still readable; anything the done page needs goes in `store.data`, which
the tombstone keeps.

After that, the runs and stashes are gone, so a submitted journey can neither
be edited nor keep growing the session. The hub page and every door answer
with `journey_completed()` — `Http404` until you say what a submitted journey
looks like — a collection page and a nested hub send the user up to the hub
above them, and each member's own wizard sends a bookmarked step URL back to
its hub. Only the ten most recently completed journeys are kept per session.

### A task list within the task list

Referees and the governing document are supporting information, and a page
of their own reads better than two more rows on the application. A hub is a
member like any other, so it is listed like any other — and it declares the
same two things a wizard member does: the key it sits under, and the hub it
returns to.

```python
class RefereesMemberViewSet(RunMemberMixin, WizardViewSet):
    member_key = "supporting:referees"
    hub_url_name = "readme-apply-supporting"
    ...


class SupportingHubView(HubView):
    url_name = "readme-apply-supporting"
    member_url_name = "readme-apply-supporting-member"
    member_key = "supporting"
    hub_url_name = "readme-apply-hub"
    members = [
        Member("referees", RefereesMemberViewSet, title="Referees"),
        Member("documents", DocumentsMemberViewSet, title="Governing document"),
    ]
```

**Nesting is a key namespace, not a second record.** A nested hub's
`member_key` is the prefix every member it lists is keyed under
(`full_key()`), the way a collection prefixes its items — so a wizard two
hubs down declares its full key, `"supporting:referees"`, and the hub checks
it agrees, exactly as it checks a drifted `member_key` or `hub_url_name` one
level up. Everything still lives in the one journey record: the governing
document's `hidden()` reads `store.data["applying_as"]`, written by the setup
wizard at the root, without being handed anything.

**A hub's row is its own rows.** The application never reads a stash for
`supporting`; it asks the hub's `status_for()`, which derives the same
status the hub's own page shows — Not started, Incomplete, Complete — from
the members under its prefix. Still no walk. The row links straight at the
hub's page, and so does the door.

**Only the root ends the journey.** A POST to the supporting hub is its
submit too, but `is_nested` is true, so it runs `hub_done()` — back to the
application by default — and tombstones nothing. `journey_done()` and the
tombstone are the root's alone, and they take every nested run and stash
with them. There is no new word for another layer: a hub in a hub in a hub
is three hubs, and `JourneyMemberMixin` is what every one of them and every
wizard share.

### Beyond the session

The store behind all of this is one class,
`SessionJourneyStore(context, journey)`, and the contract it satisfies is
written down as `gandalf.types.JourneyStore` (and `CollectionStore` for a
collection): the member runs and stashes, `data`, `complete()` and
`is_complete()`, plus a collection's registry. An application of seven
members is a lot to hold in a cookie; the day it outgrows the session, a
store that keeps the same things in a table drops in by `journey_store_class`
alone — [`tests/testapp/durable.py`](../tests/testapp/durable.py) is that store,
scoped by owner and by journey, and the swap is the same one chapter 9
described for runs.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/apply/new/ &nbsp;·&nbsp; **Source:** [`ch14_journey.py`](../tests/testapp/readme/ch14_journey.py)

---

[← Chapter 13 — Blocked and hidden members](13-blocked-and-hidden.md) · [README](../README.md) · [Chapter 15 — Outline, observers and the driver →](15-outline-observers-and-the-driver.md)
