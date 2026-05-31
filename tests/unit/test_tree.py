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


def test_configurer_generates_form_view_for_form_class():
    step = tree.Step(FirstStepForm)

    configured = tree.Configurer(template_name="testapp/linear_wizard.html").transform(
        step
    )

    assert configured.declaration is FirstStepForm
    assert issubclass(configured.form_view, FormView)
    assert configured.form_view.form_class is FirstStepForm
    assert configured.form_view.template_name == "testapp/linear_wizard.html"


def test_configurer_uses_explicit_form_view_unchanged():
    class ExplicitView(FormView):
        form_class = FirstStepForm
        template_name = "testapp/explicit.html"

    step = tree.Step(ExplicitView)

    configured = tree.Configurer(template_name="testapp/linear_wizard.html").transform(
        step
    )

    assert configured.form_view is ExplicitView


def test_configurer_requires_template_name_for_form_class():
    step = tree.Step(FirstStepForm)

    with pytest.raises(
        ImproperlyConfigured,
        match="Wizard.configure\\(\\) must receive template_name",
    ):
        tree.Configurer(template_name=None).transform(step)


def test_configurer_recurses_through_next():
    step = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))

    configured = tree.Configurer(template_name="testapp/linear_wizard.html").transform(
        step
    )

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


def test_interpreter_walk_traverses_chain():
    class Collector(tree.Interpreter):
        def __init__(self):
            self.steps = []

        def visit_step(self, step):
            self.steps.append(step)

        def visit_branch(self, branch):
            pass

    root = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))
    collector = Collector()
    collector.walk(root)

    assert [step.declaration for step in collector.steps] == [
        FirstStepForm,
        SecondStepForm,
    ]


def test_interpreter_walk_stops_when_visit_returns_false():
    class Stopper(tree.Interpreter):
        def __init__(self):
            self.steps = []

        def visit_step(self, step):
            self.steps.append(step)
            return False

        def visit_branch(self, branch):
            pass

    root = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))
    stopper = Stopper()
    stopper.walk(root)

    assert len(stopper.steps) == 1


def test_context_finder_collects_matching_steps():
    root = tree.Step(
        FirstStepForm,
        context={"step_name": "first"},
        next=tree.Step(SecondStepForm, context={"step_name": "second"}),
    )
    finder = tree.ContextFinder({"step_name": "second"})

    finder.visit(root)

    assert finder.all() == [tree.Step(SecondStepForm, context={"step_name": "second"})]


def test_context_finder_descends_into_branch_arms():
    arm_step = tree.Step(FirstStepForm, context={"step_name": "business"})
    default_step = tree.Step(SecondStepForm, context={"step_name": "personal"})
    root = tree.Branch(
        arms=((_is_business, arm_step),),
        default=default_step,
    )
    finder = tree.ContextFinder({"step_name": "personal"})

    finder.visit(root)

    assert finder.all() == [default_step]


def test_context_finder_one_returns_single_match():
    root = tree.Step(FirstStepForm, context={"step_name": "first"})
    finder = tree.ContextFinder({"step_name": "first"})

    finder.visit(root)

    assert finder.one() == root


def test_context_finder_one_returns_none_when_no_match():
    root = tree.Step(FirstStepForm, context={"step_name": "first"})
    finder = tree.ContextFinder({"step_name": "missing"})

    finder.visit(root)

    assert finder.one() is None


def test_context_finder_one_raises_when_multiple_matches():
    root = tree.Step(
        FirstStepForm,
        context={"step_name": "shared"},
        next=tree.Step(SecondStepForm, context={"step_name": "shared"}),
    )
    finder = tree.ContextFinder({"step_name": "shared"})

    finder.visit(root)

    with pytest.raises(tree.MultipleStepsReturned):
        finder.one()


def test_context_finder_all_returns_matches_in_walk_order():
    root = tree.Step(
        FirstStepForm,
        context={"step_name": "shared"},
        next=tree.Step(SecondStepForm, context={"step_name": "shared"}),
    )
    finder = tree.ContextFinder({"step_name": "shared"})

    finder.visit(root)

    assert finder.all() == [
        tree.Step(
            FirstStepForm,
            context={"step_name": "shared"},
            next=tree.Step(SecondStepForm, context={"step_name": "shared"}),
        ),
        tree.Step(SecondStepForm, context={"step_name": "shared"}),
    ]


def test_context_finder_descends_into_branch_default_when_arm_has_no_match():
    arm_step = tree.Step(FirstStepForm, context={"step_name": "business"})
    default_step = tree.Step(SecondStepForm, context={"step_name": "personal"})
    root = tree.Branch(
        arms=((_is_business, arm_step),),
        default=default_step,
    )
    finder = tree.ContextFinder({"step_name": "personal"})

    finder.visit(root)

    assert finder.one().declaration is SecondStepForm


def test_context_finder_require_data_skips_steps_with_no_data():
    from gandalf.runtime import RuntimeStep

    root = RuntimeStep(
        declaration=tree.Step(FirstStepForm, context={"step_name": "first"}),
        data=None,
        next=RuntimeStep(
            declaration=tree.Step(SecondStepForm, context={"step_name": "first"}),
            data={"value": 1},
        ),
    )
    finder = tree.ContextFinder({"step_name": "first"}, require_data=True)

    finder.visit(root)

    matches = finder.all()
    assert len(matches) == 1
    assert matches[0].data == {"value": 1}


def test_context_finder_skips_runtime_branch_with_no_selected_arm():
    from gandalf.runtime import RuntimeBranch, RuntimeStep

    root = RuntimeStep(
        declaration=tree.Step(FirstStepForm, context={"step_name": "first"}),
        data={"value": 1},
        next=RuntimeBranch(
            declaration=tree.Branch(arms=()),
            selected_arm=None,
        ),
    )
    finder = tree.ContextFinder({"step_name": "first"})

    finder.visit(root)

    assert len(finder.all()) == 1


def test_context_finder_handles_declared_branch_with_no_default():
    arm_step = tree.Step(FirstStepForm, context={"step_name": "match"})
    root = tree.Branch(
        arms=((_is_business, arm_step),),
        default=None,
    )
    finder = tree.ContextFinder({"step_name": "match"})

    finder.visit(root)

    assert len(finder.all()) == 1


def test_iter_nodes_yields_chain_and_all_declaration_branch_arms():
    arm = tree.Step(FirstStepForm)
    default = tree.Step(SecondStepForm)
    root = tree.build(
        [
            tree.Step(FirstStepForm),
            tree.Branch(arms=((_is_business, arm),), default=default),
            tree.Step(SecondStepForm),
        ]
    )

    kinds = [type(node).__name__ for node in tree.iter_nodes(root)]

    assert kinds == ["Step", "Branch", "Step", "Step", "Step"]


def test_iter_nodes_follows_only_selected_arm_of_runtime_branch():
    from gandalf.runtime import RuntimeBranch, RuntimeStep

    selected = RuntimeStep(declaration=tree.Step(FirstStepForm), data={"a": 1})
    trailing = RuntimeStep(declaration=tree.Step(SecondStepForm), data={"b": 2})
    root = RuntimeBranch(
        declaration=tree.Branch(arms=()),
        selected_arm=selected,
        next=trailing,
    )

    nodes = list(tree.iter_nodes(root))

    assert nodes == [root, selected, trailing]


def test_build_flow_graph_returns_empty_graph_for_none():
    graph = tree.build_flow_graph(None)

    assert graph == tree.FlowGraph(nodes=(), edges=())


def test_build_flow_graph_threads_a_linear_chain():
    root = tree.build([tree.Step(FirstStepForm), tree.Step(SecondStepForm)])

    graph = tree.build_flow_graph(root)

    assert graph.nodes == (
        tree.FlowNode(key=0, kind="step", label="FirstStepForm"),
        tree.FlowNode(key=1, kind="step", label="SecondStepForm"),
    )
    assert graph.edges == (tree.FlowEdge(source=0, target=1),)


def test_build_flow_graph_captures_branch_topology_and_reconvergence():
    root = tree.build(
        [
            tree.Step(FirstStepForm),
            tree.Branch(
                arms=((_is_business, tree.Step(SecondStepForm)),),
                default=tree.Step(FirstStepForm),
            ),
            tree.Step(SecondStepForm),
        ]
    )

    graph = tree.build_flow_graph(root)

    assert graph.nodes == (
        tree.FlowNode(key=0, kind="step", label="FirstStepForm"),
        tree.FlowNode(key=1, kind="branch", label="Branch"),
        tree.FlowNode(key=2, kind="step", label="SecondStepForm"),
        tree.FlowNode(key=3, kind="step", label="FirstStepForm"),
        tree.FlowNode(key=4, kind="step", label="SecondStepForm"),
    )
    assert graph.edges == (
        tree.FlowEdge(source=1, target=2, label="_is_business"),
        tree.FlowEdge(source=1, target=3, label="default"),
        tree.FlowEdge(source=0, target=1),
        tree.FlowEdge(source=2, target=4),
        tree.FlowEdge(source=3, target=4),
    )


def test_build_flow_graph_adds_skip_edge_when_branch_has_no_default():
    root = tree.build(
        [
            tree.Branch(
                arms=((_is_business, tree.Step(SecondStepForm)),),
                default=None,
            ),
            tree.Step(FirstStepForm),
        ]
    )

    graph = tree.build_flow_graph(root)

    # The branch node (key 0) is itself an exit, so it gains a direct edge to
    # the following step alongside the arm's own exit.
    assert graph.edges == (
        tree.FlowEdge(source=0, target=1, label="_is_business"),
        tree.FlowEdge(source=1, target=2),
        tree.FlowEdge(source=0, target=2),
    )


def test_build_flow_graph_treats_empty_arm_as_a_skip():
    root = tree.build(
        [
            tree.Branch(
                arms=((_is_business, None),),
                default=tree.Step(FirstStepForm),
            ),
            tree.Step(SecondStepForm),
        ]
    )

    graph = tree.build_flow_graph(root)

    assert graph.edges == (
        tree.FlowEdge(source=0, target=1, label="default"),
        tree.FlowEdge(source=0, target=2),
        tree.FlowEdge(source=1, target=2),
    )


def test_mermaid_serializes_a_flow_graph_without_touching_a_tree():
    graph = tree.FlowGraph(
        nodes=(
            tree.FlowNode(key=0, kind="step", label="A"),
            tree.FlowNode(key=1, kind="branch", label="Branch"),
        ),
        edges=(tree.FlowEdge(source=0, target=1, label="go"),),
    )

    assert tree.Mermaid().render(graph) == (
        "flowchart TD\n"
        '    n0["A"]\n'
        '    n1{"Branch"}\n'
        '    n0 -->|"go"| n1'
    )


def test_mermaid_renders_empty_tree():
    assert tree.mermaid(None) == "flowchart TD"


def test_mermaid_renders_single_step():
    assert tree.mermaid(tree.Step(FirstStepForm)) == (
        'flowchart TD\n    n0["FirstStepForm"]'
    )


def test_mermaid_renders_linear_chain():
    root = tree.build([tree.Step(FirstStepForm), tree.Step(SecondStepForm)])

    assert tree.mermaid(root) == (
        "flowchart TD\n"
        '    n0["FirstStepForm"]\n'
        '    n1["SecondStepForm"]\n'
        "    n0 --> n1"
    )


def test_mermaid_renders_branch_with_arm_and_default():
    root = tree.build(
        [
            tree.Step(FirstStepForm),
            tree.Branch(
                arms=((_is_business, tree.Step(SecondStepForm)),),
                default=tree.Step(FirstStepForm),
            ),
            tree.Step(SecondStepForm),
        ]
    )

    assert tree.mermaid(root) == (
        "flowchart TD\n"
        '    n0["FirstStepForm"]\n'
        '    n1{"Branch"}\n'
        '    n2["SecondStepForm"]\n'
        '    n3["FirstStepForm"]\n'
        '    n4["SecondStepForm"]\n'
        '    n1 -->|"_is_business"| n2\n'
        '    n1 -->|"default"| n3\n'
        "    n0 --> n1\n"
        "    n2 --> n4\n"
        "    n3 --> n4"
    )


def test_mermaid_renders_skip_path_when_branch_has_no_default():
    root = tree.build(
        [
            tree.Step(FirstStepForm),
            tree.Branch(
                arms=((_is_business, tree.Step(SecondStepForm)),),
                default=None,
            ),
            tree.Step(FirstStepForm),
        ]
    )

    assert tree.mermaid(root) == (
        "flowchart TD\n"
        '    n0["FirstStepForm"]\n'
        '    n1{"Branch"}\n'
        '    n2["SecondStepForm"]\n'
        '    n3["FirstStepForm"]\n'
        '    n1 -->|"_is_business"| n2\n'
        "    n0 --> n1\n"
        "    n2 --> n3\n"
        "    n1 --> n3"
    )


def test_mermaid_renders_nested_branch():
    inner = tree.Branch(arms=((_is_personal, tree.Step(SecondStepForm)),))
    root = tree.Branch(
        arms=((_is_business, inner),),
        default=tree.Step(FirstStepForm),
    )

    assert tree.mermaid(root) == (
        "flowchart TD\n"
        '    n0{"Branch"}\n'
        '    n1{"Branch"}\n'
        '    n2["SecondStepForm"]\n'
        '    n3["FirstStepForm"]\n'
        '    n1 -->|"_is_personal"| n2\n'
        '    n0 -->|"_is_business"| n1\n'
        '    n0 -->|"default"| n3'
    )


