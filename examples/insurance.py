"""A deliberately long wizard: a business insurance quote.

This is the tedium the agent work exists to kill. Driven by hand it is up
to fourteen steps: company details, a three-way branch on company type
(the partnership arm grows one step per partner), cover selection, a
fleet section that appears only when vehicles are covered and grows one
step per vehicle, a claims-history branch, contact details, and a final
confirmation. Driven by an agent holding a business profile, almost all
of it prefills in one call.

Used by the agent demos (`examples/agents`, `examples/copilotkit`) and
exercised end-to-end by the functional suite.
"""

from django import forms
from django.http import HttpResponse

from examples.eventlog import log_event
from gandalf.collections import CollectionView, ItemSectionMixin
from gandalf.contrib.agent import AgentProfile
from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard, condition, on_field


class CompanyForm(forms.Form):
    name = forms.CharField(label="Company name")
    company_type = forms.ChoiceField(
        label="Company type",
        choices=[
            ("limited", "Limited company"),
            ("partnership", "Partnership"),
            ("sole_trader", "Sole trader"),
        ],
    )
    founded = forms.DateField(label="Founded on", help_text="YYYY-MM-DD.")
    employees = forms.IntegerField(
        label="Number of employees", min_value=1, max_value=500
    )


class RegistrationForm(forms.Form):
    companies_house_number = forms.CharField(
        label="Companies House number", max_length=8
    )
    vat_registered = forms.BooleanField(label="VAT registered", required=False)


class PartnershipForm(forms.Form):
    partner_count = forms.IntegerField(
        label="Number of partners", min_value=2, max_value=6
    )


class PartnerForm(forms.Form):
    full_name = forms.CharField(label="Partner's full name")


class OwnerForm(forms.Form):
    full_name = forms.CharField(label="Owner's full name")
    date_of_birth = forms.DateField(
        label="Owner's date of birth", help_text="YYYY-MM-DD."
    )


class CoverageForm(forms.Form):
    cover_types = forms.MultipleChoiceField(
        label="Cover needed",
        choices=[
            ("property", "Property"),
            ("liability", "Public liability"),
            ("vehicles", "Vehicles"),
            ("cyber", "Cyber"),
        ],
    )
    excess = forms.ChoiceField(
        label="Excess",
        choices=[("250", "£250"), ("500", "£500"), ("1000", "£1,000")],
    )
    start_date = forms.DateField(
        label="Cover start date", help_text="When cover should begin, YYYY-MM-DD."
    )


class VehicleForm(forms.Form):
    registration = forms.CharField(label="Vehicle registration")
    value = forms.IntegerField(label="Vehicle value (£)", min_value=1)


class ClaimsForm(forms.Form):
    had_claims = forms.ChoiceField(
        label="Any claims in the last five years?",
        choices=[("no", "No"), ("yes", "Yes")],
    )


class ClaimsDetailForm(forms.Form):
    description = forms.CharField(label="What happened")
    total_value = forms.IntegerField(label="Total claimed (£)", min_value=0)


class ContactForm(forms.Form):
    email = forms.EmailField(label="Contact email")
    phone = forms.CharField(label="Phone", required=False)


class ConfirmForm(forms.Form):
    confirmed = forms.BooleanField(label="Everything above is correct")


class ReviewStepView(SummaryMixin, StepFormView):
    """Check your answers — and the handover point.

    An agent can fill everything ahead of this step, but confirming is the
    one thing it should not do on someone's behalf. Rendered over HTTP the
    mixin lists every answer with a change link, so a person arriving from
    a chat lands on a page that shows them exactly what was filled in
    their name.
    """

    form_class = ConfirmForm
    template_name = "hybrid/summary.html"


# Two kinds of fork, chosen to fit what actually decides them. The company
# route is one answer picking one path, so it is a `.switch()` on that
# field — the dependency is data, and an agent reading the outline can see
# that "limited" leads to the registration step. The two below are
# genuine predicates: one reads a multi-valued field, the other a value
# that has to be compared, and neither is "what did they say".


def vehicle_cover_was_chosen(context):
    """The cover step includes "vehicles", so the fleet has to be listed."""
    step = context.run.path.find_step(name="coverage")
    return "vehicles" in step.form.cleaned_data["cover_types"]


def claims_were_declared(context):
    """The claims step answered "yes", so the claim needs describing."""
    step = context.run.path.find_step(name="claims")
    return step.form.cleaned_data["had_claims"] == "yes"


def build_partner_steps(context):
    count_step = context.run.path.find_step(name="partners")
    steps = Wizard()
    for index in range(int(count_step.form.cleaned_data["partner_count"])):
        steps = steps.step(
            PartnerForm,
            name=f"partner-{index}",
            label=f"Partner {index + 1}",
        )
    return steps


class InsuranceQuoteViewSet(WizardViewSet):
    description = "A long branching quote wizard, built to be driven by an agent."
    # What an agent is told about this wizard. `description` above is for
    # whoever reads the code; this is for whoever is being talked to.
    #
    # The note is the part no wizard can supply: the fleet is not part of
    # this quote — each vehicle is its own run behind a page of its own —
    # and a wizard's steps are the only thing it knows about itself.
    agent = AgentProfile(
        purpose="a business insurance quote",
        notes=(
            "Vehicles are not part of the quote and you cannot add one. Each "
            "vehicle is added by the customer on their own fleet page. If they "
            "want vehicle cover, put that on the quote and tell them to add "
            "their vehicles there — never try to add one yourself."
        ),
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(CompanyForm, name="company", label="Your company")
        .switch(
            on_field("company", "company_type"),
            {
                "limited": Wizard().step(
                    RegistrationForm,
                    name="registration",
                    label="Registration",
                ),
                "partnership": (
                    Wizard()
                    .step(
                        PartnershipForm,
                        name="partners",
                        label="Partnership",
                    )
                    .expand(build_partner_steps)
                ),
            },
            default=Wizard().step(OwnerForm, name="owner", label="Owner"),
        )
        .step(CoverageForm, name="coverage", label="Cover")
        .step(ClaimsForm, name="claims", label="Claims history")
        .branch(
            condition(
                claims_were_declared,
                Wizard().step(
                    ClaimsDetailForm,
                    name="claims-detail",
                    label="Claim details",
                ),
            ),
        )
        .step(ContactForm, name="contact", label="Contact")
        .step(ReviewStepView, name="confirm")
    )

    def done(self, bound_wizard):
        quote = quote_for(bound_wizard)
        log_event("quote", **quote)
        return HttpResponse(
            f"Quote for {quote['name']}: £{quote['premium']}/year "
            f"covering {quote['covers']}."
        )


def quote_for(bound_wizard, *, vehicle_values=None):
    """Price the run: a base rate, a bit per employee, a bit per cover, a
    percentage of the fleet, and a loading for prior claims.

    The fleet is not in this run. Vehicles are a collection the person grows
    at their own page, so the values come from where that collection saved
    them — the same place any application would read its own records.
    """
    answers = MergeCleanedData().reduce(bound_wizard.path)
    premium = 250
    premium += answers["employees"] * 10
    premium += 150 * len(answers["cover_types"])
    read_values = saved_vehicle_values if vehicle_values is None else vehicle_values
    premium += sum(read_values(bound_wizard.context)) // 100
    if answers["had_claims"] == "yes":
        premium += answers["total_value"] // 10
    return {
        "name": answers["name"],
        "premium": premium,
        "covers": ", ".join(sorted(answers["cover_types"])),
    }


# --- The fleet: a list the person grows -------------------------------------
#
# Vehicles used to be a count step and one step per vehicle, which suited an
# agent filling a form and nobody else: a person who bought a third van had to
# go back and change the count. `gandalf.collections` is the shape that fits
# what this actually is — a list with Change and Remove on every row and an
# "add another" question at the end.
#
# The trade is worth naming, because it is the whole point of this example.
# Each item is its own wizard run, so a collection is many runs behind one
# page. `gandalf.driver` drives one run: an agent holding only that can fill
# the quote and has no vocabulary for adding an item, which is why this
# wizard's `AgentProfile` tells it so rather than letting it discover the
# silence.
#
# It is a limit of the toolset rather than of the library, and
# `examples/copilotkit/fleet.py` lifts it without new library API: a
# collection page is an ordinary view whose verbs are ordinary methods, and
# an item id is a URL kwarg, which `RunDriver` already takes. The demo's
# adaptive agent has those verbs and a profile that says so.


VEHICLES_SESSION_KEY = "insurance_vehicles"


def save_vehicle(request, item_id, bound_wizard):
    """What an application does when an item finishes: keep the answers
    somewhere of its own. A demo has no database, so the session stands in
    for one."""
    answers = MergeCleanedData().reduce(bound_wizard.path)
    saved = request.session.setdefault(VEHICLES_SESSION_KEY, {})
    saved[str(item_id)] = {
        "registration": answers["registration"],
        "value": answers["value"],
    }
    request.session.modified = True
    # The person's side of the story, which no agent transcript can see.
    log_event(
        "vehicle_saved",
        item=str(item_id),
        registration=answers["registration"],
        value=answers["value"],
        by="person",
    )


def forget_vehicle(request, item_id):
    """The counterpart, for a row the person removes."""
    saved = request.session.get(VEHICLES_SESSION_KEY, {})
    if str(item_id) in saved:
        del saved[str(item_id)]
        request.session.modified = True
        log_event("vehicle_removed", item=str(item_id), by="person")


def saved_vehicle_values(context):
    """Every saved vehicle value, for pricing."""
    return [
        vehicle["value"]
        for vehicle in context.session.get(VEHICLES_SESSION_KEY, {}).values()
    ]


class VehicleReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "hybrid/summary.html"


class VehicleItemViewSet(ItemSectionMixin, WizardViewSet):
    """One vehicle. Mounted under an item id, so the same wizard serves every
    row of the collection."""

    url_name = "vehicle"
    template_name = "hybrid/step.html"
    collection_key = "vehicles"
    collection_url_name = "vehicles"
    item_title_step = "vehicle"
    item_title_field = "registration"
    wizard = (
        Wizard()
        .step(VehicleForm, name="vehicle", label="Vehicle")
        .step(VehicleReviewStepView, name="review")
    )

    def section_done(self, bound_wizard):
        save_vehicle(self.request, self.get_item_id(), bound_wizard)
        return super().section_done(bound_wizard)


class VehicleCollectionView(CollectionView):
    """The fleet page: what has been added, and whether there is more."""

    template_name = "hybrid/collection.html"
    remove_template_name = "hybrid/remove_item.html"
    url_name = "vehicles"
    collection_key = "vehicles"
    item_viewset = VehicleItemViewSet
    item_name = "Vehicle"
    item_reopen_step = "review"
    continue_url_name = "quote"

    def item_removed(self, item_id):
        forget_vehicle(self.request, item_id)
        return super().item_removed(item_id)
