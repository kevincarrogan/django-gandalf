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


def test_nodes_are_frozen():
    import dataclasses

    step = tree.Step(FirstStepForm)
    branch = tree.Branch(arms=((_is_business, tree.Step(FirstStepForm)),))

    try:
        step.declaration = SecondStepForm
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Step should be frozen")

    try:
        branch.default = tree.Step(FirstStepForm)
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Branch should be frozen")
