"""Every form the grant application asks, in the order the README meets
them. Plain ``django.forms.Form`` classes: Gandalf adds nothing to a form."""

from django import forms
from django.urls import reverse

from gandalf.escapes import Park


# --- Chapter 1: a first wizard ---------------------------------------------


class ApplicantForm(forms.Form):
    full_name = forms.CharField(label="Your full name")


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email address")


# --- Chapter 2: individuals and organisations -------------------------------


class ApplyingAsForm(forms.Form):
    applying_as = forms.ChoiceField(
        label="Are you applying as",
        choices=[("individual", "An individual"), ("organisation", "An organisation")],
    )


class AboutYouForm(forms.Form):
    occupation = forms.CharField(label="What do you do?")


class OrganisationForm(forms.Form):
    organisation_name = forms.CharField(label="Organisation name")


# --- Chapter 3: which kind of organisation ----------------------------------


class OrganisationTypeForm(forms.Form):
    organisation_type = forms.ChoiceField(
        label="What kind of organisation is it?",
        choices=[
            ("charity", "A registered charity"),
            ("company", "A company"),
            ("community", "An unincorporated community group"),
        ],
    )


class CharityNumberForm(forms.Form):
    charity_number = forms.CharField(label="Registered charity number")


class CompanyNumberForm(forms.Form):
    company_number = forms.CharField(label="Company number")


# --- Chapter 4: as many trustees as there are --------------------------------


class TrusteeCountForm(forms.Form):
    trustees = forms.IntegerField(
        label="How many trustees or directors does it have?",
        min_value=1,
        max_value=5,
    )


class TrusteeForm(forms.Form):
    name = forms.CharField(label="Trustee's name")


# --- Chapter 5: different funds, different questions ------------------------


class PortfolioForm(forms.Form):
    portfolio_url = forms.URLField(label="A link to your portfolio")


# --- Chapter 6: check your answers ------------------------------------------


class AddressForm(forms.Form):
    """An address: several answers that belong on one line of a summary,
    plus the lookup token that found them, which belongs on none."""

    line_1 = forms.CharField(label="Address line 1")
    line_2 = forms.CharField(label="Address line 2", required=False)
    town = forms.CharField(label="Town or city")
    postcode = forms.CharField(label="Postcode")
    lookup_token = forms.CharField(label="Lookup token", required=False)


class ConfirmForm(forms.Form):
    """A check-your-answers step's form: no fields at all. The button *is*
    the confirmation."""


# --- Chapter 7: a step with a view of its own --------------------------------


class EmailLookupForm(forms.Form):
    """An address that already has an account is sent to log in instead."""

    email = forms.EmailField(label="Email address")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("email") == "existing@example.com":
            raise Park(reverse("readme-login"))
        return cleaned_data


class WebsiteForm(forms.Form):
    website = forms.URLField(label="Website", required=False)


# --- Chapter 8: proof it exists ----------------------------------------------


class GoverningDocumentForm(forms.Form):
    document = forms.FileField(label="Your governing document")


# --- Chapters 11–14: the task list -------------------------------------------


class ProjectForm(forms.Form):
    title = forms.CharField(label="Project title")
    amount = forms.DecimalField(label="How much are you asking for?", min_value=0)


class BudgetLineForm(forms.Form):
    item = forms.CharField(label="What is it for?")
    cost = forms.DecimalField(label="Cost", min_value=0)


class RefereeForm(forms.Form):
    referee_name = forms.CharField(label="Referee's name")
    referee_email = forms.EmailField(label="Referee's email")


class MatchFundingForm(forms.Form):
    source = forms.CharField(label="Where is the rest coming from?")
