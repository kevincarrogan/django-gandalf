"""django-two-factor-auth's two-factor setup.

Upstream: `jazzband/django-two-factor-auth`, `two_factor/views/core.py`
(MIT) — `SetupView`, an `IdempotentSessionWizardView` whose `form_list` is
computed per request from a plugin registry.

**What upstream has to do by hand.** Three things, and the third is why this
wizard could not be ported at all until `run.proof()` existed.

*The shape.* `get_form_list()` recomputes the steps from the method registry
on every request. Before the method is chosen it cannot know which setup
forms will be needed, so it loads **every** registered method's forms into
the list to keep the URLs resolvable, and drops the ones it turns out not to
want. Here the methods are `.switch()` cases: each arm is a wizard, each
arm's answers are stored under its own case name, and the arms simply
coexist until the answer picks one.

*The vanishing step.* With one method registered there is nothing to ask, so
upstream deletes the step and then writes the answer it would have produced
into its own answer store:

    form_list.pop('method', None)
    self.storage.validated_step_data['method'] = {'method': method_key}

A wizard forging an answer to a question it did not ask. `get_wizard(run)`
decides the shape from the registry before the run starts, so with one
method the step is never declared and there is nothing to forge —
`SingleMethodSetupViewSet` below is that case.

*The token.* Verifying a one-time password consumes it: django-otp moves the
device's counter, and the same token never verifies twice. Gandalf re-proves
every answer on every request, so without help this wizard cannot walk at
all — the token fails on the request after the one that accepted it.
`run.proof()` holds what the check established, scoped to the answers behind
it, and the form re-checks that instead of verifying again. Change the phone
number and the proof falls away on its own, which is the property upstream
gets by bluntly discarding every later step's stored data and admits is
guesswork: *"It is assumed that earlier steps affect later steps."*
"""

from django import forms
from django.http import HttpResponse

from gandalf.form_views import StepFormView
from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard, on_field


#: Tokens each device key has already accepted. django-otp keeps this as a
#: `last_t` counter on the device row; what matters is the effect — a token
#: verifies once and never again.
SPENT: dict[str, set[str]] = {}

#: Every verification actually performed, as opposed to re-checked against a
#: proof. What a test counts to show the proof is doing its job.
VERIFICATIONS: list[str] = []


def code_for(key):
    """The code the authenticator app (or the text message) would show.

    A real one is time-based. This one is not, so the demo page can print it
    and a test can type it — the property under test here is that verifying
    consumes, not that the code rotates.
    """
    return f"{int(key, 16) % 1000000:06d}"


def verify(key, code):
    """True the first time `code` is right for `key`, false ever after."""
    if code != code_for(key):
        # A wrong guess must not burn the right code.
        return False
    spent = SPENT.setdefault(key, set())
    if code in spent:
        return False
    VERIFICATIONS.append(code)
    spent.add(code)
    return True


class WelcomeForm(forms.Form):
    """Upstream's `('welcome', Form)`: a page with something to read and
    nothing to answer."""


class MethodForm(forms.Form):
    method = forms.ChoiceField(
        label="How do you want to sign in?", widget=forms.RadioSelect
    )

    def __init__(self, methods, **kwargs):
        super().__init__(**kwargs)
        self.fields["method"].choices = [(m.code, m.label) for m in methods]


class PhoneNumberForm(forms.Form):
    number = forms.CharField(label="Mobile number")


class DeviceNameForm(forms.Form):
    """Asked after the code, which is the position that matters: a step
    after a consuming check is where a wizard without proofs cannot go."""

    name = forms.CharField(label="What should we call this device?")


class CodeForm(forms.Form):
    """The consuming check. `already_proven` is what this step established
    last time; given it, the form re-checks a fact rather than performing an
    act."""

    code = forms.CharField(label="Enter the six-digit code")

    def __init__(self, key, already_proven=None, **kwargs):
        super().__init__(**kwargs)
        self.key = key
        self.already_proven = already_proven

    def clean_code(self):
        code = self.cleaned_data["code"]
        if code == self.already_proven:
            return code
        if not verify(self.key, code):
            raise forms.ValidationError("That code is not valid.")
        return code


class MethodStepView(StepFormView):
    form_class = MethodForm
    template_name = "testapp/linear_wizard.html"

    def get_form_kwargs(self):
        # `run.urls` is the viewset serving this run, which is where the
        # registry lives — the same registry `get_wizard()` shaped the run
        # from, so the choices cannot drift from the switch's cases.
        return {**super().get_form_kwargs(), "methods": self.request.run.urls.methods}


class CodeStepView(StepFormView):
    """Mints the device key once, and holds what the check proved.

    The key goes in `run.metadata` because it must survive everything —
    upstream keeps it in `storage.extra_data['keys']` for the same reason.
    What the check *proved* goes in `run.proof()` because it must not.
    """

    form_class = CodeForm
    template_name = "testapp/two_factor_code.html"
    step_name = "code"

    #: Verifying spends the token, so a dry run of a candidate answer would
    #: spend it too — and record nothing, since a check places nothing. The
    #: same fact `run.proof()` exists for, said to the other reader.
    consumes_what_it_checks = True

    def key(self):
        own = self.request.run.metadata.for_step(self.step_name)
        if "key" not in own:
            own["key"] = f"{abs(hash(self.step_name)) % 0xFFFFFF:06x}"
        return own["key"]

    def get_form_kwargs(self):
        proof = self.request.run.proof(self.step_name)
        return {
            **super().get_form_kwargs(),
            "key": self.key(),
            "already_proven": proof.get("code"),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The demo stands in for an authenticator app and a text message.
        context["code"] = code_for(self.key())
        context["proof"] = self.request.run.proof(self.step_name)
        return context

    def form_valid(self, form):
        self.request.run.proof(self.step_name)["code"] = form.cleaned_data["code"]
        return super().form_valid(form)


class GeneratorCodeStepView(CodeStepView):
    step_name = "generator"


class SMSCodeStepView(CodeStepView):
    step_name = "validation"


class SetupMethod:
    """One entry in upstream's `MethodRegistry`: a code, a name, and the
    steps that set it up.

    The steps are a function from a wizard to a wizard, which is upstream's
    shape too — `get_setup_forms(wizard)` is handed the wizard it is adding
    to. It reads both ways round: chained onto the welcome step when there
    is only one method, and called on an empty wizard to make a switch arm
    when there are several.
    """

    def __init__(self, code, label, steps):
        self.code = code
        self.label = label
        self.steps = steps

    @property
    def wizard(self):
        return self.steps(Wizard())


GENERATOR = SetupMethod(
    "generator",
    "Token generator",
    lambda wizard: wizard.step(GeneratorCodeStepView, name="generator"),
)

SMS = SetupMethod(
    "sms",
    "Text message",
    lambda wizard: (
        wizard.step(PhoneNumberForm, name="sms").step(
            SMSCodeStepView, name="validation"
        )
    ),
)


class SetupViewSet(WizardViewSet):
    description = (
        "django-two-factor-auth's setup wizard, translated: the shape comes "
        "from a method registry per request, and the code step holds a check "
        "that consumes what it checks."
    )
    url_name = "formtools-two-factor"
    template_name = "testapp/linear_wizard.html"

    #: Upstream's registry. An attribute so the single-method case below is
    #: a subclass rather than a second wizard.
    methods = [GENERATOR, SMS]

    def get_wizard(self, run):
        wizard = Wizard().step(WelcomeForm, name="welcome")
        if len(self.methods) == 1:
            # Nothing to ask, so nothing is declared — and no answer has to
            # be forged into storage to stand in for the question.
            wizard = self.methods[0].steps(wizard)
        else:
            wizard = wizard.step(MethodStepView, name="method").switch(
                on_field("method", "method"),
                {method.code: method.wizard for method in self.methods},
            )
        return wizard.step(DeviceNameForm, name="name")

    def done(self, run):
        names = [step.name for step in run.path.filter_steps()]
        return HttpResponse(
            f"set up via {names}, verified {len(VERIFICATIONS)} time(s)"
        )


class SingleMethodSetupViewSet(SetupViewSet):
    description = (
        "The same wizard with one method registered: the 'how do you want "
        "to sign in?' step is not declared at all."
    )
    url_name = "formtools-two-factor-single"
    methods = [GENERATOR]
