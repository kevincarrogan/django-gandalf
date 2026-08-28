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
reads its journey off the URL, and so does every member mounted under the
same segment, so two applications in two tabs are two URLs and two records
in one session that never see each other:

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
11 to 13 were.

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


class SetupMemberViewSet(WizardMemberMixin, WizardViewSet):
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
as")` — the same wizard as a member mounted under the journey — so the setup
answers are re-openable like any other member.

### A memory

`store.data` is the journey's record of what its members decided: a
JSON-safe mapping written through on every assignment, with
`for_member(key)` sub-bags so members cannot tread on each other. It is the
same bag chapter 9's `bound_wizard.metadata` is, kept for the journey rather
than for one run. `record_applying_as` writes *individual* or *organisation*
there, and the governing document member reads it back:

```python
class DocumentsMemberViewSet(WizardMemberMixin, WizardViewSet):
    member_key = "documents"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(GoverningDocumentForm, name="document", label="Document")

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("applying_as") != "organisation"
```

The project member writes the amount and match funding reads it, exactly as
in chapter 13; contact writes the email address, which is how
`journey_done()` below can submit without reading a stash. A stash is for
re-opening; `data` is for reading back.

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

`submit()` refuses if any row is not complete, then runs `journey_done()` —
the application's work, and the one thing with no default — and only once
that has returned tombstones the journey. A `journey_done()` that raises
leaves every member resumable. After that, the runs and stashes are gone;
the hub page answers with `journey_completed()`, which is `Http404` until
you say what a submitted journey looks like. Anything the done page needs
goes in `store.data`, which the tombstone keeps.

### A task list within the task list

Referees and the governing document are supporting information, and a page
of their own reads better than two more rows on the application. A hub is a
member like any other, so it is listed like any other — and it declares the
same two things a wizard member does: the key it sits under, and the hub it
returns to.

```python
class RefereesMemberViewSet(WizardMemberMixin, WizardViewSet):
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

Nesting is a key namespace, not a second record: a nested hub's
`member_key` is the prefix every member it lists is keyed under, so a wizard
two hubs down declares its full key, `"supporting:referees"`. Everything
still lives in the one journey record — the governing document's `hidden()`
reads `store.data["applying_as"]`, written by the setup wizard at the root.
A hub's row is its own rows' status, and only the root ends the journey: a
POST to the supporting hub goes back up to the application.

### Beyond the session

The store behind all of this is `SessionJourneyStore(context, journey)`, and
the contract it satisfies is written down as a protocol. The day an
application outgrows the session, a store that keeps the same things in a
table drops in by `journey_store_class` alone. The
[Journey store reference](../reference/journey-store.md) has the contract
and points at the worked durable store in the test app.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/apply/new/ &nbsp;·&nbsp; **Source:** [`ch14_journey.py`](../../tests/testapp/readme/ch14_journey.py) &nbsp;·&nbsp; **Reference:** [Hubs](../reference/hubs.md)

---

[← Chapter 13 — Blocked and hidden members](13-blocked-and-hidden.md) · [Learn](README.md) · [Chapter 15 — Outline, observers and the driver →](15-outline-observers-and-the-driver.md)
