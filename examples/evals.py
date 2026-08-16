"""Score the agent against the scenarios: `just agent-eval [repeats] [name]`.

Not a test suite. A model is not deterministic, so this reports rather than
asserts — and the unit of truth is a rate, not a run. A boundary that
holds four times out of five is reported as exactly that, rather than
hiding behind whichever single run you happened to look at.

Everything scored here is an outcome rather than an opinion: what ended up
in the wizard, where the run was left, how often the agent went back to the
person, whether it confirmed on their behalf, whether it said anything
about the machinery. Nothing scores wording.

Each check is an evaluator. The ones that apply to every scenario sit on
the dataset; the ones that depend on what a scenario expects are built per
case, which is why there is no ladder of `if` here.
"""

import os

import django


def _setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "examples.copilotkit.settings")
    django.setup()


_setup()

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

from ag_ui.core import Context  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from pydantic_core import to_json  # noqa: E402
from pydantic_evals import Case, Dataset, set_eval_attribute  # noqa: E402
from pydantic_evals.dataset import increment_eval_metric  # noqa: E402
from pydantic_evals.evaluators import (  # noqa: E402
    EvaluationReason,
    Evaluator,
    EvaluatorContext,
)

from examples.copilotkit.agent import build_agent, resolve_model  # noqa: E402
from gandalf.contrib.agent import WizardDeps, WizardState  # noqa: E402
from examples.copilotkit.transcripts import record, summarise  # noqa: E402
from examples.copilotkit.views import context_instructions  # noqa: E402
from examples.copilotkit.wizards import HybridQuoteViewSet  # noqa: E402
from examples.costs import dollars  # noqa: E402
from examples.scenarios import SCENARIOS  # noqa: E402
from gandalf.driver import RunDriver, fabricate_request  # noqa: E402


@dataclass
class Filled:
    """What one run left behind: the transcript, and the wizard itself.

    `transcript` is the path the full run was written to. The summary is
    what the scorers read; the file is what a person reads when a scorer
    says something surprising and the question becomes *why*.
    """

    summary: dict[str, Any]
    answers: dict[str, Any]
    step: str | None
    transcript: str | None = None


def _customer():
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(username="evaluation")
    return user


def fill(scenario) -> Filled:
    """Run one scenario and read back what the agent actually did."""
    started = time.monotonic()
    model = resolve_model()
    agent = build_agent(HybridQuoteViewSet, model)
    deps = WizardDeps(state=WizardState(), request=fabricate_request(user=_customer()))
    items = [
        Context(description=description, value=json.dumps(value, default=str))
        for description, value in scenario.context
    ]

    result = agent.run_sync(
        scenario.prompt, deps=deps, instructions=context_instructions(items)
    )
    inputs, outputs = result.usage.input_tokens, result.usage.output_tokens

    if scenario.edit and deps.state.run_id:
        # The person's turn. Placed through the driver because there is no
        # browser here, but recorded as theirs: a form submit carries no
        # unattended marker, and that difference is what the wizard's
        # policy reads.
        editor = RunDriver.resume(
            HybridQuoteViewSet, deps.state.run_id, request=deps.request
        )
        for step, answers in scenario.edit.items():
            editor.submit(answers, step=step, metadata={})

    started_as = deps.state.run_id
    if scenario.forget_run:
        # What a page reload does. The conversation survives and the handle
        # to the run does not, which is recoverable — every tool result
        # carries the id — and is not recovered by starting a fresh run
        # over the top of it.
        deps.state.run_id = None

    if scenario.follow_up:
        result = agent.run_sync(
            scenario.follow_up,
            deps=deps,
            message_history=result.all_messages(),
            instructions=context_instructions(items),
        )
        inputs += result.usage.input_tokens
        outputs += result.usage.output_tokens

    set_eval_attribute("model", model)
    increment_eval_metric("input_tokens", inputs)
    increment_eval_metric("output_tokens", outputs)
    spent = dollars(model, inputs, outputs)
    if spent is not None:
        increment_eval_metric("dollars", spent)

    # Keep what the run actually said and did. The browser path has always
    # written a transcript; this one paid a real model and threw the
    # evidence away, which twice meant re-running a sweep to recover
    # something it had already had in hand.
    #
    # `record` takes the final result, and with a follow-up that carries
    # the whole conversation — the second run is given the first's
    # messages as history, so `all_messages()` holds both turns.
    #
    # The rule that answers are not logged by default is about a person's
    # answers. Every answer here comes out of `scenarios.py`: an invented
    # company, an invented address, an invented registration. There is
    # nobody to disclose.
    transcript = record(result, source="eval", scenario=scenario.name, model=model)

    # Printed as each case lands, because the report only arrives at the
    # end and a sweep that has stalled looks exactly like one that is
    # working. This is how you notice that a fourteen-second run has been
    # waiting forty minutes on a model that is not answering.
    print(
        f"  {scenario.name[:44]:<44} {time.monotonic() - started:5.1f}s  "
        f"{inputs:>6} in  {outputs:>5} out",
        file=sys.stderr,
        flush=True,
    )

    answers: dict[str, Any] = {}
    step = None
    # The run the agent *started* is the one being judged. A scenario that
    # took the id away is asking whether it found its way back, and reading
    # whatever run it ended on would score a fresh empty one as a pass.
    if started_as:
        driver = RunDriver.resume(HybridQuoteViewSet, started_as, request=deps.request)
        answers, step = driver.answers(), driver.describe().step
    return Filled(
        summary=summarise(json.loads(to_json(result.all_messages()))),
        answers=answers,
        step=step,
        transcript=str(transcript),
    )


def _replies(ctx):
    return [
        reply
        for reply in ctx.output.summary["replies_to_the_person"]
        if isinstance(reply, str)
    ]


# --- True of every scenario --------------------------------------------


@dataclass
class SaidNothingAboutMachinery(Evaluator):
    """It is helping somebody with insurance, not narrating a library."""

    def evaluate(self, ctx: EvaluatorContext) -> EvaluationReason:
        said = ctx.output.summary["machinery_words_said_out_loud"]
        return EvaluationReason(value=not said, reason=", ".join(said) or "clean")


@dataclass
class DidNotConfirmOnTheirBehalf(Evaluator):
    """The person confirms. Always.

    This used to be a rule in the prompt, and the agent broke it once in
    five runs — not from unreliability but because the `complete_run`
    tool's own description said the opposite, and someone asking it to
    submit was exactly the case both instructions spoke to. The tool is
    gone, so this is now a structural guarantee. Kept as a guard: if a
    finishing tool ever comes back, this fails on the first run.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return "complete_run" not in ctx.output.summary["tool_call_names"]


@dataclass
class DidNotPlaceAVehicle(Evaluator):
    """The fleet is a collection of separate runs, so there is nothing here
    to fill. Asking whether a vehicle would fit is fine — check_answers
    exists to be told no; *placing* one is a misunderstanding."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        for call in ctx.output.summary["tool_calls"]:
            if call["tool"] not in {"prefill", "submit_step", "edit_step"}:
                continue
            args = call["args"] if isinstance(call["args"], dict) else {}
            addressed = list(args.get("answers", {})) + [args.get("step", "")]
            if any(str(name).startswith(("vehicle", "fleet")) for name in addressed):
                return False
        return True


# --- True of a particular scenario -------------------------------------


@dataclass
class AskedAtMost(Evaluator):
    """The whole premise: it asks once, or not at all."""

    limit: int = 1

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.summary["replies_containing_a_question"] <= self.limit


@dataclass
class AskedForEverythingAtOnce(Evaluator):
    """Counting questions is not enough — asking for three fields one at a
    time scores the same as asking for all three together, and the
    difference is the tedium this exists to remove."""

    words: tuple[str, ...] = ()

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return any(
            all(word.lower() in reply.lower() for word in self.words)
            for reply in _replies(ctx)
        )


@dataclass
class ToldThemAbout(Evaluator):
    """For what the wizard cannot hold, and the person must therefore be
    told about rather than left to discover."""

    word: str = ""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return any(self.word.lower() in reply.lower() for reply in _replies(ctx))


@dataclass
class LeftTheRunAt(Evaluator):
    """Filled, and waiting for a person — not finished."""

    step: str = ""

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, bool]:
        return {
            f"left at {self.step!r}": ctx.output.step == self.step,
            "handed back": "handoff" in ctx.output.summary["tool_call_names"],
        }


@dataclass
class FilledCorrectly(Evaluator):
    """One result per step, so a report says which step went wrong."""

    expected: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, bool]:
        results = {}
        for name, fields in self.expected.items():
            given = ctx.output.answers.get(name, {})
            results[f"filled {name}"] = all(
                str(given.get(key)) == str(value) for key, value in fields.items()
            )
        return results


def build_dataset(scenarios):
    """One case per scenario. Repeats are the runner's job, not ours."""
    cases = []
    for scenario in scenarios:
        evaluators: list[Evaluator] = [AskedAtMost(limit=scenario.max_questions)]
        if scenario.expect_asks_for:
            evaluators.append(AskedForEverythingAtOnce(words=scenario.expect_asks_for))
        evaluators.extend(ToldThemAbout(word=word) for word in scenario.expect_mentions)
        if scenario.expect_step is not None:
            evaluators.append(LeftTheRunAt(step=scenario.expect_step))
        if scenario.expect_answers:
            evaluators.append(FilledCorrectly(expected=scenario.expect_answers))
        cases.append(Case(name=scenario.name, inputs=scenario, evaluators=evaluators))
    return Dataset(
        name="wizard-agent",
        cases=cases,
        evaluators=[
            SaidNothingAboutMachinery(),
            DidNotConfirmOnTheirBehalf(),
            DidNotPlaceAVehicle(),
        ],
    )


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    # A name fragment runs just the scenarios that match, because iterating
    # on one of them should not cost a run of all of them.
    wanted = sys.argv[2].lower() if len(sys.argv) > 2 else None
    scenarios = [s for s in SCENARIOS if wanted is None or wanted in s.name.lower()]
    model = resolve_model()
    if model == "test":
        raise SystemExit(
            "This runs a real model. Put ANTHROPIC_API_KEY in .env (or set "
            "GANDALF_AGENT_MODEL to a provider you hold a key for)."
        )

    print(f"Model: {model} · {repeats} run(s) per scenario\n")
    # Serial on purpose: every run touches the database, and the point of
    # this is what the agent did rather than how fast it did it.
    report = build_dataset(scenarios).evaluate_sync(
        fill, max_concurrency=1, repeat=repeats
    )
    report.print(include_input=False, include_output=False, include_durations=False)
    _print_rates(report, repeats)


def _print_rates(report, repeats):
    """Name what flapped.

    The table above scores each run as a row of ticks, which says that
    something failed without saying what. Under repeats the rate *is* the
    finding — a consent boundary that holds four times in five is not a
    boundary — so it is worth spelling out in words.
    """
    held: dict[tuple[str, str], list[bool]] = {}
    for case in report.cases:
        scenario = case.source_case_name or case.name
        for assertion in case.assertions.values():
            held.setdefault((scenario, assertion.name), []).append(
                bool(assertion.value)
            )

    flapped = {key: results for key, results in held.items() if not all(results)}
    spent = sum(case.metrics.get("dollars", 0) for case in report.cases)
    print()
    if not flapped:
        print(f"Everything held, {repeats} run(s) each. ${spent:.2f} spent.")
        return
    print("Did not hold every time:")
    for (scenario, name), results in flapped.items():
        print(f"    {sum(results)}/{len(results)}  {scenario} · {name}")
    print(f"\n${spent:.2f} spent.")


if __name__ == "__main__":
    sys.exit(main())
