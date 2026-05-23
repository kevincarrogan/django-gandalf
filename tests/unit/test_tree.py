import dataclasses

import pytest

from gandalf import tree
from tests.testapp.forms import FirstStepForm, SecondStepForm


def _is_business(submissions):
    return True


def _is_personal(submissions):
    return True


def test_single_step_repr():
    node = tree.Step(FirstStepForm)

    assert repr(node) == "- Step(FirstStepForm)"


def test_step_chain_repr():
    node = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))

    assert repr(node) == ("- Step(FirstStepForm)\n- Step(SecondStepForm)")


def test_branch_with_arm_and_default_repr():
    node = tree.Branch(
        arms=((_is_business, tree.Step(FirstStepForm)),),
        default=tree.Step(SecondStepForm),
    )

    assert repr(node) == (
        "- Branch\n"
        "  if _is_business:\n"
        "    - Step(FirstStepForm)\n"
        "  default:\n"
        "    - Step(SecondStepForm)"
    )


def test_branch_continues_to_next_after_arms():
    node = tree.Branch(
        arms=((_is_business, tree.Step(FirstStepForm)),),
        next=tree.Step(SecondStepForm),
    )

    assert repr(node) == (
        "- Branch\n"
        "  if _is_business:\n"
        "    - Step(FirstStepForm)\n"
        "- Step(SecondStepForm)"
    )


def test_nested_branch_repr():
    inner = tree.Branch(
        arms=((_is_personal, tree.Step(SecondStepForm)),),
    )
    node = tree.Branch(
        arms=((_is_business, inner),),
        default=tree.Step(FirstStepForm),
    )

    assert repr(node) == (
        "- Branch\n"
        "  if _is_business:\n"
        "    - Branch\n"
        "      if _is_personal:\n"
        "        - Step(SecondStepForm)\n"
        "  default:\n"
        "    - Step(FirstStepForm)"
    )


def test_step_is_frozen():
    step = tree.Step(FirstStepForm)

    with pytest.raises(dataclasses.FrozenInstanceError):
        step.declaration = SecondStepForm


def test_branch_is_frozen():
    branch = tree.Branch(arms=((_is_business, tree.Step(FirstStepForm)),))

    with pytest.raises(dataclasses.FrozenInstanceError):
        branch.default = tree.Step(FirstStepForm)


def test_build_returns_none_for_empty_declarations():
    assert tree.build([]) is None


def test_build_single_step():
    result = tree.build([tree.Step(FirstStepForm)])

    assert result == tree.Step(FirstStepForm)


def test_build_threads_next_across_step_chain():
    result = tree.build(
        [
            tree.Step(FirstStepForm),
            tree.Step(SecondStepForm),
        ]
    )

    assert result == tree.Step(
        FirstStepForm,
        next=tree.Step(SecondStepForm),
    )


def test_build_threads_next_across_branch():
    inner = tree.Step(SecondStepForm)

    result = tree.build(
        [
            tree.Step(FirstStepForm),
            tree.Branch(arms=((_is_business, inner),)),
            tree.Step(FirstStepForm),
        ]
    )

    assert result == tree.Step(
        FirstStepForm,
        next=tree.Branch(
            arms=((_is_business, inner),),
            next=tree.Step(FirstStepForm),
        ),
    )


def test_build_does_not_touch_subtree_next_pointers():
    inner = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))

    result = tree.build([tree.Branch(arms=((_is_business, inner),))])

    assert result.arms[0][1] is inner


def test_build_overwrites_existing_next_on_declarations():
    result = tree.build(
        [
            tree.Step(FirstStepForm, next=tree.Step(SecondStepForm)),
            tree.Step(SecondStepForm),
        ]
    )

    assert result == tree.Step(
        FirstStepForm,
        next=tree.Step(SecondStepForm),
    )
