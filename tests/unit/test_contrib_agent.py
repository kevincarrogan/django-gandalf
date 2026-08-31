"""`gandalf.contrib.agent`: the toolset, the prompt and the profile.

Skips without the `agent` extra, which is how everything else in this
package behaves when its dependency is absent.

The tools are closures over one viewset, so they are called directly with
a stand-in context rather than through a model. Driving them through a
scripted model would prove a model can be told to call a tool, which is
not in doubt; what is worth pinning is what each one does to the run.
"""

import json
import tempfile
import warnings
from dataclasses import dataclass
from typing import Any

import pytest

pytest.importorskip("pydantic_ai")

from django import forms  # noqa: E402
from django.http import HttpResponse  # noqa: E402
from django.test import override_settings  # noqa: E402
from pydantic_ai import ModelRetry  # noqa: E402

from gandalf.contrib.agent import (  # noqa: E402
    AgentProfile,
    Attachment,
    WizardDeps,
    WizardState,
    accepts_documents,
    build_agent,
    build_instructions,
    build_toolset,
    profile_for,
)
from gandalf.contrib.agent.prompt import DOCUMENTS, PROCEDURE, REGISTER  # noqa: E402
from gandalf.driver import RunDriver  # noqa: E402
from gandalf.viewsets import WizardViewSet  # noqa: E402
from gandalf.wizard import Wizard  # noqa: E402


class NameForm(forms.Form):
    name = forms.CharField()


class EmailForm(forms.Form):
    email = forms.EmailField()


class PhotoForm(forms.Form):
    photo = forms.FileField()


class _SignupViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(NameForm, name="name").step(EmailForm, name="email")
    agent = AgentProfile(purpose="signing up", notes="Say hello first.")

    def done(self, run):
        return HttpResponse(b"signed up")


class _BareViewSet(WizardViewSet):
    """No profile at all — the wizard that says nothing about itself."""

    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(NameForm, name="name")

    def done(self, run):
        return HttpResponse(b"done")


class _PhotoViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(PhotoForm, name="photo").step(NameForm, name="name")
    agent = AgentProfile(purpose="checking a document")

    def done(self, run):
        return HttpResponse(b"checked")


@dataclass
class _Ctx:
    """The minimum `RunContext` a tool reads."""

    deps: WizardDeps


def _ctx(**kwargs: Any) -> _Ctx:
    return _Ctx(deps=WizardDeps(state=WizardState(), **kwargs))


@pytest.fixture
def media_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            yield tmpdir


def _tools(viewset_class):
    toolset = build_toolset(viewset_class)
    return {name: tool.function for name, tool in toolset.tools.items()}


# --- the profile -------------------------------------------------------


def test_a_profile_is_read_off_the_viewset():
    assert profile_for(_SignupViewSet) == AgentProfile(
        purpose="signing up", notes="Say hello first."
    )


def test_a_wizard_with_no_profile_has_none():
    assert profile_for(_BareViewSet) is None


def test_something_that_is_not_a_profile_is_not_one():
    """`agent` is a plausible attribute name for something else entirely,
    so the type is checked rather than assumed."""

    class _Odd(WizardViewSet):
        agent = "a string"

    assert profile_for(_Odd) is None


# --- the prompt --------------------------------------------------------


def test_the_prompt_carries_the_purpose_and_the_notes():
    instructions = build_instructions(_SignupViewSet)

    assert "helping someone with signing up" in instructions
    assert "Say hello first." in instructions
    for part in (PROCEDURE, DOCUMENTS, REGISTER):
        assert part in instructions


def test_a_wizard_with_no_profile_still_gets_a_working_prompt():
    """Honest and useless in equal measure: enough to drive the thing,
    not enough to talk about it."""
    instructions = build_instructions(_BareViewSet)

    assert "helping someone with this application" in instructions
    assert PROCEDURE in instructions
    assert "About this one in particular" not in instructions


def test_a_profile_can_be_passed_for_a_wizard_that_carries_none():
    instructions = build_instructions(
        _BareViewSet, AgentProfile(purpose="something else")
    )

    assert "helping someone with something else" in instructions


def test_a_profile_without_notes_adds_no_note_member():
    instructions = build_instructions(_PhotoViewSet)

    assert "About this one in particular" not in instructions


# --- which tools exist -------------------------------------------------


def test_the_toolset_drives_a_run_and_hands_it_back():
    tools = _tools(_SignupViewSet)

    assert set(tools) == {
        "start_run",
        "resume_run",
        "get_run",
        "get_outline",
        "check_answers",
        "prefill",
        "submit_step",
        "edit_step",
    }


def test_a_wizard_with_addressable_urls_can_hand_the_run_back():
    """`handoff` is the only ending offered, and it needs somewhere to
    send them — a wizard with no `url_name` has no link to give."""
    from tests.testapp.views import WalkCountingWizardViewSet

    assert "handoff" in _tools(WalkCountingWizardViewSet)
    assert "handoff" not in _tools(_SignupViewSet)


def test_there_is_no_tool_that_concludes_a_run():
    """`done()` is where the irreversible things live. An agent that can
    reach them will eventually reach them on somebody's behalf."""
    assert "complete_run" not in _tools(_SignupViewSet)
    assert "finish" not in _tools(_SignupViewSet)


def test_a_wizard_with_a_file_step_gets_a_way_to_attach_one():
    assert "attach_document" in _tools(_PhotoViewSet)


def test_a_wizard_without_one_does_not():
    """A tool an agent cannot use is one it can only misuse."""
    assert "attach_document" not in _tools(_SignupViewSet)


def test_accepts_documents_is_derived_from_the_wizard():
    assert accepts_documents(_PhotoViewSet) is True
    assert accepts_documents(_SignupViewSet) is False


def test_accepts_documents_reads_the_format_and_not_the_prose():
    """The description is written for whoever reads it and may be
    reworded; the `format` is what a decision should turn on."""
    from gandalf.driver import RunDriver, outline_steps

    outline = RunDriver.outline_for(_PhotoViewSet)
    photo = next(
        prop
        for entry in outline_steps(outline)
        for prop in entry["schema"]["properties"].values()
        if prop.get("format") == "binary"
    )

    assert photo["type"] == "string"


def test_a_step_that_repeats_its_fields_is_not_mistaken_for_one_that_has_none():
    """`accepts_documents` walked `schema["properties"]` for every step. A
    formset describes itself as an array of rows and has no `properties`,
    so asking a wizard with one in it raised `KeyError` — and the raise came
    out of `build_toolset`, so the agent could not be built at all."""
    from tests.testapp.views import OpeningHoursWizardViewSet

    assert accepts_documents(OpeningHoursWizardViewSet) is False


def test_a_step_with_no_schema_yet_is_not_mistaken_for_one_with_no_fields():
    """A step whose view composes its form from answers the run has not got
    yet reports `schema: None` until the walk reaches it. That is not a
    step with no file field; it is a step nothing can say that about."""
    from tests.testapp.from_formtools.two_factor import SetupViewSet

    assert accepts_documents(SetupViewSet) is False


@pytest.mark.parametrize(
    "wizard",
    ["djangogirls", "squest", "two_factor"],
    ids=["a formset step", "a form composed from answers", "a consuming check"],
)
def test_an_agent_can_be_built_for_every_wizard_the_repo_ships(wizard):
    """The acceptance case: the three ported wizards are the real-world
    shapes, and until this none of them could be given an agent — the
    build raised before a tool existed."""
    from tests.testapp.from_formtools import djangogirls, squest, two_factor

    viewset = {
        "djangogirls": djangogirls.OrganiseAnEventViewSet,
        "squest": squest.RequestAServiceViewSet,
        "two_factor": two_factor.SetupViewSet,
    }[wizard]

    assert "get_run" in _tools(viewset)


# --- driving a run -----------------------------------------------------


def test_a_tool_called_before_a_run_exists_asks_for_one():
    tools = _tools(_SignupViewSet)

    with pytest.raises(ModelRetry, match="start_run"):
        tools["prefill"](_ctx(), {"name": {"name": "Ada"}})


def test_starting_a_run_describes_where_it_is():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()

    result = tools["start_run"](ctx)

    assert result.return_value["step"] == "name"
    assert result.return_value["complete"] is False
    assert ctx.deps.state.run_id is not None


def test_the_outline_is_answerable_before_a_run_exists():
    """Describing a wizard needs no run, and starting one to answer a
    question about the declaration would leave a run behind for every
    wizard anybody merely asked about."""
    tools = _tools(_SignupViewSet)
    ctx = _ctx()

    result = tools["get_outline"](ctx)

    assert [entry["step"] for entry in result.return_value["outline"]] == [
        "name",
        "email",
    ]
    assert ctx.deps.state.run_id is None


def test_the_outline_of_a_started_run_describes_the_run_too():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["get_outline"](ctx)

    assert result.return_value["step"] == "name"
    assert result.return_value["outline"]


def test_answers_can_be_checked_without_placing_any():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["check_answers"](ctx, {"name": {"name": "Ada"}})

    assert result.return_value["checked"]["ok"] == ["name"]
    assert result.return_value["answers"] == {}


def test_prefill_places_what_it_can():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["prefill"](
        ctx, {"name": {"name": "Ada"}, "email": {"email": "ada@example.com"}}
    )

    assert result.return_value["placed"] == ["name", "email"]
    assert result.return_value["complete"] is True


def test_prefill_explains_what_a_gap_parked():
    """Answers are placed in the wizard's own order, so a gap parks
    everything behind it. Saying so plainly stops the model concluding
    the person must be asked again."""
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["prefill"](ctx, {"email": {"email": "ada@example.com"}})

    assert result.return_value["unused"] == ["email"]
    assert "do not ask the person" in result.return_value["hint"]


def test_submitting_advances_the_run():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["submit_step"](ctx, {"name": "Ada"})

    assert result.return_value["status"] == "advanced"
    assert result.return_value["step"] == "email"


def test_a_rejected_answer_comes_back_as_a_retry_carrying_the_errors():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})

    with pytest.raises(ModelRetry) as raised:
        tools["submit_step"](ctx, {"email": "not-an-email"})

    assert "email" in json.loads(str(raised.value).split(": ", 1)[1])


def test_submitting_to_a_finished_run_says_to_hand_it_back():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["prefill"](
        ctx, {"name": {"name": "Ada"}, "email": {"email": "ada@example.com"}}
    )

    with pytest.raises(ModelRetry, match="hand off"):
        tools["submit_step"](ctx, {"name": "Grace"})


def test_an_earlier_answer_can_be_corrected():
    """Required rather than convenient: recovering from a rejected answer
    means replacing it."""
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})

    result = tools["edit_step"](ctx, "name", {"name": "Grace"})

    assert result.return_value["answers"]["name"] == {"name": "Grace"}


def test_a_run_holding_rows_is_reported_to_the_browser_without_complaint():
    """`WizardState.answers` said every step answers with a mapping. A
    formset answers with rows, and the state is a pydantic model that both
    refuses them on construction and warns on every serialisation of one —
    and it is serialised into the AG-UI stream on every tool call.

    The warning is the assertion because the value survived: nothing failed
    loudly, the type was simply not true, which is the failure that
    outlives everybody who knew about it.
    """
    from tests.testapp.views import OpeningHoursWizardViewSet

    tools = _tools(OpeningHoursWizardViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = tools["submit_step"](ctx, [{"day": "Monday", "opens": "09:00"}])

    assert result.return_value["answers"]["opening-hours"] == [
        {"day": "Monday", "opens": "09:00"}
    ]
    rebuilt = WizardState(answers=ctx.deps.state.answers)
    assert rebuilt.answers["opening-hours"] == [{"day": "Monday", "opens": "09:00"}]


def test_editing_a_step_that_answered_with_rows_replaces_them():
    """`edit_step` merges what it is given over what is stored, which reads
    as `{**stored, **data}` — and a formset's stored answer is a list, so
    the merge raised. Rows are replaced wholesale rather than merged: there
    is no field to merge *onto* when the answer is n of them."""
    from tests.testapp.views import OpeningHoursWizardViewSet

    tools = _tools(OpeningHoursWizardViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})
    tools["submit_step"](ctx, [{"day": "Monday", "opens": "09:00"}])

    result = tools["edit_step"](
        ctx, "opening-hours", [{"day": "Tuesday", "opens": "10:00"}]
    )

    assert result.return_value["answers"]["opening-hours"] == [
        {"day": "Tuesday", "opens": "10:00"}
    ]


def test_editing_a_step_the_run_cannot_reach_is_a_retry():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    with pytest.raises(ModelRetry, match="cannot reach"):
        tools["edit_step"](ctx, "nope", {"name": "Grace"})


def test_an_edit_that_fails_validation_is_a_retry():
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})
    tools["submit_step"](ctx, {"email": "ada@example.com"})

    with pytest.raises(ModelRetry, match="fix these fields"):
        tools["edit_step"](ctx, "email", {"email": "nope"})


def test_every_tool_returns_where_the_run_now_is():
    """There is no `get_current_step`, because every tool that moves the
    run says where it left it — a separate reader would be a round trip
    for something the caller was just handed."""
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["submit_step"](ctx, {"name": "Ada"})

    assert result.return_value["answers"] == {"name": {"name": "Ada"}}
    assert result.return_value["step"] == "email"


# --- attaching a document ----------------------------------------------


def _with_attachment(**kwargs):
    return _ctx(
        attachments={
            "attachment-1": Attachment(
                id="attachment-1",
                name="proof.png",
                media_type="image/png",
                data=b"bytes",
                **kwargs,
            )
        }
    )


def test_a_document_from_the_conversation_can_be_placed(media_root):
    tools = _tools(_PhotoViewSet)
    ctx = _with_attachment()
    tools["start_run"](ctx)

    result = tools["attach_document"](ctx, "attachment-1", "photo")

    assert result.return_value["status"] == "advanced"
    assert result.return_value["attached"] == "proof.png"


def test_a_handle_that_names_nothing_says_which_ones_are_real():
    """The model may have invented one, so the retry lists what exists."""
    tools = _tools(_PhotoViewSet)
    ctx = _with_attachment()
    tools["start_run"](ctx)

    with pytest.raises(ModelRetry, match="attachment-1"):
        tools["attach_document"](ctx, "attachment-9", "photo")


def test_attaching_to_a_step_the_run_cannot_reach_is_a_retry(media_root):
    tools = _tools(_PhotoViewSet)
    ctx = _with_attachment()
    tools["start_run"](ctx)

    with pytest.raises(ModelRetry, match="cannot reach"):
        tools["attach_document"](ctx, "attachment-1", "photo", "nope")


# --- the agent ---------------------------------------------------------


def test_an_agent_is_built_without_naming_a_provider():
    """`build_agent` takes whatever pydantic-ai takes, and nothing here
    has an opinion about who serves the model — pinned with the canned
    `test` model, which needs no provider at all."""
    agent = build_agent(_SignupViewSet, "test")

    assert agent is not None


def test_the_toolset_can_be_wrapped_on_the_way_in():
    """The hook a caller needs to see every tool call go past."""
    seen = []

    def wrap(toolset):
        seen.append(sorted(toolset.tools))
        return toolset

    build_agent(_SignupViewSet, "test", wrap=wrap)

    assert "start_run" in seen[0]


# --- files in the conversation -----------------------------------------


def _message(*parts):
    from ag_ui.core import UserMessage

    return UserMessage(id="m1", role="user", content=list(parts))


def _image(data=b"bytes"):
    from base64 import b64encode

    from ag_ui.core import ImageInputContent, InputContentDataSource

    return ImageInputContent(
        type="image",
        source=InputContentDataSource(
            type="data", value=b64encode(data).decode(), mime_type="image/png"
        ),
    )


def test_a_file_in_the_conversation_becomes_an_addressable_attachment():
    """The handle the model is told to use, and the bytes it never sees."""
    from gandalf.contrib.agent import attachments_from

    attachments = attachments_from([_message(_image())])

    assert list(attachments) == ["attachment-1"]
    assert attachments["attachment-1"].data == b"bytes"
    assert attachments["attachment-1"].media_type == "image/png"


def test_the_deprecated_binary_part_is_still_understood():
    """`BinaryInputContent` is the older spelling and warns, but a client
    that has not moved on yet still gets its file placed."""
    from base64 import b64encode

    from ag_ui.core import BinaryInputContent

    from gandalf.contrib.agent import attachments_from

    with pytest.warns(DeprecationWarning):
        part = BinaryInputContent(
            type="binary",
            mime_type="image/png",
            data=b64encode(b"bytes").decode(),
            filename="proof.png",
        )

    attachment = attachments_from([_message(part)])["attachment-1"]

    assert attachment.data == b"bytes"
    assert attachment.name == "proof.png"


def test_a_binary_part_with_no_data_is_skipped():
    from ag_ui.core import BinaryInputContent

    from gandalf.contrib.agent import attachments_from

    with pytest.warns(DeprecationWarning):
        part = BinaryInputContent(
            type="binary", mime_type="image/png", url="https://example.com/x.png"
        )

    assert attachments_from([_message(part)]) == {}


def test_a_part_referencing_a_url_is_skipped():
    """Placing one means fetching whatever it points at, which is a
    different capability with a different argument attached to it."""
    from ag_ui.core import ImageInputContent, InputContentUrlSource

    from gandalf.contrib.agent import attachments_from

    part = ImageInputContent(
        type="image",
        source=InputContentUrlSource(
            type="url", value="https://example.com/x.png", mime_type="image/png"
        ),
    )

    assert attachments_from([_message(part)]) == {}


def test_text_parts_and_text_only_messages_carry_nothing():
    from ag_ui.core import TextInputContent, UserMessage

    from gandalf.contrib.agent import attachments_from

    messages = [
        UserMessage(id="m1", role="user", content="hello"),
        _message(TextInputContent(type="text", text="hello")),
        UserMessage(id="m2", role="user", content=[]),
    ]

    assert attachments_from(messages) == {}


def test_messages_that_are_not_the_persons_are_not_read():
    """An assistant turn can carry content too, and nothing it produced
    is a document somebody handed over."""
    from ag_ui.core import AssistantMessage

    from gandalf.contrib.agent import attachments_from

    assert attachments_from([AssistantMessage(id="a1", role="assistant")]) == {}


class _RejectingPhotoForm(forms.Form):
    photo = forms.FileField()

    def clean_photo(self):
        raise forms.ValidationError("Not a licence.")


class _RejectingViewSet(WizardViewSet):
    template_name = "testapp/linear_wizard.html"
    wizard = Wizard().step(_RejectingPhotoForm, name="photo")

    def done(self, run):
        return HttpResponse(b"done")


def test_a_document_the_form_refuses_comes_back_as_a_retry(media_root):
    """The one translation this toolset makes: a validation error becomes
    something the model can act on inside its own retry budget."""
    tools = _tools(_RejectingViewSet)
    ctx = _with_attachment()
    tools["start_run"](ctx)

    with pytest.raises(ModelRetry, match="not accepted"):
        tools["attach_document"](ctx, "attachment-1", "photo")


def test_handing_back_returns_the_persons_own_link():
    """The only ending this toolset offers."""
    from tests.testapp.views import WalkCountingWizardViewSet

    tools = _tools(WalkCountingWizardViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)

    result = tools["handoff"](ctx)

    assert "/walk-counting-wizard/" in result.return_value["handoff_url"]
    assert ctx.deps.state.handoff_url == result.return_value["handoff_url"]


def test_handing_back_lands_on_whatever_the_run_is_waiting_for():
    """Somebody who asks to take over half way through wants the step
    they are on, not the beginning and not the end.

    Asking the run rather than naming a step also stops this assuming
    every wizard has one called "confirm" — which was true of the demo it
    was written against and of nothing else.
    """
    from tests.testapp.views import WalkCountingWizardViewSet

    tools = _tools(WalkCountingWizardViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})

    result = tools["handoff"](ctx)

    assert result.return_value["handoff_url"].endswith("/second/")


def test_handing_back_works_for_a_wizard_with_no_step_called_confirm():
    """The `_SignupViewSet` here ends on `second`. A hardcoded step name
    would have returned a link to a page that does not exist."""
    from gandalf.contrib.agent import build_toolset

    class _Named(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        url_name = "walk-counting-wizard"
        wizard = Wizard().step(NameForm, name="first")

        def done(self, run):
            return HttpResponse(b"done")

    tools = {n: t.function for n, t in build_toolset(_Named).tools.items()}
    ctx = _ctx()
    tools["start_run"](ctx)

    assert tools["handoff"](ctx).return_value["handoff_url"].endswith("/first/")


def test_the_agent_is_told_it_may_hand_back_at_any_point():
    """Somebody who asks for their own form should get it. The procedure
    otherwise reads as though the link is a reward for finishing."""
    instructions = build_instructions(_SignupViewSet)

    assert "take over" in instructions
    assert "carry on later" in instructions


# --- looking at a run somebody else has touched ------------------------


def test_the_run_can_be_read_without_changing_it():
    """Every other tool that shows the run also moves it. Somebody asking
    "what does my form say now" should not have to submit something to
    find out."""
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})

    before = tools["get_run"](ctx).return_value
    after = tools["get_run"](ctx).return_value

    assert before == after
    assert before["step"] == "email"
    assert before["answers"] == {"name": {"name": "Ada"}}


def test_a_change_made_outside_the_agent_is_seen_when_it_looks_again():
    """The whole point of the handover working in both directions.

    The person opens the form and changes an answer while the chat is
    still open. The agent's memory of the run is now wrong, and the only
    thing that fixes that is looking.
    """
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})

    # Their turn, through the same door a browser uses: a different
    # driver, on the same run, recorded as theirs.
    theirs = RunDriver.resume(
        _SignupViewSet, ctx.deps.state.run_id, context=ctx.deps.context
    )
    theirs.submit({"name": "Grace"}, step="name", metadata={})

    seen = tools["get_run"](ctx).return_value

    assert seen["answers"]["name"] == {"name": "Grace"}
    assert ctx.deps.state.answers["name"] == {"name": "Grace"}


def test_the_agent_is_told_the_form_may_have_moved_under_it():
    instructions = build_instructions(_SignupViewSet)

    assert "filling it in themselves while you are talking" in instructions


# --- driving a whole application ---------------------------------------


def _journey_tools(task_list_viewset):
    from gandalf.contrib.agent import build_journey_toolset

    toolset = build_journey_toolset(task_list_viewset)
    return {name: tool.function for name, tool in toolset.tools.items()}


def _application():
    from django.contrib.sessions.backends.cache import SessionStore

    from gandalf.context import WizardContext
    from tests.testapp.views import SubmitViewSet

    tools = _journey_tools(SubmitViewSet)
    ctx = _ctx(context=WizardContext(session=SessionStore()))
    tools["start_application"](ctx)
    return tools, ctx


def test_the_journey_toolset_reads_a_page_and_fills_its_parts():
    from tests.testapp.views import SubmitViewSet

    assert set(_journey_tools(SubmitViewSet)) == {
        "start_application",
        "resume_application",
        "get_application",
        "get_part",
        "check_part",
        "fill_part",
        "add_to_list",
        "remove_from_list",
        "handoff",
    }


def test_there_is_no_tool_that_submits_an_application():
    """`journey_done()` is the task list's `done()`, and the same rule
    holds one level up: an agent that can reach it will eventually reach it
    on somebody's behalf."""
    from tests.testapp.views import SubmitViewSet

    tools = _journey_tools(SubmitViewSet)

    assert "submit_application" not in tools
    assert "submit" not in tools


def test_starting_one_describes_every_part_of_it():
    tools, ctx = _application()

    result = tools["get_application"](ctx)

    assert [row["key"] for row in result.return_value["rows"]] == ["first", "second"]
    assert result.return_value["complete"] is False


def test_a_part_is_filled_by_naming_it():
    """Every tool takes the part it is about, so there is no current
    section to fall out of step with what the person has been doing in the
    browser meanwhile."""
    tools, ctx = _application()

    result = tools["fill_part"](ctx, "first", {"first": {"name": "Ada"}})

    assert result.return_value["part"]["placed"] == ["first"]
    assert result.return_value["part"]["waiting_on"] is None


def test_a_filled_part_is_not_a_finished_one():
    """The handover, one level up. Filling a part answers it; *ending* it
    fires that section's own `done()`, and there is no tool that does —
    the person confirms each part and submits the application, exactly as
    they confirm a run the agent filled.

    So a part an agent has filled reads as Incomplete until they say so.
    That is the row telling the truth, not the fill having failed.
    """
    tools, ctx = _application()

    result = tools["fill_part"](ctx, "first", {"first": {"name": "Ada"}})

    assert result.return_value["rows"][0]["status"] == "incomplete"
    assert result.return_value["complete"] is False


def test_a_part_can_be_tried_before_it_is_filled():
    tools, ctx = _application()

    result = tools["check_part"](ctx, "first", {"first": {"name": "Ada"}})

    assert result.return_value["ok"] == ["first"]


def test_a_part_that_refuses_an_answer_is_a_retry():
    tools, ctx = _application()

    with pytest.raises(ModelRetry, match="not accepted"):
        tools["fill_part"](ctx, "first", {"first": {"name": ""}})


def test_a_part_the_application_does_not_have_is_a_retry_that_lists_them():
    """A model inventing a name gets told which ones are real, rather than
    an exception through the framework."""
    tools, ctx = _application()

    with pytest.raises(ModelRetry, match="first, second"):
        tools["get_part"](ctx, "nope")


def test_a_tool_called_before_an_application_exists_asks_for_one():
    from tests.testapp.views import SubmitViewSet

    tools = _journey_tools(SubmitViewSet)

    with pytest.raises(ModelRetry, match="resume_application"):
        tools["get_application"](_ctx())


def test_handing_the_application_back_gives_them_its_page():
    tools, ctx = _application()

    result = tools["handoff"](ctx)

    assert result.return_value["handoff_url"] == ctx.deps.state.journey_url
    assert ctx.deps.state.handoff_url == result.return_value["url"]


def test_an_application_can_be_picked_back_up_by_its_id():
    tools, ctx = _application()
    tools["fill_part"](ctx, "first", {"first": {"name": "Ada"}})
    journey_id = ctx.deps.state.journey_id

    again = _ctx(context=ctx.deps.context)
    result = tools["resume_application"](again, journey_id)

    assert result.return_value["rows"][0]["status"] == "incomplete"


# --- a list that grows, one level up -----------------------------------


def _party():
    from django.contrib.sessions.backends.cache import SessionStore

    from gandalf.context import WizardContext
    from tests.testapp.views import PartyViewSet

    tools = _journey_tools(PartyViewSet)
    ctx = _ctx(context=WizardContext(session=SessionStore()))
    tools["start_application"](ctx)
    return tools, ctx


def test_one_call_puts_one_thing_on_a_list():
    tools, ctx = _party()

    result = tools["add_to_list"](ctx, "guests", {"guest": {"name": "Ada"}})

    assert result.return_value["part"]["key"] == "guests"
    assert result.return_value["rows"][1]["status"] == "incomplete"


def test_a_thing_that_does_not_validate_leaves_nothing_behind():
    """Registered but empty reads on their page as a half-added guest.
    Taking it back off is what makes the retry safe to act on."""
    tools, ctx = _party()

    with pytest.raises(ModelRetry, match="nothing was added"):
        tools["add_to_list"](ctx, "guests", {"guest": {"name": ""}})

    assert tools["get_application"](ctx).return_value["rows"][1]["status"] == (
        "not-started"
    )


def test_a_thing_can_be_taken_back_off():
    from gandalf.driver import JourneyDriver
    from tests.testapp.views import PartyViewSet

    tools, ctx = _party()
    tools["add_to_list"](ctx, "guests", {"guest": {"name": "Ada"}})
    journey = JourneyDriver.resume(
        PartyViewSet, ctx.deps.state.journey_id, context=ctx.deps.context
    )
    (item_id,) = [row.item_id for row in journey.items("guests").rows]

    tools["remove_from_list"](ctx, "guests", item_id)

    assert journey.items("guests").rows == ()


def test_a_part_that_cannot_be_opened_yet_is_a_retry():
    """The page's door, reached through a journey tool: the same three
    answers in the same words, one level up."""
    from django.contrib.sessions.backends.cache import SessionStore

    from gandalf.context import WizardContext
    from tests.testapp.views import GatedViewSet

    tools = _journey_tools(GatedViewSet)
    ctx = _ctx(context=WizardContext(session=SessionStore()))
    tools["start_application"](ctx)

    with pytest.raises(ModelRetry, match="finished first"):
        tools["get_part"](ctx, "second")


def test_removing_from_something_that_is_not_a_list_is_a_retry():
    tools, ctx = _party()

    with pytest.raises(ModelRetry, match="not a list"):
        tools["remove_from_list"](ctx, "venue", "whatever")


def test_a_part_that_is_not_a_list_is_a_retry():
    tools, ctx = _party()

    with pytest.raises(ModelRetry, match="not a list"):
        tools["add_to_list"](ctx, "venue", {})


def test_a_journey_agent_is_told_it_may_be_waiting_on_a_part():
    """The one thing a journey's procedure has to say that a wizard's does
    not: a part can be waiting on another, and the way past that is to do
    the other one rather than to report it as unavailable."""
    from gandalf.contrib.agent import build_journey_agent
    from gandalf.contrib.agent.prompt import JOURNEY_PROCEDURE
    from tests.testapp.views import SubmitViewSet

    agent = build_journey_agent(SubmitViewSet, "test")

    (instructions,) = agent._instructions
    assert JOURNEY_PROCEDURE in instructions
    assert "waiting on another one" in JOURNEY_PROCEDURE


# --- a door that will not open -----------------------------------------


def _gated_ctx():
    from django.contrib.sessions.backends.cache import SessionStore

    from gandalf.context import WizardContext

    return _ctx(context=WizardContext(session=SessionStore()))


def test_a_section_that_cannot_be_started_yet_is_a_retry():
    """A refusal reaches the model as words about the application rather
    than as an exception through the framework — and as words that say what
    would have to change, so it does not simply try the same thing again."""
    from tests.testapp.views import GatedViewSet

    tools = _tools(GatedViewSet.viewset_for("second"))

    with pytest.raises(ModelRetry, match="finished first"):
        tools["start_run"](_gated_ctx())


def test_a_submitted_journey_is_a_retry_that_says_to_stop():
    """The one refusal with no way round it. Everything on the journey is
    finished, so there is nothing for the agent to do but say so."""
    from gandalf.context import WizardContext
    from django.contrib.sessions.backends.cache import SessionStore

    from tests.testapp.readme.ch12_task_list import GrantApplicationViewSet

    session = SessionStore()
    context = WizardContext(session=session)
    page = GrantApplicationViewSet()
    page.setup(context.http_request())
    page.get_journey_store().complete()

    tools = _tools(GrantApplicationViewSet.viewset_for("contact"))

    with pytest.raises(ModelRetry, match="already been submitted"):
        tools["start_run"](_ctx(context=context))


def test_a_run_whose_door_has_since_closed_cannot_be_picked_back_up():
    """A section open when the run started can be shut afterwards — its
    prerequisite withdrawn, the journey submitted. The run is refused at
    the door rather than resumed, before it is even retrieved, which is
    what a browser coming back to the same section gets."""
    from gandalf.context import WizardContext
    from django.contrib.sessions.backends.cache import SessionStore

    from tests.testapp.readme.ch12_task_list import GrantApplicationViewSet

    session = SessionStore()
    context = WizardContext(session=session)
    tools = _tools(GrantApplicationViewSet.viewset_for("contact"))
    ctx = _ctx(context=context)
    run_id = tools["start_run"](ctx).return_value["run_id"]

    page = GrantApplicationViewSet()
    page.setup(context.http_request())
    page.get_journey_store().complete()

    with pytest.raises(ModelRetry, match="already been submitted"):
        tools["resume_run"](_ctx(context=context), run_id)


# --- picking a run back up ---------------------------------------------


def test_a_run_can_be_resumed_by_its_id():
    """The recovery that was missing. A run id comes back on every tool
    call, so it is somewhere in the conversation even after the client's
    state has lost it — and picking it up is the difference between
    carrying on and quietly abandoning somebody's half-filled form.
    """
    tools = _tools(_SignupViewSet)
    ctx = _ctx()
    tools["start_run"](ctx)
    tools["submit_step"](ctx, {"name": "Ada"})
    run_id = ctx.deps.state.run_id

    # A new turn whose state did not survive: same session, no run id.
    later = _Ctx(deps=WizardDeps(state=WizardState(), context=ctx.deps.context))

    resumed = tools["resume_run"](later, run_id).return_value

    assert resumed["run_id"] == run_id
    assert resumed["answers"] == {"name": {"name": "Ada"}}
    assert later.deps.state.run_id == run_id


def test_resuming_a_run_that_does_not_exist_says_so():
    """A model that has misread an id should be told, not handed an
    exception it cannot act on."""
    tools = _tools(_SignupViewSet)

    with pytest.raises(ModelRetry, match="no run with the id"):
        tools["resume_run"](_ctx(), "3f2504e0-4f89-11d3-9a0c-0305e82c3301")


def test_the_no_run_message_offers_resuming_before_starting():
    """What the agent is told when it has no run is what it will do. Told
    only to start one, it starts one — which is what happened, and what
    lost somebody's answers.
    """
    tools = _tools(_SignupViewSet)

    with pytest.raises(ModelRetry) as raised:
        tools["get_run"](_ctx())

    message = str(raised.value)
    assert "resume_run" in message
    assert "abandons whatever is already filled in" in message
