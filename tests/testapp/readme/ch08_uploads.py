"""Chapter 8 — proof it exists. An organisation uploads its governing
document, and the bytes live somewhere other than the session."""

from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet

from . import ch02_branching as ch02, ch04_expand as ch04
from .ch07_step_views import with_contact_and_review
from .forms import GoverningDocumentForm


organisation_details = ch04.organisation_details.step(
    GoverningDocumentForm, name="governing-document", label="Governing document"
)


class DocumentedApplicationViewSet(WizardViewSet):
    description = "Chapter 8: a file step, replayed from storage on every request."
    url_name = "readme-upload"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def done(self, run):
        document = run.path.find_step(name="governing-document")
        if document is None:
            return HttpResponse("Application received (no document needed)")
        return HttpResponse(f"Received {document.files['document']['name']}")
