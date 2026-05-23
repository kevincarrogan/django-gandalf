import dataclasses

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.views.generic.edit import FormView

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


def test_step_configure_generates_form_view_for_form_class():
    step = tree.Step(FirstStepForm)

    configured = step.configure(template_name="testapp/linear_wizard.html")

    assert configured.declaration is FirstStepForm
    assert issubclass(configured.form_view, FormView)
    assert configured.form_view.form_class is FirstStepForm
    assert configured.form_view.template_name == "testapp/linear_wizard.html"


def test_step_configure_uses_explicit_form_view_unchanged():
    class ExplicitView(FormView):
        form_class = FirstStepForm
        template_name = "testapp/explicit.html"

    step = tree.Step(ExplicitView)

    configured = step.configure(template_name="testapp/linear_wizard.html")

    assert configured.form_view is ExplicitView


def test_step_configure_requires_template_name_for_form_class():
    step = tree.Step(FirstStepForm)

    with pytest.raises(
        ImproperlyConfigured,
        match="Wizard.configure\\(\\) must receive template_name",
    ):
        step.configure(template_name=None)


def test_step_configure_recurses_through_next():
    step = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))

    configured = step.configure(template_name="testapp/linear_wizard.html")

    assert configured.form_view.form_class is FirstStepForm
    assert configured.next.form_view.form_class is SecondStepForm


def test_branch_configure_recurses_into_arm_subtrees():
    branch = tree.Branch(
        arms=((_is_business, tree.Step(FirstStepForm)),),
    )

    configured = branch.configure(template_name="testapp/linear_wizard.html")

    arm_subtree = configured.arms[0][1]
    assert arm_subtree.form_view.form_class is FirstStepForm
    assert arm_subtree.form_view.template_name == "testapp/linear_wizard.html"


def test_branch_configure_recurses_into_default():
    branch = tree.Branch(
        arms=((_is_business, tree.Step(FirstStepForm)),),
        default=tree.Step(SecondStepForm),
    )

    configured = branch.configure(template_name="testapp/linear_wizard.html")

    assert configured.default.form_view.form_class is SecondStepForm


def test_branch_configure_recurses_into_next():
    branch = tree.Branch(
        arms=((_is_business, tree.Step(FirstStepForm)),),
        next=tree.Step(SecondStepForm),
    )

    configured = branch.configure(template_name="testapp/linear_wizard.html")

    assert configured.next.form_view.form_class is SecondStepForm


def test_branch_configure_preserves_predicates():
    branch = tree.Branch(
        arms=((_is_business, tree.Step(FirstStepForm)),),
    )

    configured = branch.configure(template_name="testapp/linear_wizard.html")

    assert configured.arms[0][0] is _is_business
