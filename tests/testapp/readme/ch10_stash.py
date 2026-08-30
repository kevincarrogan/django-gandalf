"""Chapter 10 — coming back later. The wizard finishes, and the answers
stay editable."""

from django.http import HttpResponse
from django.shortcuts import redirect

from gandalf.context import WizardContext
from gandalf.storage import SessionStashStore, StashNotFound
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import InvalidStash, Wizard

from .forms import ApplicantForm, EmailForm


class ContactDetailsViewSet(WizardViewSet):
    description = "Chapter 10: done() stashes the answers so they can be re-opened."
    url_name = "readme-stash"
    template_name = "testapp/linear_wizard.html"
    wizard = (
        Wizard().step(ApplicantForm, name="applicant").step(EmailForm, name="contact")
    )

    def done(self, run):
        SessionStashStore(run.context).put("contact", run.stash(label="contact"))
        return HttpResponse("Contact details saved.")


def reopen_contact_details(request):
    stashes = SessionStashStore(WizardContext.from_request(request))
    try:
        payload = stashes.get("contact")
        url = ContactDetailsViewSet.resurrect(
            request, payload, expected_label="contact"
        )
    except (StashNotFound, InvalidStash):
        return redirect("readme-stash")  # nothing stashed — start fresh
    return redirect(url)
