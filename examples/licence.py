"""A short wizard whose first answer is a photograph.

The insurance wizard asks what an agent can fill from a profile it was
handed. This one asks for something no profile holds: a picture of a
driving licence, and then the four fields printed on it.

That inverts the demo. There, the person supplies context up front and
the agent does the typing; here the person supplies a *document* and the
agent does the reading — a step that neither a form's `clean()` nor the
person's patience handles well, and the first thing in these demos that
the agent can do and the browser cannot.

It is deliberately not part of `examples.insurance`. The evaluation's
eight scenarios are measured against that wizard's shape and
`just agent-cost` against its outline, so growing it mid-flight would
invalidate the baseline the sweep exists to compare against.

This is the half that *keeps* the photograph: there is a file step, and
the agent attaches the picture to the run as an answer in its own right.
`examples.identity` is the same idea with nothing stored, and is much the
more common case.
"""

from django import forms
from django.http import HttpResponse

from examples.eventlog import log_event
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


class LicenceScanForm(forms.Form):
    scan = forms.FileField(
        label="Photo of your driving licence",
        help_text="The front of the card, with the details readable.",
    )


class LicenceDetailsForm(forms.Form):
    """What is printed on the card.

    Every field here is readable from the photograph, which is the point:
    an agent that has been shown the scan should be able to fill all four
    without asking a single question, and a person should still be able to
    correct any of them afterwards.
    """

    licence_number = forms.CharField(label="Licence number", max_length=20)
    surname = forms.CharField(label="Surname", max_length=60)
    date_of_birth = forms.DateField(label="Date of birth", help_text="YYYY-MM-DD.")
    expires_on = forms.DateField(label="Valid until", help_text="YYYY-MM-DD.")


class ConfirmLicenceForm(forms.Form):
    confirmed = forms.BooleanField(
        label="I have checked these details against my licence",
    )


class LicenceCheckViewSet(WizardViewSet):
    description = "A three-step check whose first answer is an uploaded photograph."
    agent_purpose = "checking a driving licence"
    # An agent driving this one may be handed a file. Declared rather than
    # detected, and off by default, because a tool an agent cannot use is
    # one it can only misuse — the quote wizard has no file step, and
    # offering it a way to attach documents would invite it to invent one.
    agent_accepts_documents = True
    # The one thing the wizard cannot say about itself. Reading a document
    # is not the same kind of act as filling a form from something you were
    # told, and the difference matters to whoever is being helped: a
    # misread digit looks exactly like a confident one.
    agent_notes = (
        "If you are given a photograph of the licence, read the details off "
        "it and fill them in yourself rather than asking for them one at a "
        "time. Say that you have read them from the photo and that they "
        "should be checked, because you can misread a character and it will "
        "not look like a mistake. Never confirm the details yourself — hand "
        "the run back so they can check the card against what you typed."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(LicenceScanForm, name="scan")
        .step(LicenceDetailsForm, name="details")
        .step(ConfirmLicenceForm, name="confirm")
    )

    def done(self, bound_wizard):
        details = bound_wizard.path.find_step(name="details").form.cleaned_data
        log_event(
            "licence",
            run=bound_wizard.run_id,
            licence_number=details["licence_number"],
        )
        return HttpResponse(f"Checked licence {details['licence_number']}")
