"""Synthetic wizard generator.

Builds wizards parameterised by the three dimensions issue #46 asks about —
step count, field count, and `clean()` cost — plus a branching variant, and
publishes each as a `WizardViewSet` ready to mount.

Each builder returns a `BenchmarkWizard` carrying the payload to submit for
every step, keyed by URL segment. The journey driver needs that: it walks the
run by following redirects and only ever knows the step it has landed on by
its slug.
"""

import time
from dataclasses import dataclass

from django import forms
from django.http import HttpResponse

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import Wizard, condition

from benchmarks.instrumentation import CountingCursorWalker, CountingStepDispatcher
from benchmarks.settings import STEP_TEMPLATE_NAME


@dataclass
class BenchmarkWizard:
    """A generated wizard, mountable and self-describing."""

    label: str
    viewset_class: type
    # URL segment -> valid POST payload for that step.
    payloads: dict
    # Steps on the path the driver will actually take, which for a branching
    # wizard is fewer than the number of steps declared.
    path_length: int


class BenchmarkForm(forms.Form):
    """Base for generated step forms.

    `clean_seconds` models the common expensive case: a `clean()` that hits
    the database. Sleeping rather than burning CPU is the right model for
    that — it is I/O the walk pays for once per completed step per request.
    """

    clean_seconds = 0.0

    def clean(self):
        cleaned_data = super().clean()
        if self.clean_seconds:
            time.sleep(self.clean_seconds)
        return cleaned_data


def _naming(segment):
    """Name a step the long way round.

    `.step(..., name=...)` is the preferred spelling today, but it only
    arrived in 85346b7. Spelling it as explicit context instead costs
    nothing and lets the harness be checked out against older commits to
    bisect a cost change — which is most of the value of counting at all.
    """
    return {"context": {"step_name": segment}}


def _class_name(segment, suffix="Form"):
    return "".join(part.title() for part in segment.split("-")) + suffix


def _make_step_form(segment, *, fields, clean_seconds):
    attrs = {f"field_{n}": forms.CharField() for n in range(fields)}
    attrs["clean_seconds"] = clean_seconds
    return type(_class_name(segment), (BenchmarkForm,), attrs)


def _step_payload(fields):
    return {f"field_{n}": "x" for n in range(fields)}


def _make_decision_form(segment, *, clean_seconds):
    attrs = {
        "choice": forms.ChoiceField(choices=[("a", "A"), ("b", "B")]),
        "clean_seconds": clean_seconds,
    }
    return type(_class_name(segment), (BenchmarkForm,), attrs)


def _chose(segment, value):
    """Predicate reading a decided step's cleaned data.

    Written the way the README writes them, which matters: `RuntimeStep.form`
    re-instantiates and re-validates the step's form, so a predicate is
    itself a cost the walk pays. This is the same shape as formtools'
    `condition_dict` callables calling `get_cleaned_data_for_step()`.
    """

    def predicate(request):
        step = request.wizard.find_step(step_name=segment)
        return step.form.cleaned_data["choice"] == value

    predicate.__name__ = f"chose_{value}_at_{segment.replace('-', '_')}"
    return predicate


def _done(self, bound_wizard):
    return HttpResponse("done")


def _configuration(instrumented):
    configuration = {"template_name": STEP_TEMPLATE_NAME}
    if instrumented:
        configuration["step_dispatcher_class"] = CountingStepDispatcher
        configuration["cursor_walker_class"] = CountingCursorWalker
    return configuration


def _configuring(configuration):
    """A `configure_wizard` that folds the counting classes in.

    Mirrors what `WizardViewSet.configure_wizard` does for a viewset
    declaring a plain `Wizard`: build a fresh `ConfiguredWizard` on every
    resolve. That per-resolve rebuild is itself part of what is being
    measured, so it must not be optimised away here.
    """

    def configure_wizard(self, wizard):
        return wizard.configure(**configuration)

    return configure_wizard


def _build_viewset(
    *, url_name, instrumented, wizard=None, get_wizard=None, preconfigured=True
):
    configuration = _configuration(instrumented)
    attrs = {"url_name": url_name, "done": _done}
    if get_wizard is not None:
        # A dynamic wizard is rebuilt from stored state every request by
        # definition, so there is nothing to pre-configure.
        attrs["get_wizard"] = get_wizard
        attrs["configure_wizard"] = _configuring(configuration)
    elif preconfigured:
        attrs["wizard"] = wizard.configure(**configuration)
    else:
        attrs["wizard"] = wizard
        attrs["configure_wizard"] = _configuring(configuration)
    return type("BenchmarkWizardViewSet", (WizardViewSet,), attrs)


def linear_wizard(
    *, steps, fields=1, clean_seconds=0.0, instrumented=True, preconfigured=True
):
    """A flat run of `steps` identical steps — the baseline shape.

    `preconfigured` picks which of the two static spellings is measured:
    a `ConfiguredWizard` class attribute (`.configure()` called once at
    import), or a plain `Wizard` that the viewset configures per request.
    They are the same wizard and differ only in object identity across
    resolves, which is precisely what walk-reuse turns on.
    """
    wizard = Wizard()
    payloads = {}
    for index in range(steps):
        segment = f"step-{index}"
        form_class = _make_step_form(
            segment, fields=fields, clean_seconds=clean_seconds
        )
        wizard = wizard.step(form_class, **_naming(segment))
        payloads[segment] = _step_payload(fields)

    spelling = "configured" if preconfigured else "plain Wizard"
    label = f"linear steps={steps} fields={fields} clean={clean_seconds}s [{spelling}]"
    return BenchmarkWizard(
        label=label,
        viewset_class=_build_viewset(
            wizard=wizard,
            url_name="bench",
            instrumented=instrumented,
            preconfigured=preconfigured,
        ),
        payloads=payloads,
        path_length=steps,
    )


def dynamic_wizard(*, items, fields=1, clean_seconds=0.0, instrumented=True):
    """The documented dynamic idiom: answer a count, and the tree grows that
    many steps.

    This is the shape `_refreshed_cursor` exists for. The tree resolved at
    the start of the count POST does not yet contain the steps that POST
    implies, so anything that skips the refresh walk must not skip it here.
    """
    count_segment = "count"
    count_form = type(
        "CountForm",
        (BenchmarkForm,),
        {
            "count": forms.IntegerField(min_value=0, max_value=1000),
            "clean_seconds": clean_seconds,
        },
    )
    item_forms = [
        _make_step_form(f"item-{index}", fields=fields, clean_seconds=clean_seconds)
        for index in range(items)
    ]

    def get_wizard(self, bound_wizard):
        state = bound_wizard.get_state()
        wizard = Wizard().step(count_form, **_naming(count_segment))
        if state:
            count = int(state[0]["step"]["count"])
            for index in range(count):
                wizard = wizard.step(item_forms[index], **_naming(f"item-{index}"))
        return wizard

    payloads = {count_segment: {"count": str(items)}}
    for index in range(items):
        payloads[f"item-{index}"] = _step_payload(fields)

    return BenchmarkWizard(
        label=f"dynamic items={items} fields={fields} clean={clean_seconds}s",
        viewset_class=_build_viewset(
            url_name="bench", instrumented=instrumented, get_wizard=get_wizard
        ),
        payloads=payloads,
        path_length=1 + items,
    )


def branching_wizard(
    *, sections, arm_steps, fields=1, clean_seconds=0.0, instrumented=True
):
    """`sections` repetitions of: one decision step, then a two-arm branch.

    Both arms are the same length, so the path taken is the same length
    whichever way each decision goes. What this isolates is whether dormant
    arms cost anything — reading `CursorWalker.visit_branch`, only the
    selected arm recurses, so they should not.
    """
    wizard = Wizard()
    payloads = {}
    for section in range(sections):
        decision_segment = f"s{section}-choice"
        wizard = wizard.step(
            _make_decision_form(decision_segment, clean_seconds=clean_seconds),
            **_naming(decision_segment),
        )
        payloads[decision_segment] = {"choice": "a"}

        arms = {}
        for arm in ("a", "b"):
            arm_wizard = Wizard()
            for index in range(arm_steps):
                segment = f"s{section}{arm}-{index}"
                arm_wizard = arm_wizard.step(
                    _make_step_form(
                        segment, fields=fields, clean_seconds=clean_seconds
                    ),
                    **_naming(segment),
                )
                payloads[segment] = _step_payload(fields)
            arms[arm] = arm_wizard

        wizard = wizard.branch(
            condition(_chose(decision_segment, "a"), arms["a"]),
            default=arms["b"],
        )

    label = (
        f"branching sections={sections} arm_steps={arm_steps} "
        f"fields={fields} clean={clean_seconds}s"
    )
    return BenchmarkWizard(
        label=label,
        viewset_class=_build_viewset(
            wizard=wizard, url_name="bench", instrumented=instrumented
        ),
        payloads=payloads,
        path_length=sections * (1 + arm_steps),
    )
