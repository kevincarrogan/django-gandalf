"""Chapter 9 — finishing, and what it leaves behind. done() runs once; a
record opened at the start is remembered for the rest of the run."""

from django.http import Http404
from django.shortcuts import redirect, render

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData

from ..models import Application
from . import ch02_branching as ch02
from .ch07_step_views import with_contact_and_review
from .ch08_uploads import organisation_details


class RecordedApplicationViewSet(WizardViewSet):
    description = (
        "Chapter 9: a draft record opened at run_started(), submitted at done()."
    )
    url_name = "readme-record"
    template_name = "testapp/file_upload_wizard.html"
    wizard = with_contact_and_review(ch02.applicant(organisation=organisation_details))

    def run_started(self, run):
        application = Application.objects.create()
        run.metadata["application_id"] = application.pk

    def done(self, run):
        application = Application.objects.get(pk=run.metadata["application_id"])
        answers = MergeCleanedData().reduce(run.path)
        application.submit(answers["email"])
        return redirect("readme-received", pk=application.pk)

    def run_unavailable(self, run, reason):
        if reason == "completed":
            # The metadata bag survives the tombstone, so a revisit can still
            # say which application this run submitted.
            return redirect("readme-received", pk=run.metadata["application_id"])
        raise Http404("That application has expired.")


def application_received(request, pk):
    application = Application.objects.get(pk=pk)
    return render(
        request, "testapp/application_received.html", {"application": application}
    )
