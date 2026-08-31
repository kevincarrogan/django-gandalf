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
from gandalf.contrib.agent.prompt import JOURNEY_PROCEDURE, build_instructions
from gandalf.driver import (
    JourneyDriver,
    RunComplete,
    RunDriver,
    outline_steps,
)
from gandalf.runtime import StepNotFound
from gandalf.storage import RunNotFound
from gandalf.tasklists import EntryNotFound, TaskListViewSet
from gandalf.types import Answer
from gandalf.viewsets import DoorRefused, WizardViewSet


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

    Two kinds of step answer nothing here, and both used to raise rather
    than answer. A step with no schema yet — a view composing its form from
    answers the run has not got — cannot be asked; and a step describing
    itself as an array repeats its fields per row, so a file in one is
    addressed as `0-document` and placed with the management form, which
    `attach_document` does not do. Neither is a step this tool could serve,
    so neither turns it on.
    """
    outline = RunDriver.outline_for(viewset_class)
    return any(
        prop.get("format") == "binary"
        for entry in outline_steps(outline)
        for prop in (entry["schema"] or {}).get("properties", {}).values()
    )


#: What to tell the model about a door that would not open. Retries rather
#: than results, because a refusal is something to say to the person and
#: work around — but never the same way twice, so each one says what would
#: have to change rather than inviting another attempt at the same thing.
_CLOSED_DOORS = {
    "submitted": (
        "This has already been submitted, so nothing on it can be "
        "answered now. Tell them, and do not try again."
    ),
    "hidden": (
        "This is not part of their application, so it cannot be filled "
        "in. Carry on with the parts that are."
    ),
    "blocked": (
        "This cannot be started yet — something earlier has to be "
        "finished first. Do that part, then come back to this one."
    ),
}


def _closed_door(refusal: DoorRefused) -> str:
    return _CLOSED_DOORS.get(
        refusal.reason, f"This cannot be opened ({refusal.reason})."
    )


def build_toolset(
    viewset_class: type[WizardViewSet],
) -> FunctionToolset[WizardDeps]:
    """The tools for driving `viewset_class`, mirroring the run into state."""
    toolset: FunctionToolset[WizardDeps] = FunctionToolset()

    def _driver(ctx: RunContext[WizardDeps]) -> RunDriver:
        run_id = ctx.deps.state.run_id
        if run_id is None:
            # Both ways out, because the id is very often recoverable: it
            # comes back on every tool call, so it is somewhere in the
            # conversation even when the client's state has lost it. An
            # agent told only to start a run will start one, and the
            # person's half-filled form is quietly abandoned.
            raise ModelRetry(
                "No run is active. If you have seen a run id in this "
                "conversation — every tool returns one — call resume_run "
                "with it rather than starting again, because starting "
                "again abandons whatever is already filled in. Call "
                "start_run only if there is genuinely no run yet."
            )
        # Resumed per call rather than cached: a run lives in storage, not
        # in this process, which is the whole point of the handover.
        return RunDriver.resume(viewset_class, run_id, context=ctx.deps.context)

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
        try:
            driver = RunDriver.begin(viewset_class, context=ctx.deps.context)
        except DoorRefused as refusal:
            raise ModelRetry(_closed_door(refusal)) from None
        return _sync(ctx, driver)

    @toolset.tool
    def resume_run(ctx: RunContext[WizardDeps], run_id: str) -> ToolReturn:
        """Pick an existing run back up by its id and describe where it is.

        Use this rather than `start_run` whenever you know a run id — you
        will have seen one in an earlier tool result, and the person may
        have been filling the form in themselves since. Starting a fresh
        run does not resume anything; it leaves whatever was already
        answered behind, and the person will be the one who notices."""
        try:
            driver = RunDriver.resume(viewset_class, run_id, context=ctx.deps.context)
        except RunNotFound:
            raise ModelRetry(
                f"There is no run with the id {run_id!r}. Check the id "
                "against an earlier tool result, or call start_run if this "
                "is a new one."
            ) from None
        except DoorRefused as refusal:
            raise ModelRetry(_closed_door(refusal)) from None
        ctx.deps.state.run_id = driver.run_id
        return _sync(ctx, driver)

    @toolset.tool
    def get_run(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """Look at the run as it is right now: the step it is waiting on, a
        JSON Schema for the answers that step wants, everything answered so
        far, and whether it is complete. Changes nothing.

        The person can open the form themselves at any time — you may have
        given them the link yourself — so what you were told earlier may no
        longer be true. Call this before answering anything about what the
        run contains or where it has got to, rather than describing what
        you remember. Somebody who has just changed an answer and is asking
        you about it will not enjoy being told what it used to say."""
        return _sync(ctx, _driver(ctx))

    @toolset.tool
    def get_outline(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """The wizard's full declared shape: every step with its JSON
        Schema, every fork with all of its possible routes, and markers
        where the tree grows from an answer. Answerable before anything
        has been started, so call it first to plan the conversation."""
        outline = RunDriver.outline_for(viewset_class, context=ctx.deps.context)
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
        ctx: RunContext[WizardDeps], answers: dict[str, Answer]
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
    def prefill(ctx: RunContext[WizardDeps], answers: dict[str, Answer]) -> ToolReturn:
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
    def submit_step(ctx: RunContext[WizardDeps], data: Answer) -> ToolReturn:
        """Submit answers for the current step. `data` maps the current
        step's field names (from its JSON Schema) to values — or is a list
        of one such mapping per row, for a step whose schema is an array."""
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
    def edit_step(ctx: RunContext[WizardDeps], step: str, data: Answer) -> ToolReturn:
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
        #
        # Rows are the exception, and not an oversight: a step answered
        # with n of them has no field to merge onto, and merging by
        # position would silently keep a row the caller meant to drop. A
        # list replaces what is there, which is also how the person's own
        # form submits one.
        placement = driver.placements().get(step)
        stored = placement.answers if placement else {}
        merged: Answer = (
            data
            if isinstance(data, list) or isinstance(stored, list)
            else {**stored, **data}
        )
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
            """Give the person a link into their own run, so they can pick
            it up in the form themselves. It lands on whatever they need to
            do next: the step the run is waiting on, or the page that lists
            everything filled in their name for them to check and confirm.

            Use this whenever they ask to take over, to see it, to finish
            it themselves, or to carry on later — not only at the end. It
            is their run, and asking for it is not a request you have to
            weigh. Use it at the end as well, instead of confirming
            anything yourself.

            Put the URL in your reply as a markdown link — `[carry on
            here](the url)` — and not as bare text. The chat renders
            markdown, so a bare URL arrives as something they cannot
            click, which makes the one thing you are asking them to do the
            hardest thing on the page."""
            driver = _driver(ctx)
            # No step named: the run is asked where it is. Naming one —
            # this used to say "confirm" — assumes every wizard has a step
            # called that, which is true of the demo it was written against
            # and of nothing else.
            url = driver.run.entry_url()
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


def _rows(journey: JourneyDriver) -> list[dict[str, Any]]:
    """The page as data: one row per listed entry, as a person sees it."""
    return [
        {
            "key": row.key,
            "title": str(row.title),
            "status": str(row.status),
            "status_label": str(row.status_label),
        }
        for row in journey.rows()
    ]


def _page_sync(
    ctx: RunContext[WizardDeps],
    journey: JourneyDriver,
    extra: dict[str, Any] | None = None,
) -> ToolReturn:
    """Every journey tool returns the page, for the reason every run tool
    returns the run: the answer to "where are we now" must not depend on
    which tool was called."""
    state = ctx.deps.state
    state.journey_id = journey.journey_id
    state.journey_url = journey.url
    state.rows = _rows(journey)
    payload = {
        "journey_id": journey.journey_id,
        "url": journey.url,
        "rows": state.rows,
        "complete": journey.is_complete,
        **(extra or {}),
    }
    return ToolReturn(return_value=payload, metadata=[_snapshot(state)])


def build_journey_toolset(
    task_list_viewset: type[TaskListViewSet],
) -> FunctionToolset[WizardDeps]:
    """The tools for driving a task list, mirroring the page into state.

    `build_toolset` drives one wizard, and its tools need no key because
    there is only ever one run. A journey is several, so every tool here
    takes the row it is about — which is what keeps the vocabulary static
    and stateless: there is no "current section" to get out of step with
    what the person has been doing in the browser meanwhile.

    The verbs are whole sections rather than steps, because that is what
    front-loading a journey is: read the whole shape, ask once, fill what
    you were told. `fill_section` is `prefill` and follows the wizard's own
    routing to a fixpoint, so an answer that opens a branch consumes the
    answers behind it in the same call.

    Nothing here submits the journey, for the reason nothing in
    `build_toolset` concludes a run: `journey_done()` is where the
    irreversible things live, and the person presses it.
    """
    toolset: FunctionToolset[WizardDeps] = FunctionToolset()

    def _journey(ctx: RunContext[WizardDeps]) -> JourneyDriver:
        journey_id = ctx.deps.state.journey_id
        if journey_id is None:
            raise ModelRetry(
                "No application is open. If you have seen an application id "
                "in this conversation — every tool returns one — call "
                "resume_application with it rather than starting again, "
                "because starting again abandons whatever is already filled "
                "in. Call start_application only if there is genuinely none."
            )
        return JourneyDriver.resume(
            task_list_viewset, journey_id, context=ctx.deps.context
        )

    def _section(ctx: RunContext[WizardDeps], key: str) -> RunDriver:
        try:
            return _journey(ctx).section(key)
        except EntryNotFound:
            known = ", ".join(row["key"] for row in _rows(_journey(ctx)))
            raise ModelRetry(
                f"There is no part of this called {key!r}. The parts are: {known}."
            ) from None
        except DoorRefused as refusal:
            raise ModelRetry(_closed_door(refusal)) from None

    def _described(driver: RunDriver) -> dict[str, Any]:
        description = driver.describe(json_safe=True)
        return {
            "run_id": driver.run_id,
            "step": description.step,
            "schema": description.schema,
            "answers": description.answers,
            "errors": description.errors,
            "complete": description.complete,
        }

    @toolset.tool
    def start_application(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """Start a fresh application and describe it: its id, its page, and
        every part of it with how far that part has got."""
        journey = JourneyDriver.begin(task_list_viewset, context=ctx.deps.context)
        return _page_sync(ctx, journey, extra={"parts": journey.outline()})

    @toolset.tool
    def resume_application(ctx: RunContext[WizardDeps], journey_id: str) -> ToolReturn:
        """Pick an existing application back up by its id.

        Use this rather than `start_application` whenever you know one —
        you will have seen it in an earlier tool result, and the person may
        have been filling parts in themselves since."""
        journey = JourneyDriver.resume(
            task_list_viewset, journey_id, context=ctx.deps.context
        )
        return _page_sync(ctx, journey, extra={"parts": journey.outline()})

    @toolset.tool
    def get_application(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """How the application stands now: every part and how far it has
        got. Look here before you say anything about what it contains —
        they may have been filling it in themselves while you talked."""
        return _page_sync(ctx, _journey(ctx))

    @toolset.tool
    def get_part(ctx: RunContext[WizardDeps], part: str) -> ToolReturn:
        """One part of the application: what it is waiting on, a JSON
        Schema for the answers that want, everything answered so far, and
        anything it refused."""
        return ToolReturn(return_value=_described(_section(ctx, part)))

    @toolset.tool
    def check_part(
        ctx: RunContext[WizardDeps], part: str, answers: dict[str, Answer]
    ) -> ToolReturn:
        """Try answers for one part without filling anything in. Says what
        is wrong and what is still missing, so you can ask for all of it at
        once rather than one question at a time. `answers` is keyed by the
        step names that part's schema gives."""
        result = _section(ctx, part).check(answers)
        return ToolReturn(
            return_value={
                "ok": result.ok,
                "invalid": result.invalid,
                "missing": result.missing,
                "unchecked": result.unchecked,
                "unknown": result.unknown,
            }
        )

    @toolset.tool
    def fill_part(
        ctx: RunContext[WizardDeps], part: str, answers: dict[str, Answer]
    ) -> ToolReturn:
        """Fill in as much of one part as you hold, keyed by its step names.

        Placement follows the questions wherever the answers lead, so an
        answer that opens up further questions lets the ones behind it be
        placed in the same call. What could not be placed comes back
        saying why."""
        driver = _section(ctx, part)
        result = driver.prefill(answers)
        if result.errors:
            raise ModelRetry(
                "Some answers were not accepted: "
                + json.dumps(result.errors)
                + ". Fix them and call fill_part again with the same answers "
                "and the corrections."
            )
        # The part goes under its own key rather than beside the page's.
        # Both have a `complete`, and they mean different things — this
        # part is answered, versus every part is — so splatting one over
        # the other tells the model the application is finished the moment
        # its first section is.
        return _page_sync(
            ctx,
            _journey(ctx),
            extra={
                "part": {
                    "key": part,
                    "placed": result.placed,
                    "unused": result.unused,
                    "waiting_on": result.next_step,
                    **_described(driver),
                }
            },
        )

    @toolset.tool
    def add_to_list(
        ctx: RunContext[WizardDeps], part: str, answers: dict[str, Answer]
    ) -> ToolReturn:
        """Put one thing on a part that is a list of them — one call, one
        thing. `answers` is keyed by the step names of the questions asked
        about each one."""
        journey = _journey(ctx)
        try:
            driver = journey.add(part)
        except EntryNotFound as error:
            raise ModelRetry(str(error)) from None
        result = driver.prefill(answers)
        if result.errors:
            # Registered but empty reads on their page as a half-added
            # thing. Take it back off rather than leave one.
            journey.remove(part, _newest(journey, part))
            raise ModelRetry(
                "That was not accepted, so nothing was added: "
                + json.dumps(result.errors)
                + ". Fix it and call add_to_list again."
            )
        return _page_sync(
            ctx,
            _journey(ctx),
            extra={"part": {"key": part, **_described(driver)}},
        )

    @toolset.tool
    def remove_from_list(
        ctx: RunContext[WizardDeps], part: str, item_id: str
    ) -> ToolReturn:
        """Take one thing off a part that is a list of them. `item_id` is
        the id the list reported for it."""
        journey = _journey(ctx)
        try:
            journey.remove(part, item_id)
        except EntryNotFound as error:
            raise ModelRetry(str(error)) from None
        return _page_sync(ctx, _journey(ctx), extra={"part": {"key": part}})

    @toolset.tool
    def handoff(ctx: RunContext[WizardDeps]) -> ToolReturn:
        """Give them the link to their application so they can look it
        over, change anything, and submit it themselves. Say what is left
        to do. Do this whenever they ask for it, and when there is nothing
        left for you to fill in."""
        journey = _journey(ctx)
        ctx.deps.state.handoff_url = journey.url
        return _page_sync(ctx, journey, extra={"handoff_url": journey.url})

    return toolset


def _newest(journey: JourneyDriver, part: str) -> str:
    """The item just added, which is the last one on the list."""
    return journey.items(part).rows[-1].item_id


def build_journey_agent(
    task_list_viewset: type[TaskListViewSet],
    model: Any,
    *,
    wrap: Callable[[FunctionToolset[WizardDeps]], AbstractToolset[WizardDeps]]
    | None = None,
) -> Agent[WizardDeps, str]:
    """An agent that drives a task list with `model`.

    `build_agent` for a journey: the same shape, the same `wrap` hook, and
    `JOURNEY_PROCEDURE` instead — an agent working through several parts
    has to be told that one of them may be waiting on another, which is
    not a thing that happens inside a single wizard.
    """
    toolset = build_journey_toolset(task_list_viewset)
    return Agent(
        model,
        deps_type=WizardDeps,
        instructions=build_instructions(task_list_viewset, procedure=JOURNEY_PROCEDURE),
        toolsets=[wrap(toolset) if wrap else toolset],
    )
