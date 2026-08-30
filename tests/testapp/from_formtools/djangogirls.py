"""Django Girls' "organise an event" application.

Upstream: `DjangoGirls/djangogirls`, `organize/views.py` (BSD-3-Clause) — a
`NamedUrlSessionWizardView` with six forms and a three-entry
`condition_dict`.

**What upstream has to do by hand.** Two of its three conditions are the
same question asked twice, in opposite directions:

    def skip_workshop_if_remote(wizard):
        return not cleaned_data.get("remote")

    def skip_workshop_remote_if_in_person(wizard):
        return cleaned_data.get("remote", False)

`condition_dict` can only say whether a step is *in*, so a two-way fork has
to be written as two independent predicates that nobody checks are
opposites. Get one wrong and the applicant sees both workshop forms, or
neither, depending on which way you erred. Here it is one `.branch()` with
two arms: the fork is a single node, the arms are exclusive because the
structure says so, and there is no second predicate to keep in step.

The third condition is a genuine "skip this step", and stays one — a branch
with `default=None`.

The organisers step is a formset, which Gandalf takes without ceremony
because `.step()` accepts a `FormView` and `FormView` already builds a
formset the same way it builds a form. `MergeCleanedData` follows it: a
formset has no fields to spread across the merged dict, so its rows land
whole under the step's name. Upstream's `done()` has to pull the organisers
back out of its merged dict and re-shape them; here the merge does both
halves of the work, because `city` arrives from whichever workshop arm ran
and `organisers` arrives as the list it always was.
"""

from django import forms
from django.http import HttpResponse

from gandalf.form_views import FormSetStepView
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import MergeCleanedData, Wizard, condition


PREVIOUS_ORGANISER_CHOICES = (
    ("yes", "Yes, I organised Django Girls before"),
    ("no", "No, it is my first time organising"),
)

WORKSHOP_CHOICES = (("remote", "Remote"), ("in-person", "In person"))


class PreviousEventForm(forms.Form):
    has_organised_before = forms.ChoiceField(
        label="Have you organised before?",
        choices=PREVIOUS_ORGANISER_CHOICES,
        widget=forms.RadioSelect,
    )
    previous_event = forms.CharField(label="Which event?", required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("has_organised_before") == "yes" and not cleaned.get(
            "previous_event"
        ):
            self.add_error("previous_event", "Tell us which event you organised.")
        return cleaned


class ApplicationForm(forms.Form):
    """Asked only of first-time organisers — upstream's one true skip."""

    about_you = forms.CharField(label="About you", widget=forms.Textarea)
    why = forms.CharField(label="Why do you want to organise?", widget=forms.Textarea)


class OrganiserForm(forms.Form):
    email = forms.EmailField(label="Email address")
    first_name = forms.CharField(label="First name", max_length=30)


OrganisersFormSet = forms.formset_factory(
    OrganiserForm, extra=1, max_num=10, min_num=1, validate_min=True
)


class WorkshopTypeForm(forms.Form):
    remote = forms.ChoiceField(
        label="What kind of workshop?",
        choices=WORKSHOP_CHOICES,
        widget=forms.RadioSelect,
    )


class WorkshopForm(forms.Form):
    city = forms.CharField(label="City")
    venue = forms.CharField(label="Venue", widget=forms.Textarea)


class RemoteWorkshopForm(forms.Form):
    city = forms.CharField(label="City")
    tools = forms.CharField(label="Which tools will you use?", widget=forms.Textarea)


class OrganisersStepView(FormSetStepView):
    """A formset step.

    `.step()` takes a `FormView` and asks nothing else of it, and Django's
    `FormView` instantiates a formset from `data`, `files`, `initial` and
    `prefix` exactly as it does a form. The replay works for the reason the
    rest of the walk works: the stored submission is the POST the browser
    sent, management form and all.

    Serving it needs no more than that. `FormSetStepView` is what makes the
    step readable by everything that is *not* a browser — the driver, and so
    the agent — because those ask the view what the step refused rather than
    reading a `BaseForm` attribute off an object that has not got one.
    """

    form_class = OrganisersFormSet
    template_name = "testapp/formset_step.html"


def is_first_time_organiser(context):
    previous = context.run.path.find_step(name="previous-event")
    return previous.form.cleaned_data["has_organised_before"] == "no"


def is_remote(context):
    workshop_type = context.run.path.find_step(name="workshop-type")
    return workshop_type.form.cleaned_data["remote"] == "remote"


#: The two arms of the workshop question, exclusive because there is one
#: fork rather than two predicates.
in_person_workshop = Wizard().step(WorkshopForm, name="workshop")
remote_workshop = Wizard().step(RemoteWorkshopForm, name="workshop-remote")


organise_an_event = (
    Wizard()
    .step(PreviousEventForm, name="previous-event")
    .branch(
        condition(
            is_first_time_organiser,
            Wizard().step(ApplicationForm, name="application"),
        ),
        # A true skip: an organiser who has done this before is not asked.
        default=None,
    )
    .step(OrganisersStepView, name="organisers")
    .step(WorkshopTypeForm, name="workshop-type")
    .branch(condition(is_remote, remote_workshop), default=in_person_workshop)
)


class OrganiseAnEventViewSet(WizardViewSet):
    description = (
        "Django Girls' organise-an-event application, translated: a "
        "three-entry condition_dict as two branches, and a formset step."
    )
    url_name = "formtools-djangogirls"
    template_name = "testapp/linear_wizard.html"
    wizard = organise_an_event

    def done(self, run):
        """One merge over a formset and a branch.

        `city` is declared by both workshop arms and merges from whichever
        one the run took; `organisers` is a formset, so its rows fold under
        the step's name rather than spreading across the dict.
        """
        answers = MergeCleanedData().reduce(run.path)
        organisers = answers["organisers"]
        return HttpResponse(
            f"Application from {organisers[0]['email']} "
            f"for {answers['city']}, {len(organisers)} organiser(s)"
        )
