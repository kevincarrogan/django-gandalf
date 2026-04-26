from django import forms


class FirstStepForm(forms.Form):
    name = forms.CharField()


class SecondStepForm(forms.Form):
    email = forms.EmailField()
