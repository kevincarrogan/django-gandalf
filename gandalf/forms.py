from django import forms


class ManagementForm(forms.Form):
    run_id = forms.CharField(widget=forms.HiddenInput)
