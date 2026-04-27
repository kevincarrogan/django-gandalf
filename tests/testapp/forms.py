from django import forms


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
