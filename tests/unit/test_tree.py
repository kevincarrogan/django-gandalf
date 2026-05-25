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


def test_step_iter_yields_chain():
    node = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))

    assert list(node) == [
        tree.Step(FirstStepForm, next=tree.Step(SecondStepForm)),
        tree.Step(SecondStepForm),
    ]


def test_branch_iter_yields_branch_then_next():
    inner = tree.Step(FirstStepForm)
    node = tree.Branch(
        arms=((_is_business, inner),),
        next=tree.Step(SecondStepForm),
    )

    walked = list(node)

    assert walked[0] is node
    assert walked[1] == tree.Step(SecondStepForm)


def test_branch_iter_yields_only_self_when_next_is_none():
    node = tree.Branch(arms=((_is_business, tree.Step(FirstStepForm)),))

    assert list(node) == [node]


def test_step_matches_context_returns_true_when_all_kwargs_match():
    step = tree.Step(FirstStepForm, context={"step_name": "first", "kind": "form"})

    assert step.matches_context(step_name="first") is True
    assert step.matches_context(step_name="first", kind="form") is True


def test_step_matches_context_returns_false_when_value_differs():
    step = tree.Step(FirstStepForm, context={"step_name": "first"})

    assert step.matches_context(step_name="second") is False


def test_step_matches_context_returns_false_when_key_missing():
    step = tree.Step(FirstStepForm, context={"step_name": "first"})

    assert step.matches_context(kind="form") is False


def test_step_matches_context_returns_true_when_no_kwargs_given():
    step = tree.Step(FirstStepForm)

    assert step.matches_context() is True


def test_step_matches_context_returns_false_when_step_has_no_context():
    step = tree.Step(FirstStepForm)

    assert step.matches_context(step_name="first") is False


def test_context_finder_collects_matching_steps():
    root = tree.Step(
        FirstStepForm,
        context={"step_name": "first"},
        next=tree.Step(SecondStepForm, context={"step_name": "second"}),
    )
    finder = tree.ContextFinder({"step_name": "second"})

    tree.walk(root, finder)

    assert finder.matches == [tree.Step(SecondStepForm, context={"step_name": "second"})]


def test_context_finder_descends_into_branch_arms():
    arm_step = tree.Step(FirstStepForm, context={"step_name": "business"})
    default_step = tree.Step(SecondStepForm, context={"step_name": "personal"})
    root = tree.Branch(
        arms=((_is_business, arm_step),),
        default=default_step,
    )
    finder = tree.ContextFinder({"step_name": "personal"})

    tree.walk(root, finder)

    assert finder.matches == [default_step]


def test_context_finder_one_returns_single_match():
    root = tree.Step(FirstStepForm, context={"step_name": "first"})
    finder = tree.ContextFinder({"step_name": "first"})

    tree.walk(root, finder)

    assert finder.one() == root


def test_context_finder_one_returns_none_when_no_match():
    root = tree.Step(FirstStepForm, context={"step_name": "first"})
    finder = tree.ContextFinder({"step_name": "missing"})

    tree.walk(root, finder)

    assert finder.one() is None


def test_context_finder_one_raises_when_multiple_matches():
    root = tree.Step(
        FirstStepForm,
        context={"step_name": "shared"},
        next=tree.Step(SecondStepForm, context={"step_name": "shared"}),
    )
    finder = tree.ContextFinder({"step_name": "shared"})

    tree.walk(root, finder)

    with pytest.raises(tree.MultipleStepsReturned):
        finder.one()


def test_context_finder_all_returns_matches_in_walk_order():
    root = tree.Step(
        FirstStepForm,
        context={"step_name": "shared"},
        next=tree.Step(SecondStepForm, context={"step_name": "shared"}),
    )
    finder = tree.ContextFinder({"step_name": "shared"})

    tree.walk(root, finder)

    assert finder.all() == [
        tree.Step(
            FirstStepForm,
            context={"step_name": "shared"},
            next=tree.Step(SecondStepForm, context={"step_name": "shared"}),
        ),
        tree.Step(SecondStepForm, context={"step_name": "shared"}),
    ]
