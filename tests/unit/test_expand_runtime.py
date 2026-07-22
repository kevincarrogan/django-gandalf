"""Unit coverage for `.expand()` at the `BoundWizard` / walker level.

The functional suite drives expansions over HTTP; these exercise the same
runtime pieces directly — the sealed passthrough, the path and merge folds
over an expanded region, and the build-time vetting — so each suite stands
alone at full coverage.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from gandalf import tree
from gandalf.runtime import (
    BoundWizard,
    MergeCleanedData,
    PreservedExpand,
    RuntimeExpand,
)
from gandalf.storage import SessionStorage
from gandalf.wizard import Wizard, condition

from tests.testapp.forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    ItemCountForm,
    ItemForm,
    PersonalDetailsForm,
    ReviewForm,
)


class _Session(dict):
    modified = False


@pytest.fixture
def request_factory(rf):
    def build(session=None):
        request = rf.get("/wizard/")
        request.session = _Session()
        if session:
            request.session.update(session)
        return request

    return build


def _build_items(request):
    count = int(request.wizard.find_step(name="count").form.cleaned_data["count"])
    steps = Wizard()
    for index in range(count):
        steps = steps.step(ItemForm, name=f"item-{index}")
    return steps


def _expand_wizard(builder=_build_items):
    return (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(builder)
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )


def _bound(wizard, request, state):
    request.session["gandalf_runs"] = {"run": {"state": state}}
    bound = BoundWizard(request, SessionStorage(request), wizard=wizard)
    bound.retrieve("run")
    return bound


def test_expand_builds_the_subtree_from_a_prior_answer(request_factory):
    bound = _bound(_expand_wizard(), request_factory(), [{"step": {"count": "2"}}])

    walk = bound.walk()

    # The count is answered, so the expansion built two item steps; the walk
    # parks on the first of them, which is a step that did not exist in the
    # declared tree at all.
    assert walk.cursor.node.context["step_name"] == "item-0"


def test_expanded_answers_serialise_as_a_positional_list(request_factory):
    bound = _bound(
        _expand_wizard(),
        request_factory(),
        [
            {"step": {"count": "2"}},
            {"expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]},
        ],
    )

    walk = bound.walk()

    assert walk.cursor.node.context["step_name"] == "review"
    node = walk.cursor.state.next
    assert isinstance(node, RuntimeExpand)
    assert bound.wizard.state_serializer_class().reduce(walk.cursor.state) == [
        {"step": {"count": "2"}},
        {"expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]},
    ]


def test_an_expansion_before_the_cursor_is_preserved_verbatim(request_factory):
    """With the count itself unanswered the walk seals at it, so the stored
    expansion rides through as an opaque `PreservedExpand` rather than being
    rebuilt against an answer that is not there yet."""
    stored = [
        {"step": None},
        {"expand": [{"step": {"name": "Ada"}}]},
    ]
    bound = _bound(_expand_wizard(), request_factory(), stored)

    walk = bound.walk()

    assert walk.cursor.node.context["step_name"] == "count"
    preserved = walk.cursor.state.next
    assert isinstance(preserved, PreservedExpand)
    # Serializing keeps the sealed region exactly as stored.
    serialized = bound.wizard.state_serializer_class().reduce(walk.cursor.state)
    assert serialized == stored


def test_path_skips_a_preserved_expansion(request_factory):
    bound = _bound(
        _expand_wizard(),
        request_factory(),
        [{"step": None}, {"expand": [{"step": {"name": "Ada"}}]}],
    )

    # `path` flattens the active route; a sealed expansion is opaque, so it
    # contributes nothing and the path is empty before the unanswered count.
    assert bound.path is None


def test_merge_cleaned_data_folds_over_an_expansion(request_factory):
    bound = _bound(
        _expand_wizard(),
        request_factory(),
        [
            {"step": {"count": "2"}},
            {"expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]},
        ],
    )

    # Reduced over the runtime tree (which keeps the RuntimeExpand structure,
    # where `path` would flatten it away), the fold descends the expansion.
    merged = MergeCleanedData().reduce(bound.runtime_tree)

    assert merged["count"] == 2
    assert merged["name"] == "Grace"  # last-write-wins across the two items


def test_path_inlines_an_active_expansion(request_factory):
    bound = _bound(
        _expand_wizard(),
        request_factory(),
        [
            {"step": {"count": "2"}},
            {"expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]},
        ],
    )

    names = []
    node = bound.path
    while node is not None:
        names.append(node.declaration.context.get("step_name"))
        node = node.next

    # The expanded item steps are spliced into the active route inline,
    # between the count and wherever the run has reached.
    assert names[:3] == ["count", "item-0", "item-1"]


def test_a_submission_can_be_placed_into_an_expanded_step(request_factory):
    bound = _bound(_expand_wizard(), request_factory(), [{"step": {"count": "2"}}])

    walk = bound.walk(claim={"step_name": "item-0"}, submission={"name": "Grace"})

    # The claim reaches a step that only exists inside the expansion — the
    # cursor of the sub-walk — so the placement is carried back out of the
    # expansion and surfaced as the walk's target.
    assert walk.reached is True
    assert walk.target.data == {"name": "Grace"}


def test_a_wizard_can_carry_steps_after_an_expansion():
    wizard = (
        Wizard()
        .step(ItemCountForm, name="count")
        .expand(_build_items)
        .step(ReviewForm, name="review")
        .step(AccountTypeForm, name="account")
    )

    # Iterating the declared chain reaches the steps after the expansion,
    # which means the Expand node was threaded through the chain correctly.
    names = [
        node.context.get("step_name")
        for node in tree.iter_nodes(wizard.tree)
        if isinstance(node, tree.Step)
    ]
    assert names == ["count", "review", "account"]


def test_an_expansion_may_contain_a_branch():
    """A branch inside an expansion is fine — only expand-within-expand is
    barred — so configuring such a subtree walks its arms without complaint."""
    built = Wizard().branch(
        condition(lambda r: True, Wizard().step(BusinessDetailsForm, name="biz")),
        default=Wizard().step(PersonalDetailsForm, name="pers"),
    )

    subtree = _expand_wizard().configure_expansion(built)

    assert any(isinstance(node, tree.Branch) for node in tree.iter_nodes(subtree))


def test_unroutable_expanded_step_is_rejected_at_build_time():
    wizard = _expand_wizard()

    with pytest.raises(ImproperlyConfigured, match="routable name"):
        wizard.configure_expansion(Wizard().step(ItemForm))


def test_expansion_within_expansion_is_rejected_at_build_time():
    wizard = _expand_wizard()
    nested = Wizard().step(ItemForm, name="outer").expand(_build_items)

    with pytest.raises(ImproperlyConfigured, match="cannot contain another expansion"):
        wizard.configure_expansion(nested)
