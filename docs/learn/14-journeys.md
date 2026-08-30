# Chapter 14 — Journeys: scope, memory, nesting and an ending

Everything so far, put together. A hub's members add up to something — this
application — and that something is a **journey**. It has three things no
single wizard has: a scope, a memory, and an ending. Every member of it gets
the first two; the root hub — the one no hub lists — owns the third. And
because a hub is a member like any other, a task list can hold a task list.

### A scope

One session can hold two applications in two tabs, and they must never see
each other. Mount the hub under a journey segment, and everything beneath it
— the page, every door, every member's run, the budget and its lines —
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

One pattern, as always. A hub not mounted under a journey uses the one it
declares, `journey = "default"` — one per session, which is what chapters
11 to 13 were.

### Somewhere to be minted

The library does not decide when a journey begins; the first wizard does. It
has no journey yet, so its `done()` mints one, stashes its own answers as the
journey's first member, and sends the applicant to the hub under the new id:

```python
def record_applying_as(store, bound_wizard):
    """Read the one answer the rest of the journey turns on, once, and write
    it where every other member can read it without a walk."""
    step = bound_wizard.path.find_step(name="applying_as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]
```

```python
setup = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as", label="Applying as")
    .configure(
        template_name="testapp/linear_wizard.html",
        observer_class=CountRejections,
    )
)
```

```python
class ApplicationStartViewSet(WizardViewSet):
    url_name = "readme-apply-start"
    wizard = setup

    def done(self, bound_wizard):
        journey = uuid.uuid4().hex
        store = SessionJourneyStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applying_as(store, bound_wizard)
        return redirect("readme-apply", journey=journey)
```

The same wizard is then the journey's first member — re-openable from the
hub like any other, and re-recording its answer when it is re-saved:

```python
    .member("setup", setup, title="Applying as", done=record_applying_as)
```

### A memory

`store.data` is the journey's record of what its members decided — the
facts the rest of the journey turns on, kept where every member reads them
without a walk. It is the same bag chapter 9's `bound_wizard.metadata` is,
kept for the journey rather than for one run, with per-member sub-bags so
members cannot tread on each other. `record_applying_as` writes
*individual* or *organisation* there, and the governing document member
reads it back:

```python
    # Written by the setup member at the root; one record, so a member two
    # hubs down reads it without being handed anything.
    .member(
        "documents",
        documents,
        title="Governing document",
        hidden=lambda store: store.data.get("applying_as") != "organisation",
    )
```

The project member writes the amount and match funding reads it, exactly as
in chapter 13; contact writes the email address, which is how
`journey_done()` below can submit without reading a stash. A stash is for
re-opening; `data` is for reading back.

### An ending

`hub.is_complete` says the submit button may appear; a POST to the hub page
presses it:

```python
application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .member("project", project, title="Project", reopen="review", done=record_amount)
    .collection("budget", budget, title="Budget")
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        hidden=lambda store: store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD,
    )
    .hub("supporting", supporting, title="Supporting information")
)


class GrantApplicationViewSet(HubViewSet):
    template_name = "testapp/journey_hub.html"
    member_template_name = "testapp/linear_wizard.html"
    url_name = "readme-apply"
    hub = application

    def journey_done(self, hub, store):
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
the hub page answers with `submitted()`, which is `Http404` until
you say what a submitted journey looks like. Anything the done page needs
goes in `store.data`, which the tombstone keeps.

### A task list within the task list

Referees and the governing document are supporting information, and a page
of their own reads better than two more rows on the application. A hub is a
member like any other, so it is listed like any other: a `Hub` inside a
`Hub`.

```python
supporting = (
    Hub()
    # Locked until contact details are finished. `contact` is a root key:
    # the record is the journey's, whichever hub reads it.
    .member(
        "referees",
        referees,
        title="Referees",
        blocked=lambda store: not store.has_stash("contact"),
    )
    # Written by the setup member at the root; one record, so a member two
    # hubs down reads it without being handed anything.
    .member(
        "documents",
        documents,
        title="Governing document",
        hidden=lambda store: store.data.get("applying_as") != "organisation",
    )
    .configure(template_name="testapp/nested_hub.html")
)
```

Nesting is a key namespace, not a second record: the nested hub's key is
the prefix every member it lists is keyed under, so the referees member
lives at `supporting:referees` in the journey's store — composed by the
hub, never typed. Everything still lives in the one journey record — the
governing document's `hidden` reads `store.data["applying_as"]`, written by
the setup wizard at the root. A nested hub has no viewset of its own, so
its page template comes from `configure()`; its row on the parent is its
own rows' status; and only the root ends the journey: a POST to the
supporting hub goes back up to the application.

### Beyond the session

The store behind all of this is `SessionCollectionStore(context, journey)`,
and the contract it satisfies is written down as a protocol. The day an
application outgrows the session, a store that keeps the same things in a
table drops in by `journey_store_class` on the root alone — every member
beneath it gets the same one. The
[Journey store reference](../reference/journey-store.md) has the contract
and points at the worked durable store in the test app.

> ▶ **Try it live:** http://127.0.0.1:8000/readme/apply/new/ &nbsp;·&nbsp; **Source:** [`ch14_journey.py`](../../tests/testapp/readme/ch14_journey.py) &nbsp;·&nbsp; **Reference:** [Hubs](../reference/hubs.md)

---

[← Chapter 13 — Blocked and hidden members](13-blocked-and-hidden.md) · [Learn](README.md) · [Chapter 15 — Outline, observers and the driver →](15-outline-observers-and-the-driver.md)
