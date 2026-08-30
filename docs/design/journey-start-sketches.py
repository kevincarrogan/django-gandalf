# ruff: noqa
# Design sketches: deliberately not runnable.
"""Starting a journey from an initiator wizard, five ways.

The common shape: a wizard asks a few mandatory questions, and finishing it
lands the user on a task list where those answers are already the first
section, complete and re-openable. Everything here is the start wizard's
`done()` and the URLconf; the task list (`GrantApplication`, a `TaskList`
with a `setup` section) is the same in every sketch.

The question each sketch answers differently: who is responsible for a
journey *beginning* — and how much of that does the reader have to see?

What every version has to do, somehow:

    1. make a journey id
    2. build the list's store for it
    3. record the finished run as the `setup` section — stashed under the
       section's key and label, its `run_done()` run
    4. redirect to the list's page under the new id
"""

# =============================================================================
# The task list every sketch starts (tests/testapp/readme/ch14_tasklist.py)
# =============================================================================
#
# `setup` is the section the start wizard's answers become. `SetupMember`
# is the section's viewset: the same wizard, plus what to do when it
# finishes. `GrantApplication` is a TemplateView underneath, mounted with
# `include(GrantApplicationViewSet.urls())` under `apply/<slug:journey>/`.


class SetupMember(MemberViewSet):
    wizard = setup

    def run_done(self, bound_wizard):
        record_applying_as(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class GrantApplication(TaskList):
    setup = Section(SetupMember, title="Applying as")
    contact = Section(ContactMember, title="Contact details", reopen="review")
    project = Section(ProjectMember, title="Project", reopen="review")
    budget = AddAnother(budget, title="Budget")
    match_funding = Section(MatchFundingMember, title="Match funding")
    supporting = Group(SupportingInformation, title="Supporting information")


class GrantApplicationViewSet(TaskListViewSet):
    url_name = "apply"
    template_name = "apply/hub.html"
    member_template_name = "apply/step.html"
    tasklist = GrantApplication

    def journey_done(self, hub, store):
        application = Application.objects.create()
        application.submit(store.data["email"])
        store.data["reference"] = application.reference
        return redirect(self.get_page_url())


# =============================================================================
# 0. By hand (the branch's ch14_journey.py)
# =============================================================================
#
# Every one of the four steps written out. Three facts the list already
# knows are repeated: the store class, the stash label (must equal the
# section's key), and the page's URL name. Step 3 is only half done — the
# stash is written but `SetupMember.run_done()` is not run, so
# `record_applying_as` has to be called by hand as well.


class ApplicationStartViewSet(WizardViewSet):
    url_name = "apply-start"
    wizard = setup

    def done(self, bound_wizard):
        journey = uuid.uuid4().hex
        store = SessionJourneyStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applying_as(store, bound_wizard)
        return redirect("apply", journey=journey)


urlpatterns = [
    path("apply/new/", include(ApplicationStartViewSet.urls())),
    path("apply/<slug:journey>/", include(GrantApplicationViewSet.urls())),
]


# =============================================================================
# M. mint() (was on the branch; replaced by 1)
# =============================================================================
#
# One call. The list instantiates its own `setup` member viewset under a
# new id and calls its `done()`, then redirects. Correct, and nothing is
# repeated — but the name says "make an id" and the shape says "the list
# does something to a member on your behalf", neither of which is what you
# see.


class ApplicationStartViewSet(WizardViewSet):
    url_name = "apply-start"
    wizard = setup

    def done(self, bound_wizard):
        return GrantApplication.mint(self.request, bound_wizard, section="setup")


# =============================================================================
# 1. A journey you begin, then finish a section of
# =============================================================================
#
# The list contributes exactly its scope: `begin()` returns a handle — the
# id, the list's store, the page URL. `finish()` on the handle does what the
# door does when a section completes. Three lines, each saying what it does;
# nothing hidden behind another. The start wizard stays an ordinary
# WizardViewSet with an ordinary done().


class ApplicationStartViewSet(WizardViewSet):
    url_name = "apply-start"
    wizard = setup

    def done(self, bound_wizard):
        journey = GrantApplication.begin(self.request)
        journey.finish("setup", bound_wizard)
        return redirect(journey.url)


# Variation 1b — the same handle, from the list's own page for an "apply
# again" link, or from a management command or an agent: nothing about
# `begin()` needs a wizard.
def start_application(request):
    return redirect(GrantApplication.begin(request).url)


# =============================================================================
# 2. A mixin on the start wizard — the FormView ladder
# =============================================================================
#
# A plain wizard gains "starts a journey" by mixing it in, the way a Form
# gains a view. Two attributes say which list and which section; done() is
# the mixin's. This is what `WizardMemberMixin` on main looked like, minus
# the strings that had to agree with anything — `journey` is the class
# itself, `section` is checked against its rows.


class ApplicationStartViewSet(StartsJourney, WizardViewSet):
    url_name = "apply-start"
    journey = GrantApplication
    section = "setup"
    wizard = setup

    # Optional: the hook for anything beyond the recording.
    def journey_started(self, journey, bound_wizard):
        notify_ops(journey.id)


# =============================================================================
# 3. Finishing a section with no journey on the URL starts one
# =============================================================================
#
# No code. The list's own `setup` member viewset is mounted a second time,
# at new/, with no journey segment; finishing it there begins a journey
# instead of stashing into the default one. The start wizard and the
# section are literally the same class.
#
# The rule to learn is the cost: "a section finished outside a journey
# starts one". And a list on the fixed default journey (chapters 11–13)
# cannot use it, because for that list "no journey on the URL" *is* the
# journey.

urlpatterns = [
    path("apply/new/", include(GrantApplicationViewSet.viewset_for("setup").urls())),
    path("apply/<slug:journey>/", include(GrantApplicationViewSet.urls())),
]


# =============================================================================
# 4. mint(), named for what it is
# =============================================================================
#
# Sketch M with an honest name and the recording made visible: `finished=`
# says what is recorded as what. One call. Still the list doing a member's
# work behind a classmethod — sketch 1 with its three lines folded back in.


class ApplicationStartViewSet(WizardViewSet):
    url_name = "apply-start"
    wizard = setup

    def done(self, bound_wizard):
        return GrantApplication.begin(self.request, finished={"setup": bound_wizard})


# =============================================================================
# 5. The list publishes new/ itself (the retracted Start row)
# =============================================================================
#
# For the record. `Start(SetupMember)` in the class body; the list publishes
# `new/` and `<journey>/` and is mounted at `apply/`. Zero code in the app,
# but the list becomes responsible for its own beginning — which is not its
# concern: a journey is a record in a store, and anything may begin one.


class GrantApplication(TaskList):
    url_name = "apply"
    setup = Start(SetupMember, title="Applying as")
    ...


urlpatterns = [path("apply/", include(GrantApplicationViewSet.urls()))]
