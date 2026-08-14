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


class AccountKindForm(forms.Form):
    """Three kinds, so a switch can name two cases and let the third fall
    through to the default arm."""

    kind = forms.ChoiceField(
        choices=[
            ("business", "Business"),
            ("personal", "Personal"),
            ("charity", "Charity"),
        ],
    )


class BusinessDetailsForm(forms.Form):
    business_name = forms.CharField()


class PersonalDetailsForm(forms.Form):
    preferred_name = forms.CharField()


class ReviewForm(forms.Form):
    confirmed = forms.BooleanField()


class ToppingsForm(forms.Form):
    """A field whose widget posts one HTML input per selected value, so the
    submission is multi-valued rather than a single string per name."""

    toppings = forms.MultipleChoiceField(
        choices=[
            ("cheese", "Cheese"),
            ("olives", "Olives"),
            ("basil", "Basil"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )


class SummaryFieldsForm(forms.Form):
    """One of each answer a summary page has to render as text rather than
    as the raw stored value."""

    contact_method = forms.ChoiceField(
        label="Contact method",
        choices=[
            ("email", "Email"),
            ("post", "Post"),
        ],
    )
    toppings = forms.MultipleChoiceField(
        label="Toppings",
        choices=[
            ("cheese", "Cheese"),
            ("olives", "Olives"),
            ("basil", "Basil"),
        ],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    marketing = forms.BooleanField(label="Marketing emails", required=False)
    starts_on = forms.DateField(label="Start date")
    note = forms.CharField(label="Note", required=False)


class SummaryDisplayForm(forms.Form):
    """Answers whose display text is nothing like the stored value: a
    grouped choice, a date and time, and an upload."""

    delivery = forms.ChoiceField(
        label="Delivery",
        choices=[
            ("Digital", [("email", "Email"), ("sms", "SMS")]),
            ("Physical", [("post", "Post")]),
        ],
    )
    collect_at = forms.DateTimeField(label="Collect at")
    opens_at = forms.TimeField(label="Opens at")
    photo = forms.FileField(label="Photo")
    note = forms.CharField(label="Note", required=False)


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
