"""An identity check that never wants the document it is filled from.

Five pages, one question each — name, date of birth, driving licence
number, address, then check your answers. The shape a real service of
this kind takes, and the reason the demo has a point: answered by hand it
is four pages of transcribing a card that is sitting in front of you.

Nothing here knows about documents. There is no `FileField`, no step a
file could be stored at, and no `agent_accepts_documents` — so the agent
is offered no way to attach anything and needs none. A photograph shared
in the chat reaches the model as an image; it reads the details off the
card and submits ordinary strings.

Which makes this the more useful half of the pair. Reading a document
takes no support from the form at all, and the one thing that makes it
happen is a sentence in `agent_notes` saying which document holds what.
`examples.licence` is the same journey for a wizard that does keep the
picture.
"""

from django import forms
from django.http import HttpResponse

from examples.eventlog import log_event
from gandalf.form_views import StepFormView
from gandalf.summary import SummaryMixin
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard


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
