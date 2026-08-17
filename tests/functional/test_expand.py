"""`.expand()` grows the tree mid-walk from a prior answer.

The point of the primitive is that it does this in a *single* walk — the
subtree is built after the answer that shapes it has validated, in the same
pass — where a state-reading `get_wizard()` needs a second walk to notice the
steps its own submission implied.
"""

from http import HTTPStatus

from django.core.exceptions import ImproperlyConfigured
import pytest

from tests.testapp.counting import counting_walks


@pytest.fixture
def started(wizard_driver):
    return wizard_driver("expand-wizard").start()


def test_answering_the_count_grows_that_many_steps(started):
    response = started.post_step("count", {"count": "2"})

    # The expansion built two item steps in the same walk the count validated
    # in, so the run parks on the first of them rather than completing.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == started.step_url("item-0")


def test_the_count_is_answered_in_a_single_walk(started):
    with counting_walks() as counts:
        started.post_step("count", {"count": "3"})

    # One walk, not two: the subtree is grown after the count validates,
    # within the same pass, so there is no stale tree to refresh against.
    assert counts.walks == 1


def test_items_store_as_a_positional_list(started):
    started.post_steps(
        [
            ("count", {"count": "2"}),
            ("item-0", {"name": "Ada"}),
            ("item-1", {"name": "Grace"}),
        ]
    )

    assert started.state == [
        {"step": {"count": "2"}},
        {"expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]},
    ]


def test_completion_reads_every_expanded_answer(started):
    started.post_steps(
        [
            ("count", {"count": "2"}),
            ("item-0", {"name": "Ada"}),
            ("item-1", {"name": "Grace"}),
        ]
    )

    response = started.post_step("review", {"confirmed": "on"})

    assert response.content == b"completed items=Ada,Grace"


def test_raising_the_count_keeps_answers_and_appends_a_hole(started):
    started.post_steps(
        [
            ("count", {"count": "2"}),
            ("item-0", {"name": "Ada"}),
            ("item-1", {"name": "Grace"}),
        ]
    )

    # Go back and grow the list. Positional storage keeps the two answers and
    # parks on the newly-created third slot.
    response = started.post_step("count", {"count": "3"})

    assert response["Location"] == started.step_url("item-2")
    assert started.state[1] == {
        "expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]
    }


def test_lowering_the_count_drops_the_trailing_answer(started):
    started.post_steps(
        [
            ("count", {"count": "2"}),
            ("item-0", {"name": "Ada"}),
            ("item-1", {"name": "Grace"}),
        ]
    )

    # Shrinking the list drops the tail by position: Ada stays, Grace goes.
    started.post_step("count", {"count": "1"}, follow=True)

    assert started.state == [
        {"step": {"count": "1"}},
        {"expand": [{"step": {"name": "Ada"}}]},
    ]


def test_an_empty_expansion_is_skipped(wizard_driver):
    """A builder that produces no steps leaves nothing behind — the run walks
    straight past the expansion to the step after it."""
    run = wizard_driver("empty-expand-wizard").start()

    response = run.post_step("first", {"name": "Ada"})

    assert response["Location"] == run.step_url("review")
    # The empty expansion serialises to nothing, so state holds only the step.
    assert run.state == [{"step": {"name": "Ada"}}]


def test_unroutable_expanded_step_is_rejected_when_built(client, started):
    """The subtree does not exist at resolve time, so an unroutable step in it
    can only be caught when the expansion is built."""
    from django.http import HttpResponse
    from django.views.generic.edit import FormView

    from gandalf.viewsets import WizardViewSet
    from gandalf.wizard import Wizard
    from tests.testapp.forms import FirstStepForm, ItemCountForm

    class Unnamed(FormView):
        form_class = FirstStepForm
        template_name = "testapp/linear_wizard.html"

    def build_unnamed(request):
        return Wizard().step(Unnamed)  # no name -> unroutable

    class _ViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        url_name = "bad-expand"
        wizard = Wizard().step(ItemCountForm, name="count").expand(build_unnamed)

        def done(self, bound_wizard):  # pragma: no cover
            return HttpResponse("done")

    started.post_step("count", {"count": "1"})

    with pytest.raises(ImproperlyConfigured, match="routable name"):
        _drive(_ViewSet, client, started.run_id)


def test_expansion_cannot_contain_an_expansion(client, started):
    from django.http import HttpResponse

    from gandalf.viewsets import WizardViewSet
    from gandalf.wizard import Wizard
    from tests.testapp.forms import ItemCountForm, ItemForm

    def inner(request):
        return Wizard().step(ItemForm, name="inner")

    def outer(request):
        return Wizard().step(ItemForm, name="outer").expand(inner)

    class _ViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"
        url_name = "nested-expand"
        wizard = Wizard().step(ItemCountForm, name="count").expand(outer)

        def done(self, bound_wizard):  # pragma: no cover
            return HttpResponse("done")

    started.post_step("count", {"count": "1"})

    with pytest.raises(ImproperlyConfigured, match="cannot contain another expansion"):
        _drive(_ViewSet, client, started.run_id)


def _drive(viewset_class, client, run_id):
    """Dispatch a bare-run GET at `viewset_class`, which walks and so builds
    the expansion."""
    from django.test import RequestFactory

    request = RequestFactory().get(f"/x/{run_id}/")
    request.session = client.session
    return viewset_class.as_view()(request, run_id=run_id)


# --- Coverage of sealed expansions, path reads over them, and branches
# inside expansions, mirroring the analogous PreservedBranch scenarios. ---


@pytest.fixture
def sealable_run(wizard_driver):
    return wizard_driver("sealable-expand-wizard").start()


def test_path_read_is_safe_while_an_expansion_is_sealed(sealable_run):
    """The gate is unanswered, so the walk seals before the expansion. A GET
    that renders the gate reads `path`, which must flatten over the sealed
    expansion without rebuilding it."""
    # Seeded rather than driven: an answer behind an unanswered step is the
    # one thing no walk will place, so neither door produces this state.
    sealable_run.seed_state(
        [
            {"step": {"count": "1"}},
            {"step": None},
            {"expand": [{"step": {"name": "Ada"}}]},
        ]
    )

    response = sealable_run.get_step("gate")

    assert response.status_code == HTTPStatus.OK
    # The count is on the active route; the sealed expansion contributes
    # nothing.
    assert response.context["path_names"] == ["count"]


def test_an_invalid_answer_before_a_sealed_expansion_persists_it_verbatim(
    sealable_run,
):
    sealable_run.seed_state(
        [
            {"step": {"count": "1"}},
            {"step": None},
            {"expand": [{"step": {"name": "Ada"}}]},
        ]
    )

    # An invalid gate answer parks on the gate and persists — the sealed
    # expansion is serialised back untouched rather than rebuilt.
    sealable_run.post_step("gate", {"name": ""}, follow=True)

    assert sealable_run.state[2] == {"expand": [{"step": {"name": "Ada"}}]}


def test_merge_cleaned_data_over_an_expanded_run_at_completion(sealable_run):
    sealable_run.post_steps(
        [
            ("count", {"count": "1"}),
            ("gate", {"name": "Ada"}),
            ("item-0", {"name": "Grace"}),
        ]
    )

    response = sealable_run.post_step("review", {"confirmed": "on"})

    # done() folds cleaned_data across the runtime tree, descending the
    # expansion.
    assert response.content == b"count=1 name=Grace"


def test_an_expansion_can_build_a_branch(wizard_driver):
    run = wizard_driver("branching-expand-wizard").start()

    # Answering the count builds an expansion whose subtree is a branch; the
    # run parks on the selected arm's first step.
    response = run.post_step("count", {"count": "1"})

    assert response["Location"] == run.step_url("biz")
