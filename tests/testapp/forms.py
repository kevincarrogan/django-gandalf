from django import forms
from django.urls import reverse

from gandalf.escapes import Advance, Escape, Park


class FirstStepForm(forms.Form):
    name = forms.CharField()


class SecondStepForm(forms.Form):
    email = forms.EmailField()


class AccountTypeForm(forms.Form):
    account_type = forms.ChoiceField(
        choices=[
            ("personal", "Personal"),
            ("business", "Business"),
        ],
    )


class BusinessDetailsForm(forms.Form):
    business_name = forms.CharField()


class PersonalDetailsForm(forms.Form):
    preferred_name = forms.CharField()


class ReviewForm(forms.Form):
    confirmed = forms.BooleanField()


class ItemCountForm(forms.Form):
    count = forms.IntegerField(min_value=1, max_value=5)


class ItemForm(forms.Form):
    name = forms.CharField()


class ProfilePhotoForm(forms.Form):
    photo = forms.FileField()


class OptionalPhotoForm(forms.Form):
    label = forms.CharField()
    photo = forms.FileField(required=False)


class EmailLookupForm(forms.Form):
    """Sends an address that already has an account off to log in, leaving
    the run parked on this step."""

    email = forms.EmailField()

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("email") == "existing@example.com":
            raise Park(reverse("escape-landing"))
        return cleaned_data


class NewsletterForm(forms.Form):
    """Keeps the answer but sends the user away to confirm it elsewhere."""

    email = forms.EmailField()
    subscribe = forms.BooleanField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("subscribe"):
            raise Advance(reverse("escape-landing"))
        return cleaned_data


class CancelSignupForm(forms.Form):
    reason = forms.CharField()
    cancel = forms.BooleanField(required=False)


class EscapingPhotoForm(forms.Form):
    """Escapes from a step that uploads, so the discarded upload has to be
    cleaned up too."""

    photo = forms.FileField()
    abandon = forms.BooleanField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("abandon"):
            raise Park(reverse("escape-landing"))
        return cleaned_data


class BareEscapeForm(forms.Form):
    """Raises the base class, which names no disposition — a misuse the
    viewset rejects."""

    name = forms.CharField()

    def clean(self):
        super().clean()
        raise Escape(reverse("escape-landing"))
