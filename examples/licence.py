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
"""

from django import forms
from django.http import HttpResponse

from examples.eventlog import log_event
from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin
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


class NameForm(forms.Form):
    first_name = forms.CharField(label="First name", max_length=60)
    surname = forms.CharField(label="Last name", max_length=60)


class DateOfBirthForm(forms.Form):
    date_of_birth = forms.DateField(
        label="What is your date of birth?", help_text="YYYY-MM-DD."
    )


class LicenceNumberForm(forms.Form):
    licence_number = forms.CharField(
        label="What is your driving licence number?",
        max_length=20,
        help_text="It is printed at 5 on the front of the card.",
    )


class AddressForm(forms.Form):
    address_line_1 = forms.CharField(label="Address line 1", max_length=120)
    address_line_2 = forms.CharField(
        label="Address line 2 (optional)", max_length=120, required=False
    )
    town = forms.CharField(label="Town or city", max_length=60)
    postcode = forms.CharField(label="Postcode", max_length=10)


class IdentityConfirmForm(forms.Form):
    confirmed = forms.BooleanField(label="These details are correct")


class IdentityReviewStepView(SummaryMixin, StepFormView):
    """Check your answers, and the handover point.

    The mixin lists every answer with a change link, so somebody arriving
    from a chat lands on a page showing exactly what was filled in their
    name — which is the only honest way to end a journey where a machine
    read the answers off a photograph.
    """

    form_class = IdentityConfirmForm
    template_name = "hybrid/summary.html"


class IdentityCheckViewSet(WizardViewSet):
    """One question per page, and nowhere to put a document.

    The case that has nothing to do with file uploads. No `FileField`
    anywhere, no step a document could be stored at, and no
    `agent_accepts_documents` — so the agent is offered no way to attach
    anything, and needs none. A photograph shared in the chat reaches the
    model as an image; it reads the details off the card and submits
    ordinary strings.

    Laid out one thing per page, which is the shape a real service of this
    kind takes and the reason the demo has a point. Answered by hand it is
    five pages of transcribing a card that is sitting in front of you;
    answered from a photograph of that card it is one message and a check.
    The tedium is the product being demonstrated.

    Nothing about these fields says a driving licence carries all of them.
    The wizard's author knows it, and `agent_notes` is where they say so —
    no library feature is involved, and none is needed.
    """

    description = "A five-page identity check, asked one question at a time."
    agent_purpose = "confirming somebody's identity"
    agent_notes = (
        "Ask for a photo of the front of their driving licence up front. It "
        "shows their name, their date of birth, the licence number and the "
        "address it is registered to — everything this asks for — so one "
        "photograph saves five pages of typing. Read the details off it "
        "rather than asking for them one at a time. If they would rather not "
        "send a photo, just ask for the details instead; it is a shortcut and "
        "not a requirement."
    )
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard()
        .step(NameForm, name="name")
        .step(DateOfBirthForm, name="date-of-birth")
        .step(LicenceNumberForm, name="licence-number")
        .step(AddressForm, name="address")
        .step(IdentityReviewStepView, name="confirm")
    )

    def done(self, bound_wizard):
        name = bound_wizard.path.find_step(name="name").form.cleaned_data
        log_event("identity", run=bound_wizard.run_id, surname=name["surname"])
        return HttpResponse(f"Confirmed {name['first_name']} {name['surname']}")
