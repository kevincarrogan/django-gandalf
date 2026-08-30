# ruff: noqa
# Design sketches: deliberately not runnable.
"""The same application — chapter 14's grant application — declared eleven
ways, starting from where main is today. None of this runs; it exists
to be read side by side.

The question each sketch answers differently: where does a member's
*name*, *title*, *gate* and *done* live, and how does nesting read?

The wizards themselves are the same in every sketch and elided:

    setup, contact, project, budget_line, match_funding, referees, documents

as are the three callbacks:

    record_applying_as(store, bound_wizard)
    record_email(store, bound_wizard)
    record_amount(store, bound_wizard)
"""

# =============================================================================
# 0. Where we started (main): a viewset class per member, wired by string
# =============================================================================
#
# The hub lists members by key; each member repeats that key and the hub's
# URL name so the two can be checked against each other. Nesting is a
# prefix typed by hand. Gates and done are classmethods and methods on the
# member's own viewset. Everything is mounted as siblings, one path each.


class SetupMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-setup"
    template_name = "apply/step.html"
    member_key = "setup"
    hub_url_name = "apply"
    wizard = setup

    def run_done(self, bound_wizard):
        record_applying_as(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class ContactMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-contact"
    template_name = "apply/step.html"
    member_key = "contact"
    hub_url_name = "apply"
    wizard = contact

    def run_done(self, bound_wizard):
        record_email(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class ProjectMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-project"
    template_name = "apply/step.html"
    member_key = "project"
    hub_url_name = "apply"
    wizard = project

    def run_done(self, bound_wizard):
        record_amount(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class BudgetLineViewSet(ItemMemberMixin, WizardViewSet):
    url_name = "apply-budget-line"
    template_name = "apply/step.html"
    collection_key = "budget"
    hub_url_name = "apply-budget"
    item_title_step = "line"
    item_title_field = "item"
    wizard = budget_line


class BudgetCollectionView(CollectionView):
    template_name = "apply/budget.html"
    remove_template_name = "apply/budget_remove.html"
    url_name = "apply-budget"
    member_key = "budget"
    item_viewset = BudgetLineViewSet
    item_name = "Budget line"
    item_reopen_step = "review"
    min_items = 1
    hub_url_name = "apply"


class MatchFundingMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-match-funding"
    template_name = "apply/step.html"
    member_key = "match_funding"
    hub_url_name = "apply"
    wizard = match_funding

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("amount", 0) <= 10_000


class RefereesMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-referees"
    template_name = "apply/step.html"
    member_key = "supporting:referees"
    hub_url_name = "apply-supporting"
    wizard = referees

    @classmethod
    def blocked(cls, request, member, store):
        return not store.has_stash("contact")


class DocumentsMemberViewSet(WizardMemberMixin, WizardViewSet):
    url_name = "apply-documents"
    template_name = "apply/upload_step.html"
    member_key = "supporting:documents"
    hub_url_name = "apply-supporting"
    wizard = documents

    @classmethod
    def hidden(cls, request, member, store):
        return store.data.get("applying_as") != "organisation"


class SupportingHubView(HubView):
    template_name = "apply/supporting.html"
    url_name = "apply-supporting"
    member_url_name = "apply-supporting-member"
    member_key = "supporting"
    hub_url_name = "apply"
    members = [
        Member("referees", RefereesMemberViewSet, title="Referees"),
        Member("documents", DocumentsMemberViewSet, title="Governing document"),
    ]


class GrantApplicationHubView(HubView):
    template_name = "apply/hub.html"
    url_name = "apply"
    member_url_name = "apply-member"
    members = [
        Member("setup", SetupMemberViewSet, title="Applying as"),
        Member(
            "contact",
            ContactMemberViewSet,
            title="Contact details",
            reopen_step="review",
        ),
        Member("project", ProjectMemberViewSet, title="Project", reopen_step="review"),
        Member("budget", BudgetCollectionView, title="Budget"),
        Member("match_funding", MatchFundingMemberViewSet, title="Match funding"),
        Member("supporting", SupportingHubView, title="Supporting information"),
    ]

    def journey_done(self, hub, store): ...


urlpatterns = [
    path("apply/<slug:journey>/", include(GrantApplicationHubView.urls())),
    path("apply-setup/<slug:journey>/", include(SetupMemberViewSet.urls())),
    path("apply-contact/<slug:journey>/", include(ContactMemberViewSet.urls())),
    path("apply-project/<slug:journey>/", include(ProjectMemberViewSet.urls())),
    path("apply-budget/<slug:journey>/", include(BudgetCollectionView.urls())),
    path(
        "apply-budget-line/<slug:journey>/<uuid:item>/",
        include(BudgetLineViewSet.urls()),
    ),
    path(
        "apply-match-funding/<slug:journey>/", include(MatchFundingMemberViewSet.urls())
    ),
    path("apply-referees/<slug:journey>/", include(RefereesMemberViewSet.urls())),
    path("apply-documents/<slug:journey>/", include(DocumentsMemberViewSet.urls())),
    path("apply-supporting/<slug:journey>/", include(SupportingHubView.urls())),
]


# =============================================================================
# A. The branch (PR #105): a builder, keys as strings, gates as lambdas
# =============================================================================
#
# Rhymes with Wizard(). Every fact is a keyword on the row it belongs to.
# Costs: quoted keys; `lambda store:` on every gate; presentation via
# .configure(); the root's hooks live on a separate class.

supporting = (
    Hub()
    .member(
        "referees",
        referees,
        title="Referees",
        blocked=lambda store: not store.has_stash("contact"),
    )
    .member(
        "documents",
        documents,
        title="Governing document",
        hidden=lambda store: store.data.get("applying_as") != "organisation",
    )
    .configure(template_name="apply/supporting.html")
)

application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .member("project", project, title="Project", reopen="review", done=record_amount)
    .collection(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        hidden=lambda store: store.data.get("amount", 0) <= 10_000,
    )
    .hub("supporting", supporting, title="Supporting information")
)


class GrantApplicationViewSet(HubViewSet):
    url_name = "apply"
    template_name = "apply/hub.html"
    member_template_name = "apply/step.html"
    hub = application

    def journey_done(self, hub, store): ...


# =============================================================================
# B. Class body: attribute name is the key, methods are the hooks
# =============================================================================
#
# The most Django-native shape (Model, Form, DRF serializer). No quoted
# keys, no lambdas, gates and done are named methods next to the rows,
# presentation and hooks on the same object as the structure. Costs: does
# not rhyme with Wizard(); nesting is a nested class; a metaclass.


class SupportingInformation(Hub):
    template_name = "apply/supporting.html"

    referees = Member(referees, title="Referees")
    documents = Member(documents, title="Governing document")

    def referees_blocked(self, store):
        return not store.has_stash("contact")

    def documents_hidden(self, store):
        return store.data.get("applying_as") != "organisation"


class GrantApplication(Journey):
    url_name = "apply"
    template_name = "apply/hub.html"
    member_template_name = "apply/step.html"

    setup = Member(setup, title="Applying as", done=record_applying_as)
    contact = Member(
        contact, title="Contact details", reopen="review", done=record_email
    )
    project = Member(project, title="Project", reopen="review", done=record_amount)
    budget = Collection(
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    match_funding = Member(match_funding, title="Match funding")
    supporting = SupportingInformation(title="Supporting information")

    def match_funding_hidden(self, store):
        return store.data.get("amount", 0) <= 10_000

    def journey_done(self, hub, store): ...


# =============================================================================
# C. Builder, but the gates read like branch(): named predicates, no lambdas
# =============================================================================
#
# Same as A with the one thing that reads worst in A — `lambda store:` —
# replaced by small predicate helpers, the way `condition(is_organisation,
# ...)` reads on a wizard. `until` / `unless` say which gate it is.

application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .member("project", project, title="Project", reopen="review", done=record_amount)
    .collection(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        unless=amount_at_most(10_000),
    )
    .hub(
        "supporting",
        title="Supporting information",
        members=(
            Hub()
            .member("referees", referees, title="Referees", until=finished("contact"))
            .member(
                "documents",
                documents,
                title="Governing document",
                unless=answered("applying_as", "organisation"),
            )
        ),
    )
)


# =============================================================================
# D. Wizards carry their own identity; the hub is positional
# =============================================================================
#
# The key and title move onto the thing they name. The hub is then just an
# ordered list — the shortest declaration of all, and a wizard can be
# reused under its own name anywhere. Costs: Wizard() grows `name`/`title`
# it does not need on its own; a wizard listed twice needs renaming.

contact = (
    Wizard(name="contact", title="Contact details", reopen="review", done=record_email)
    .step(ApplicantForm, name="name", label="Your name")
    .step(EmailForm, name="email", label="Email")
    .step(ReviewStepView, name="review")
)

supporting = Hub(
    name="supporting",
    title="Supporting information",
    members=[
        referees.until(finished("contact")),
        documents.unless(answered("applying_as", "organisation")),
    ],
)

application = Hub(
    setup,
    contact,
    project,
    Collection(budget_line, name="budget", title="Budget", min_items=1),
    match_funding.unless(amount_at_most(10_000)),
    supporting,
)


# =============================================================================
# E. Keyword rows: the key is the keyword, the row is a small value
# =============================================================================
#
# No quoted keys and no class body — Python keywords are the keys and dict
# order is row order. Reads like a form's `fields = {...}`. Costs: keys
# cannot contain hyphens; rows are constructor calls rather than methods,
# so it does not chain the way a wizard does.

application = Hub(
    setup=Member(setup, title="Applying as", done=record_applying_as),
    contact=Member(
        contact, title="Contact details", reopen="review", done=record_email
    ),
    project=Member(project, title="Project", reopen="review", done=record_amount),
    budget=Collection(
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    ),
    match_funding=Member(
        match_funding, title="Match funding", hidden=amount_at_most(10_000)
    ),
    supporting=Hub(
        referees=Member(referees, title="Referees", blocked=finished("contact")),
        documents=Member(
            documents,
            title="Governing document",
            hidden=answered("applying_as", "organisation"),
        ),
    ).configure(template_name="apply/supporting.html", title="Supporting information"),
)


# =============================================================================
# F. Builder with sections as the vocabulary the user sees
# =============================================================================
#
# A because the docs already say "the word on the page is yours — a task
# list says *sections*". If the library called them sections too, the
# declaration would read as the page reads. Same shape as A otherwise.

application = (
    TaskList()
    .section("setup", setup, title="Applying as", done=record_applying_as)
    .section(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .section("project", project, title="Project", reopen="review", done=record_amount)
    .add_another(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .section(
        "match_funding",
        match_funding,
        title="Match funding",
        unless=amount_at_most(10_000),
    )
    .group(
        "supporting",
        title="Supporting information",
        sections=(
            TaskList()
            .section("referees", referees, title="Referees", until=finished("contact"))
            .section(
                "documents",
                documents,
                title="Governing document",
                unless=answered("applying_as", "organisation"),
            )
        ),
    )
)


# =============================================================================
# G. Facts: the thing a member writes and another member reads is one object
# =============================================================================
#
# In every sketch above, a gate reads a string key that some other member's
# `done` wrote — the same "declared twice, joined by a string" smell that
# `member_key` / `hub_url_name` had. Here the fact is a value both sides
# hold: `records=` says who writes it and from which answer, and a gate is
# an expression on it. Rename the fact and every reference moves with it;
# the outline can list which facts a member records and which gates read
# them. Costs: a new concept, operator overloading on Fact, and `done=` is
# still needed for real side effects (saving the email, say).

applying_as = Fact("applying_as")
amount = Fact("amount", int)
email = Fact("email")

application = (
    Hub()
    .member(
        "setup",
        setup,
        title="Applying as",
        records=applying_as.from_answer("applying_as", "applying_as"),
    )
    .member(
        "contact",
        contact,
        title="Contact details",
        reopen="review",
        records=email.from_answer("email", "email"),
    )
    .member(
        "project",
        project,
        title="Project",
        reopen="review",
        records=amount.from_answer("project", "amount"),
    )
    .collection(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .member(
        "match_funding", match_funding, title="Match funding", unless=amount <= 10_000
    )
    .hub(
        "supporting",
        title="Supporting information",
        members=(
            Hub()
            .member("referees", referees, title="Referees", until=finished("contact"))
            .member(
                "documents",
                documents,
                title="Governing document",
                unless=applying_as != "organisation",
            )
        ),
    )
)


class GrantApplicationViewSet(HubViewSet):
    url_name = "apply"
    template_name = "apply/hub.html"
    member_template_name = "apply/step.html"
    hub = application

    def journey_done(self, hub, store):
        # Facts read back the same way they were declared.
        Application.objects.create().submit(email.read(store))


# =============================================================================
# H. The branch, written the way branch predicates are written
# =============================================================================
#
# Exactly A's API — no engine change, no vocabulary, no Fact. The only
# difference is the examples: every gate is a named function beside the
# `record_*` that feeds it, the way `condition(is_organisation, ...)` names
# its predicate. The writer and the reader are two named functions in one
# module, which is the cohesion the wizard already has for cross-step facts
# (`on_field("applying_as", "applying_as")` names an answer by string too).


def record_applying_as(store, bound_wizard):
    step = bound_wizard.path.find_step(name="applying_as")
    store.data["applying_as"] = step.form.cleaned_data["applying_as"]


def is_individual(store):
    return store.data.get("applying_as") != "organisation"


def record_amount(store, bound_wizard):
    step = bound_wizard.path.find_step(name="project")
    store.data["amount"] = int(step.form.cleaned_data["amount"])


def below_match_funding_threshold(store):
    return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


def contact_not_finished(store):
    return not store.has_stash("contact")


supporting = (
    Hub()
    .member("referees", referees, title="Referees", blocked=contact_not_finished)
    .member("documents", documents, title="Governing document", hidden=is_individual)
    .configure(template_name="apply/supporting.html")
)

application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .member("project", project, title="Project", reopen="review", done=record_amount)
    .collection(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        hidden=below_match_funding_threshold,
    )
    .hub("supporting", supporting, title="Supporting information")
)


# =============================================================================
# I. H, with the gates named for the rule rather than the state
# =============================================================================
#
# `blocked=` / `hidden=` describe what the row *is*; `until=` / `unless=`
# describe the *rule*, the way `condition(...)` does. Same predicates as H,
# and the predicates read better when the keyword carries the negation:
# `until=contact_finished` rather than `blocked=contact_not_finished`.


def is_organisation(store):
    return store.data.get("applying_as") == "organisation"


def above_match_funding_threshold(store):
    return store.data.get("amount", 0) > MATCH_FUNDING_THRESHOLD


def contact_finished(store):
    return store.has_stash("contact")


supporting = (
    Hub()
    .member("referees", referees, title="Referees", until=contact_finished)
    .member("documents", documents, title="Governing document", only_if=is_organisation)
    .configure(template_name="apply/supporting.html")
)

application = (
    Hub()
    .member("setup", setup, title="Applying as", done=record_applying_as)
    .member(
        "contact", contact, title="Contact details", reopen="review", done=record_email
    )
    .member("project", project, title="Project", reopen="review", done=record_amount)
    .collection(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .member(
        "match_funding",
        match_funding,
        title="Match funding",
        only_if=above_match_funding_threshold,
    )
    .hub("supporting", supporting, title="Supporting information")
)


# =============================================================================
# J. The wizard's ladder, applied without exception
# =============================================================================
#
# The wizard has one rule: the builder carries facts (`name`, `label`), and
# behaviour lives on the thing in the slot — a Form the library wraps in a
# FormView, or your own FormView subclass when a step needs a hook. Nothing
# about the wizard changes between the two. Applied to hubs: a row carries
# `title` / `reopen` / `label`; behaviour lives on the member's viewset —
# a Wizard the library wraps in a MemberViewSet, or your own MemberViewSet
# subclass when the member needs `run_done` / `blocked` / `hidden`. No
# `done=` / `blocked=` / `hidden=` callables on the row, so there is nothing
# to name or invert (H, I, G become moot). The hub still supplies the key,
# the return URL and the mount.


class SetupMember(MemberViewSet):
    wizard = setup

    def run_done(self, bound_wizard):
        record_applying_as(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class ContactMember(MemberViewSet):
    wizard = contact

    def run_done(self, bound_wizard):
        record_email(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class ProjectMember(MemberViewSet):
    wizard = project

    def run_done(self, bound_wizard):
        record_amount(self.get_journey_store(), bound_wizard)
        return super().run_done(bound_wizard)


class MatchFundingMember(MemberViewSet):
    wizard = match_funding

    @classmethod
    def hidden(cls, store):
        return store.data.get("amount", 0) <= MATCH_FUNDING_THRESHOLD


class RefereesMember(MemberViewSet):
    wizard = referees

    @classmethod
    def blocked(cls, store):
        return not store.has_stash("contact")


class DocumentsMember(MemberViewSet):
    wizard = documents

    @classmethod
    def hidden(cls, store):
        return store.data.get("applying_as") != "organisation"


supporting = (
    Hub()
    .member("referees", RefereesMember, title="Referees")
    .member("documents", DocumentsMember, title="Governing document")
    .configure(template_name="apply/supporting.html")
)

application = (
    Hub()
    .member("setup", SetupMember, title="Applying as")
    .member("contact", ContactMember, title="Contact details", reopen="review")
    .member("project", ProjectMember, title="Project", reopen="review")
    # rung 1 for the collection: a wizard, wrapped
    .collection(
        "budget",
        budget_line,
        title="Budget",
        item_name="Budget line",
        item_title=("line", "item"),
        min_items=1,
        reopen="review",
    )
    .member("match_funding", MatchFundingMember, title="Match funding")
    .hub("supporting", supporting, title="Supporting information")
)


class GrantApplicationViewSet(HubViewSet):
    url_name = "apply"
    template_name = "apply/hub.html"
    member_template_name = "apply/step.html"
    hub = application

    def journey_done(self, hub, store): ...
