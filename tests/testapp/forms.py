from django import forms


class FirstStepForm(forms.Form):
    name = forms.CharField()
