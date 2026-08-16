"""A `pydantic-ai` toolset over one wizard, and an agent that carries it.

Every tool here is a thin call into `RunDriver` — start a run, describe
where it is, check a bag of answers, place them, hand it back — so a
wizard behaves the same whether a person walks it in a browser or a model
fills it from a conversation. Nothing in `gandalf` proper knows any of
this exists.

Two things are deliberately absent.

There is no tool that concludes a run. `done()` is where the irreversible
things live, and an agent that can reach them will eventually reach them
on somebody's behalf. `handoff` returns the person a link instead, which
is the only ending this toolset offers.

There is no edit policy, and that is the harder of the two absences to
hold on to. It is tempting to stop an agent changing an answer a person
typed, and this toolset does not, because whose an answer is is a
question about an application rather than about wizards — a service
where an agent tidies what somebody half-filled wants the opposite rule
from one confirming identity.

`RunDriver.placements()` carries who placed each answer, so an
application can write the rule it wants; `wrap` is where it goes, since
a toolset that refuses a call is a toolset with something wrapped round
it. Note that an agent correcting *its own* earlier answer must stay
allowed whatever the rule: that is how it recovers from a rejected one.

`attach_document` appears only for a wizard that has somewhere to put a
file, which is derived from the outline rather than declared: a wizard
knows whether it has a `FileField`, and a flag saying otherwise would
only ever be wrong. A tool an agent cannot use is one it can only misuse.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from pydantic_ai import Agent, ModelRetry, RunContext, ToolReturn
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from gandalf.contrib.agent.deps import WizardDeps, _snapshot
from gandalf.contrib.agent.prompt import build_instructions
from gandalf.driver import (
    RunComplete,
    RunDriver,
    fabricate_request,
    outline_steps,
)
from gandalf.runtime import StepNotFound
from gandalf.viewsets import WizardViewSet


def accepts_documents(viewset_class: type[WizardViewSet]) -> bool:
    """Whether any step of `viewset_class` takes an uploaded file.

    Derived rather than declared. A wizard knows this about itself, and a
    flag beside it could only ever agree or be wrong — and it would be
    wrong quietly, as an agent being unhelpful rather than as anything
    failing.

    Asked of the schema's `format`, which is the machine-readable half of
    what a field says about itself. The description beside it says the
    same thing in words, and reading *that* would make a sentence somebody
    might reasonably reword into the thing that decides whether an agent
    gets a tool.
    """
    outline = RunDriver.outline_for(viewset_class, request=fabricate_request())
    return any(
        prop.get("format") == "binary"
        for entry in outline_steps(outline)
        for prop in entry["schema"]["properties"].values()
    )


def build_toolset(
    viewset_class: type[WizardViewSet],
) -> FunctionToolset[WizardDeps]:
    """The tools for driving `viewset_class`, mirroring the run into state."""
    toolset: FunctionToolset[WizardDeps] = FunctionToolset()

    def _driver(ctx: RunContext[WizardDeps]) -> RunDriver:
        run_id = ctx.deps.state.run_id
        if run_id is None:
            raise ModelRetry("No run is active; call start_run first.")
        # Resumed per call rather than cached: a run lives in storage, not
        # in this process, which is the whole point of the handover.
        return RunDriver.resume(viewset_class, run_id, request=ctx.deps.request)

    def _sync(
        ctx: RunContext[WizardDeps],
        driver: RunDriver,
        extra: dict[str, Any] | None = None,
    ) -> ToolReturn:
        # Everything here is bound for the model and the browser, so the
        # answers are asked for as JSON rather than as cleaned Python
        # values. Converting them here costs no extra walk.
        description = driver.describe(json_safe=True)
        state = ctx.deps.state
        state.run_id = driver.run_id
        state.step = description.step
        state.step_schema = description.schema
        state.answers = description.answers
        state.complete = description.complete
        payload = {
            "run_id": driver.run_id,
            "step": description.step,
            "schema": state.step_schema,
            "answers": state.answers,
            "errors": description.errors,
            "complete": description.complete,
            **(extra or {}),
        }
        return ToolReturn(return_value=payload, metadata=[_snapshot(state)])

    @toolset.tool
    def start_run(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """Start a fresh wizard run and describe its current step: the
        step's name, a JSON Schema for the answers it wants, everything
        answered so far, and whether the run is complete."""
        driver = RunDriver.begin(viewset_class, request=ctx.deps.request)
        return _sync(ctx, driver)

    @toolset.tool
    def get_outline(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """The wizard's full declared shape: every step with its JSON
        Schema, every fork with all of its possible routes, and markers
        where the tree grows from an answer. Answerable before anything
        has been started, so call it first to plan the conversation."""
        outline = RunDriver.outline_for(viewset_class, request=ctx.deps.request)
        ctx.deps.state.outline = outline
        if ctx.deps.state.run_id is None:
            # Describing a wizard needs no run, and starting one to answer
            # a question about the declaration would leave a run behind
            # for every wizard anybody merely asked about.
            return ToolReturn(
                return_value={"outline": outline}, metadata=[_snapshot(ctx.deps.state)]
            )
        driver = _driver(ctx)
        return _sync(ctx, driver, extra={"outline": outline})

    @toolset.tool
    def check_answers(
        ctx: RunContext[WizardDeps], answers: dict[str, dict[str, Any]]
    ) -> ToolReturn:
        """Try answers against the wizard without submitting any of them.
        Returns which would validate, which would be rejected and why,
        which steps still have no answer, and which could not be judged.
        Call this before prefill so you can ask the person for everything
        you need in one message instead of one question at a time."""
        driver = _driver(ctx)
        result = driver.check(answers)
        return _sync(
            ctx,
            driver,
            extra={
                "checked": {
                    "ok": result.ok,
                    "invalid": result.invalid,
                    "missing": result.missing,
                    "unchecked": result.unchecked,
                    "unknown": result.unknown,
                }
            },
        )

    @toolset.tool
    def prefill(
        ctx: RunContext[WizardDeps], answers: dict[str, dict[str, Any]]
    ) -> ToolReturn:
        """Fill many steps at once from answers you already hold, keyed by
        step name. Placement follows the wizard's own routing — an answer
        that selects a branch or grows the tree reveals more steps to
        fill. The result reports what was placed, what was rejected, what
        was never asked for, and where the run now is."""
        driver = _driver(ctx)
        result = driver.prefill(answers)
        extra: dict[str, Any] = {
            "placed": result.placed,
            "prefill_errors": result.errors,
            "unused": result.unused,
            "escape": result.escape,
        }
        if result.unused and result.next_step:
            # Answers are placed in the wizard's own order, so a gap parks
            # everything behind it. Say so plainly rather than leaving the
            # model to conclude the person must be asked again.
            extra["hint"] = (
                f"These were not placed because the run is waiting on "
                f"{result.next_step!r}: {', '.join(result.unused)}. Answer "
                f"that step, then call prefill again with the same answers "
                f"— do not ask the person for anything you already hold."
            )
        return _sync(ctx, driver, extra=extra)

    @toolset.tool
    def submit_step(ctx: RunContext[WizardDeps], data: dict[str, Any]) -> ToolReturn:
        """Submit answers for the current step. `data` maps the current
        step's field names (from its JSON Schema) to values."""
        driver = _driver(ctx)
        try:
            result = driver.submit(data)
        except RunComplete:
            raise ModelRetry(
                "The run is already complete; hand off so it can be confirmed."
            ) from None
        if result.status == "invalid":
            raise ModelRetry(
                "The submission failed validation; fix these fields and submit "
                "again: " + json.dumps(result.errors)
            )
        return _sync(
            ctx, driver, extra={"status": result.status, "escape": result.escape}
        )

    @toolset.tool
    def edit_step(
        ctx: RunContext[WizardDeps], step: str, data: dict[str, Any]
    ) -> ToolReturn:
        """Change named fields of an already-answered step. Send only what
        you are changing: every field you leave out keeps the answer it has
        now, which may be one the person set themselves. The run re-routes
        from there — later answers are kept where they still apply, and the
        current step may change."""
        driver = _driver(ctx)
        # A step is answered whole, so replacing it with just the changed
        # fields would blank the rest — and re-sending the whole step from
        # memory quietly reverts anything the person corrected in the form
        # since. Merging over what is stored is what makes an edit an edit.
        placement = driver.placements().get(step)
        merged = {**(placement.answers if placement else {}), **data}
        try:
            result = driver.submit(merged, step=step)
        except StepNotFound:
            raise ModelRetry(f"The run cannot reach a step named {step!r}.") from None
        if result.status == "invalid":
            raise ModelRetry(
                "The edit failed validation; fix these fields and try again: "
                + json.dumps(result.errors)
            )
        return _sync(
            ctx, driver, extra={"status": result.status, "escape": result.escape}
        )

    if accepts_documents(viewset_class):

        @toolset.tool
        def attach_document(
            ctx: RunContext[WizardDeps],
            attachment_id: str,
            field: str,
            step: str | None = None,
        ) -> ToolReturn:
            """Put a file the person shared in this conversation into the
            run, as the answer to a file field. `attachment_id` names the
            file you were given (`attachment-1` for the first one), `field`
            is the field it answers, and `step` the step that field belongs
            to — omit it for the step the run is waiting on. Use this
            rather than describing the file in words; it is the file
            itself that has to be stored."""
            attachment = ctx.deps.attachments.get(attachment_id)
            if attachment is None:
                # Nothing to retry into existence, but the model may have
                # invented a handle, so say which ones are real.
                known = ", ".join(ctx.deps.attachments) or "none"
                raise ModelRetry(
                    f"There is no {attachment_id!r} in this conversation. "
                    f"Files you were given: {known}."
                )
            driver = _driver(ctx)
            upload = SimpleUploadedFile(
                attachment.name or "upload",
                attachment.data,
                content_type=attachment.media_type,
            )
            try:
                result = driver.submit({}, files={field: upload}, step=step)
            except StepNotFound:
                raise ModelRetry(
                    f"The run cannot reach a step named {step!r}."
                ) from None
            if result.status == "invalid":
                raise ModelRetry(
                    "The file was not accepted; the field errors were: "
                    + json.dumps(result.errors)
                )
            return _sync(
                ctx,
                driver,
                extra={
                    "status": result.status,
                    "attached": attachment.name or attachment.media_type,
                },
            )

    if viewset_class.url_name is not None:

        @toolset.tool
        def handoff(ctx: RunContext[WizardDeps]) -> ToolReturn:
            """Hand the run back to the person: returns the URL of their
            check-your-answers page, where they can review everything
            filled in their name, change any answer, and confirm. Use this
            instead of confirming yourself.

            Put the URL in your reply as a markdown link — `[Check and
            confirm](the url)` — and not as bare text. The chat renders
            markdown, so a bare URL arrives as something they cannot
            click, which makes the one thing you are asking them to do the
            hardest thing on the page."""
            driver = _driver(ctx)
            url = driver.bound_wizard.entry_url("confirm")
            state = ctx.deps.state
            state.handoff_url = url
            return _sync(ctx, driver, extra={"handoff_url": url})

    return toolset


def build_agent(
    viewset_class: type[WizardViewSet],
    model: Any,
    *,
    wrap: Callable[[FunctionToolset[WizardDeps]], AbstractToolset[WizardDeps]]
    | None = None,
) -> Agent[WizardDeps, str]:
    """An agent that drives `viewset_class` with `model`.

    `model` is whatever pydantic-ai takes — a `"provider:model"` string or
    a `Model` instance. Nothing here has an opinion about who serves it;
    install the provider extra you want beside this one.

    `wrap` gets the toolset before the agent does, for a caller that wants
    to see every tool call go past: logging, metrics, a policy that
    refuses one. It is a hook rather than a subclass because there is one
    place a call goes through and wrapping it leaves the tools alone.
    """
    toolset = build_toolset(viewset_class)
    return Agent(
        model,
        deps_type=WizardDeps,
        instructions=build_instructions(viewset_class),
        toolsets=[wrap(toolset) if wrap else toolset],
    )
