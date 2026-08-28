"""Runnable, tested counterparts to every worked example in ``README.md``.

Each ``WizardViewSet`` here is the exact code the README shows, mounted under a
``readme/`` URL prefix so that:

* ``just serve`` exposes it at ``http://127.0.0.1:8000/readme/...`` (the
  README's "Try it live" links), and
* ``tests/functional/test_readme_examples.py`` drives it through the Django
  test client, so a broken example fails CI rather than rotting in the docs.

The forms are ordinary ``django.forms.Form`` classes; the templates are the
plain form templates already bundled with the test app.
"""

import uuid

from django import forms
from django.http import HttpResponse
from django.shortcuts import redirect, render
from gandalf.collections import CollectionView, ItemSectionMixin
from gandalf.context import WizardContext
from gandalf.form_views import StepFormView
from gandalf.sections import HubView, Section, SectionMixin
from gandalf.storage import SessionSectionStore, SessionStashStore, StashNotFound
from gandalf.summary import Group, Hide, SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import InvalidStash, MergeCleanedData, Wizard, condition

from .forms import (
    ConfirmForm,
    AccountTypeForm,
    BusinessDetailsForm,
    EmailLookupForm,
    ItemCountForm,
    ItemForm,
    PersonalDetailsForm,
    ProfilePhotoForm,
    ReviewForm,
)


# --- Quickstart: a linear signup wizard -------------------------------------


class NameForm(forms.Form):
    name = forms.CharField()


class EmailForm(forms.Form):
    email = forms.EmailField()


class SignupWizardViewSet(WizardViewSet):
    description = "Quickstart: a two-step linear signup wizard."
    url_name = "readme-signup"
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(NameForm, name="name").step(EmailForm, name="email")

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        # A real app would call create_account(**payload); the demo echoes it.
        return HttpResponse(f"Signed up {payload['name']} <{payload['email']}>")


# --- Branching --------------------------------------------------------------


def is_business_account(context):
    account_step = context.run.path.find_step(name="account_type")
    return account_step.form.cleaned_data["account_type"] == "business"


class BranchingWizardViewSet(WizardViewSet):
    description = "Branching: business accounts take a different detail step."
    url_name = "readme-branching"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .step(ReviewForm, name="review")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        name = payload.get("business_name") or payload.get("preferred_name")
        return HttpResponse(f"Onboarded {name}")


# --- Dynamic wizards: get_wizard() ------------------------------------------


class OnboardingWizardViewSet(WizardViewSet):
    description = "Dynamic: the flow varies by the plan captured in the URL."
    url_name = "readme-onboarding"
    template_name = "testapp/linear_wizard.html"

    def get_wizard(self, bound_wizard):
        wizard = Wizard().step(NameForm, name="name")
        if self.kwargs["plan"] == "team":
            wizard = wizard.step(BusinessDetailsForm, name="company")
        return wizard.step(EmailForm, name="email")

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(
            f"Onboarded {payload['name']} on the {self.kwargs['plan']} plan"
        )


# --- .expand(): grow the tree from a prior answer ---------------------------


def build_item_steps(context):
    count = int(context.run.path.find_step(name="count").form.cleaned_data["count"])
    steps = Wizard()
    for index in range(count):
        steps = steps.step(ItemForm, name=f"item-{index}")
    return steps


class ExpandWizardViewSet(WizardViewSet):
    description = "Expand: grow N item steps mid-walk from the count answered."
    url_name = "readme-expand"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(build_item_steps)
        .step(ReviewForm, name="review")
    )

    def done(self, bound_wizard):
        names = [
            step.data["name"]
            for step in bound_wizard.path
            if step.data and "name" in step.data
        ]
        return HttpResponse(f"Collected {', '.join(names)}")


# --- File uploads -----------------------------------------------------------


class FileUploadWizardViewSet(WizardViewSet):
    description = "File upload: the first step accepts a photo."
    url_name = "readme-file-upload"
    template_name = "testapp/file_upload_wizard.html"
    wizard = Wizard().step(ProfilePhotoForm, name="photo").step(NameForm, name="name")

    def done(self, bound_wizard):
        photo_step = bound_wizard.path.find_step(name="photo")
        filename = photo_step.files["photo"]["name"]
        return HttpResponse(f"Uploaded {filename}")


# --- Step views: bringing your own FormView ---------------------------------


class BillingForm(forms.Form):
    company = forms.CharField()
    country = forms.CharField()


class BillingStepView(StepFormView):
    """A step that brings its own view instead of a plain `Form`.

    Carries the one thing Gandalf does not supply for a user-supplied step
    view — its own `template_name` — plus the view-level behavior that is
    the reason to bring a `FormView` at all. The no-op success URL comes
    from `StepFormView`.
    """

    form_class = BillingForm
    template_name = "testapp/other_linear_wizard.html"

    def get_initial(self):
        initial = super().get_initial()
        account = self.request.wizard.path.find_step(name="account")
        initial["company"] = account.form.cleaned_data["email"].partition("@")[2]
        return initial


class FormViewStepWizardViewSet(WizardViewSet):
    description = "A step that brings its own FormView, mixed with plain Form steps."
    url_name = "readme-form-view"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(EmailForm, name="account")
        .step(BillingStepView, name="billing")
        .step(ReviewForm, name="confirm")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        return HttpResponse(f"Billing {payload['company']} ({payload['country']})")


# --- Escaping the wizard ----------------------------------------------------


class EscapeWizardViewSet(WizardViewSet):
    description = "Escape: a known email parks the run and redirects to login."
    url_name = "readme-escape"
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(EmailLookupForm, name="email").step(NameForm, name="name")

    def done(self, bound_wizard):
        return HttpResponse(f"Signed up {bound_wizard.run_id}")


# --- Back-navigation / editing ---------------------------------------------


class EditingWizardViewSet(WizardViewSet):
    description = "Editing: a review template links back to each prior step."
    url_name = "readme-editing"
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    def done(self, bound_wizard):
        return HttpResponse(f"Onboarded {bound_wizard.run_id}")


# --- Dormant memory: flipping a branch arm and back -------------------------


class FlipFlopWizardViewSet(WizardViewSet):
    description = "Dormant memory: a de-selected arm's answers survive a flip."
    url_name = "readme-flip-flop"
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .step(ReviewForm, name="review")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        detail = payload.get("business_name") or payload.get("preferred_name")
        return HttpResponse(f"Onboarded {detail}")


# --- Stashing and resurrecting runs -----------------------------------------


class ContactSectionWizardViewSet(WizardViewSet):
    description = (
        "Stashing: done() keeps the finished answers so the section can be "
        "re-opened and edited later."
    )
    url_name = "readme-stash"
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(NameForm, name="name").step(EmailForm, name="email")

    def done(self, bound_wizard):
        # Keep the finished answers so this section can be re-opened later.
        SessionStashStore(bound_wizard.context).put(
            "contact", bound_wizard.stash(label="contact")
        )
        return HttpResponse("Contact details saved.")


def reopen_contact(request):
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.get("contact")
        url = ContactSectionWizardViewSet.resurrect(
            request, payload, expected_label="contact"
        )
    except (StashNotFound, InvalidStash):
        return redirect("readme-stash")  # nothing stashed — start fresh
    return redirect(url)


# --- Summary: a check-your-answers step -------------------------------------


class DeliveryForm(forms.Form):
    method = forms.ChoiceField(
        label="Delivery method",
        choices=[("standard", "Standard"), ("express", "Express")],
    )
    leave_with_neighbour = forms.BooleanField(
        label="Leave with a neighbour", required=False
    )


class DeliveryAddressForm(forms.Form):
    line_1 = forms.CharField(label="Address line 1")
    line_2 = forms.CharField(label="Address line 2", required=False)
    town = forms.CharField(label="Town or city")
    postcode = forms.CharField(label="Postcode")
    # What the address lookup returned, not what the person typed.
    uprn = forms.CharField(widget=forms.HiddenInput, required=False)


class ReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"
    summary_fields = {
        "address": [
            Group("line_1", "line_2", "town", "postcode"),
            Hide("uprn"),
        ],
    }


class SummaryWizardViewSet(WizardViewSet):
    description = (
        "Summary: a check-your-answers step with a change link per answer, "
        "and an address read back as one line."
    )
    url_name = "readme-summary"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(NameForm, name="name", label="Your name")
        .step(DeliveryForm, name="delivery", label="Delivery")
        .step(DeliveryAddressForm, name="address", label="Address")
        .step(ReviewStepView, name="review")
    )

    def done(self, bound_wizard):
        return HttpResponse("Order placed")


# --- Hub and spoke: parallel sections ---------------------------------------


class AddressForm(forms.Form):
    line_one = forms.CharField(label="Address line 1")
    postcode = forms.CharField()


class SectionReviewStepView(SummaryMixin, StepFormView):
    form_class = ConfirmForm
    template_name = "testapp/summary_wizard.html"


class ContactSectionViewSet(SectionMixin, WizardViewSet):
    description = "Hub and spoke: the contact section of a profile task list."
    url_name = "readme-hub-contact"
    template_name = "testapp/linear_wizard.html"
    section_key = "contact"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(NameForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
        # A review step is what makes re-opening safe: without it, one
        # successful edit walks straight through to `done()` again.
        .step(SectionReviewStepView, name="review")
    )


class AddressSectionViewSet(SectionMixin, WizardViewSet):
    description = "Hub and spoke: the address section of a profile task list."
    url_name = "readme-hub-address"
    template_name = "testapp/linear_wizard.html"
    section_key = "address"
    hub_url_name = "readme-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="address", label="Address")
        .step(SectionReviewStepView, name="review")
    )


class ProfileHubView(HubView):
    description = "Hub and spoke: a task list over two independent sections."
    template_name = "testapp/hub.html"
    url_name = "readme-hub"
    section_url_name = "readme-hub-section"
    sections = [
        # `reopen_step` lands a finished section back on its review page, so
        # re-entering shows the answers with a change link each rather than
        # dropping the user at step one.
        Section(
            "contact",
            ContactSectionViewSet,
            title="Contact details",
            reopen_step="review",
        ),
        Section(
            "address",
            AddressSectionViewSet,
            title="Address",
            reopen_step="review",
        ),
    ]


# --- Add another: a collection of items --------------------------------------


class GuestForm(forms.Form):
    name = forms.CharField(label="Guest name")
    dietary_requirements = forms.CharField(required=False)


class GuestItemViewSet(ItemSectionMixin, WizardViewSet):
    description = "Add another: one guest of a collection the user grows."
    url_name = "readme-guest"
    template_name = "testapp/linear_wizard.html"
    collection_key = "guests"
    collection_url_name = "readme-guests"
    # The answer that names a row. Cached when the item finishes, so the
    # page reads a string and a row still costs no walk.
    item_title_step = "guest"
    item_title_field = "name"
    wizard = (
        Wizard()
        .step(GuestForm, name="guest", label="Guest")
        .step(SectionReviewStepView, name="review")
    )


class GuestCollectionView(CollectionView):
    description = "Add another: a collection of guests with full CRUD."
    template_name = "testapp/collection.html"
    remove_template_name = "testapp/collection_remove.html"
    url_name = "readme-guests"
    collection_key = "guests"
    item_viewset = GuestItemViewSet
    item_name = "Guest"
    item_reopen_step = "review"
    continue_url_name = "readme-party-hub"


class VenueSectionViewSet(SectionMixin, WizardViewSet):
    description = "Add another: a plain section beside a collection."
    url_name = "readme-party-venue"
    template_name = "testapp/linear_wizard.html"
    section_key = "venue"
    hub_url_name = "readme-party-hub"
    wizard = (
        Wizard()
        .step(AddressForm, name="venue", label="Venue")
        .step(SectionReviewStepView, name="review")
    )


class PartyHubView(HubView):
    description = "Add another: a task list whose second row is a collection."
    template_name = "testapp/hub.html"
    url_name = "readme-party-hub"
    section_url_name = "readme-party-hub-section"
    sections = [
        Section("venue", VenueSectionViewSet, title="Venue", reopen_step="review"),
        # A collection page is not a wizard, so the row links straight at it
        # and answers for its own status.
        GuestCollectionView.as_section("guests", title="Guests"),
    ]


# --- Journeys: a task list scoped to one application ------------------------


class ApplicantTypeForm(forms.Form):
    applicant_type = forms.ChoiceField(
        label="Applying as",
        choices=[("individual", "An individual"), ("business", "A business")],
    )


class EmploymentStatusForm(forms.Form):
    status = forms.ChoiceField(
        label="Employment status",
        choices=[
            ("employed", "Employed"),
            ("self_employed", "Self-employed"),
            ("unemployed", "Not working"),
        ],
    )


class EmployerForm(forms.Form):
    employer = forms.CharField(label="Employer")


class ReferenceForm(forms.Form):
    referee = forms.CharField(label="Referee")


def record_applicant_type(store, bound_wizard):
    """Read the one answer the rest of the journey turns on, once, and write
    it where every other section can read it without a walk."""
    step = bound_wizard.path.find_step(name="type")
    store.data["applicant_type"] = step.form.cleaned_data["applicant_type"]


class ApplicationStartViewSet(WizardViewSet):
    """The first wizard. There is no journey yet, so `done()` mints one,
    stashes these answers as its first section, and sends the user to the
    hub under the new id."""

    description = "Journeys: the setup wizard that mints an application."
    url_name = "readme-apply-start"
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(ApplicantTypeForm, name="type", label="Applicant")

    def done(self, bound_wizard):
        journey = uuid.uuid4().hex
        store = SessionSectionStore(self.context_for(self.request), journey)
        store.put_stash("setup", bound_wizard.stash(label="setup"))
        record_applicant_type(store, bound_wizard)
        return redirect("readme-apply-hub", journey=journey)


class SetupSectionViewSet(SectionMixin, WizardViewSet):
    """The same wizard, once a journey exists: re-openable from the hub like
    any other section, and re-recording its answer when it is re-saved."""

    description = "Journeys: the setup answers, re-openable from the hub."
    url_name = "readme-apply-setup"
    template_name = "testapp/linear_wizard.html"
    section_key = "setup"
    hub_url_name = "readme-apply-hub"
    wizard = ApplicationStartViewSet.wizard

    def section_done(self, bound_wizard):
        record_applicant_type(self.get_section_store(), bound_wizard)
        return super().section_done(bound_wizard)


class ApplyContactSectionViewSet(SectionMixin, WizardViewSet):
    description = "Journeys: a plain section of the application."
    url_name = "readme-apply-contact"
    template_name = "testapp/linear_wizard.html"
    section_key = "contact"
    hub_url_name = "readme-apply-hub"
    wizard = (
        Wizard()
        .step(NameForm, name="name", label="Your name")
        .step(EmailForm, name="email", label="Email")
    )


class EmploymentSectionViewSet(SectionMixin, WizardViewSet):
    """Decides whether the Employer section exists. The answer is read off
    the path here — the one moment the run is readable and a walk has
    already been paid — and written to the journey's data."""

    description = "Journeys: the section whose answer reveals another."
    url_name = "readme-apply-employment"
    template_name = "testapp/linear_wizard.html"
    section_key = "employment"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(EmploymentStatusForm, name="status", label="Employment")

    def section_done(self, bound_wizard):
        step = bound_wizard.path.find_step(name="status")
        self.get_section_store().data["employment_status"] = step.form.cleaned_data[
            "status"
        ]
        return super().section_done(bound_wizard)


class EmployerSectionViewSet(SectionMixin, WizardViewSet):
    """Hidden until the applicant says they are employed: not listed, not
    counted, and its door refuses a stale link."""

    description = "Journeys: a section that only exists for the employed."
    url_name = "readme-apply-employer"
    template_name = "testapp/linear_wizard.html"
    section_key = "employer"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(EmployerForm, name="employer", label="Employer")

    @classmethod
    def hidden(cls, request, section, store):
        return store.data.get("employment_status") != "employed"


class ReferencesSectionViewSet(SectionMixin, WizardViewSet):
    """Listed from the start but locked until Contact details are finished:
    the row reads *Cannot start yet* and the door refuses it."""

    description = "Journeys: a section that unlocks when another is finished."
    url_name = "readme-apply-references"
    template_name = "testapp/linear_wizard.html"
    section_key = "references"
    hub_url_name = "readme-apply-hub"
    wizard = Wizard().step(ReferenceForm, name="referee", label="Referee")

    @classmethod
    def blocked(cls, request, section, store):
        return not store.has_stash("contact")


class ApplicationHubView(HubView):
    """Mounted under `apply/<journey>/`, so every request — the page, the
    doors, and each section's own wizard under the same segment — reads the
    same journey, and two applications are two URLs."""

    description = "Journeys: the application's task list, with a submit."
    template_name = "testapp/journey_hub.html"
    url_name = "readme-apply-hub"
    section_url_name = "readme-apply-hub-section"
    sections = [
        Section("setup", SetupSectionViewSet, title="Applicant"),
        Section("contact", ApplyContactSectionViewSet, title="Contact details"),
        Section("employment", EmploymentSectionViewSet, title="Employment"),
        Section("employer", EmployerSectionViewSet, title="Employer"),
        Section("references", ReferencesSectionViewSet, title="References"),
    ]

    def journey_done(self, hub, store):
        # The stashes are still readable here; the tombstone keeps only
        # `store.data`, so whatever the done page needs goes there.
        reference = f"APP-{self.get_journey()[:8].upper()}"
        store.data["reference"] = reference
        return redirect(self.get_hub_url())

    def journey_completed(self, store):
        return render(
            self.request,
            "testapp/journey_done.html",
            {"reference": store.data["reference"]},
        )
