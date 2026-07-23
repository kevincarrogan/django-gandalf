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

from django import forms
from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard, condition

from .forms import (
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
    wizard = (
        Wizard()
        .step(NameForm, name="name")
        .step(EmailForm, name="email")
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        # A real app would call create_account(**payload); the demo echoes it.
        return HttpResponse(f"Signed up {payload['name']} <{payload['email']}>")


# --- Branching --------------------------------------------------------------


def is_business_account(request):
    account_step = request.wizard.path.find_step(name="account_type")
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


def build_item_steps(request):
    count = int(request.wizard.path.find_step(name="count").form.cleaned_data["count"])
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
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, name="photo")
        .step(NameForm, name="name")
    )

    def done(self, bound_wizard):
        photo_step = bound_wizard.path.find_step(name="photo")
        filename = photo_step.files["photo"]["name"]
        return HttpResponse(f"Uploaded {filename}")


# --- Escaping the wizard ----------------------------------------------------


class EscapeWizardViewSet(WizardViewSet):
    description = "Escape: a known email parks the run and redirects to login."
    url_name = "readme-escape"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(EmailLookupForm, name="email")
        .step(NameForm, name="name")
    )

    def done(self, bound_wizard):
        return HttpResponse(f"Signed up {bound_wizard.run_id}")


# --- Back-navigation / editing ---------------------------------------------


class EditingWizardViewSet(WizardViewSet):
    description = "Editing: a review template links back to each prior step."
    url_name = "readme-editing"
    template_name = "testapp/editing_wizard.html"
    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"name": "account_type"})
        .branch(
            condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"name": "business_name"}
                ),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"name": "preferred_name"}
            ),
        )
        .step(ReviewForm, context={"name": "review"})
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
        .step(AccountTypeForm, context={"name": "account_type"})
        .branch(
            condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"name": "business_name"}
                ),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"name": "preferred_name"}
            ),
        )
        .step(ReviewForm, context={"name": "review"})
    )

    def done(self, bound_wizard):
        payload = MergeCleanedData().reduce(bound_wizard.path)
        detail = payload.get("business_name") or payload.get("preferred_name")
        return HttpResponse(f"Onboarded {detail}")
