"""`.expand()` grows the tree mid-walk from a prior answer.

The point of the primitive is that it does this in a *single* walk — the
subtree is built after the answer that shapes it has validated, in the same
pass — where a state-reading `get_wizard()` needs a second walk to notice the
steps its own submission implied.
"""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from tests.testapp.counting import counting_walks


@pytest.fixture
def expand_url():
    return reverse("expand-wizard")


@pytest.fixture
def run_url():
    def build(run_id):
        return reverse("expand-wizard-run", kwargs={"run_id": run_id})

    return build


def _step(run, seg):
    return f"{run}{seg}/"


@pytest.fixture
def started(client, expand_url, run_url):
    client.get(expand_url)
    run_id = list(client.session["gandalf_runs"])[0]
    return run_id, run_url(run_id)


def _state(client, run_id):
    return client.session["gandalf_runs"][run_id]["state"]


def test_answering_the_count_grows_that_many_steps(client, started):
    run_id, run = started

    response = client.post(_step(run, "count"), data={"count": "2"})

    # The expansion built two item steps in the same walk the count validated
    # in, so the run parks on the first of them rather than completing.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == _step(run, "item-0")


def test_the_count_is_answered_in_a_single_walk(client, started):
    run_id, run = started

    with counting_walks() as counts:
        client.post(_step(run, "count"), data={"count": "3"})

    # One walk, not two: the subtree is grown after the count validates,
    # within the same pass, so there is no stale tree to refresh against.
    assert counts.walks == 1


def test_items_store_as_a_positional_list(client, started):
    run_id, run = started
    client.post(_step(run, "count"), data={"count": "2"}, follow=True)
    client.post(_step(run, "item-0"), data={"name": "Ada"}, follow=True)
    client.post(_step(run, "item-1"), data={"name": "Grace"}, follow=True)

    assert _state(client, run_id) == [
        {"step": {"count": "2"}},
        {"expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]},
    ]


def test_completion_reads_every_expanded_answer(client, started):
    run_id, run = started
    client.post(_step(run, "count"), data={"count": "2"}, follow=True)
    client.post(_step(run, "item-0"), data={"name": "Ada"}, follow=True)
    client.post(_step(run, "item-1"), data={"name": "Grace"}, follow=True)

    response = client.post(_step(run, "review"), data={"confirmed": "on"})

    assert response.content == b"completed items=Ada,Grace"


def test_raising_the_count_keeps_answers_and_appends_a_hole(client, started):
    run_id, run = started
    client.post(_step(run, "count"), data={"count": "2"}, follow=True)
    client.post(_step(run, "item-0"), data={"name": "Ada"}, follow=True)
    client.post(_step(run, "item-1"), data={"name": "Grace"}, follow=True)

    # Go back and grow the list. Positional storage keeps the two answers and
    # parks on the newly-created third slot.
    response = client.post(_step(run, "count"), data={"count": "3"})

    assert response["Location"] == _step(run, "item-2")
    assert _state(client, run_id)[1] == {
        "expand": [{"step": {"name": "Ada"}}, {"step": {"name": "Grace"}}]
    }


def test_lowering_the_count_drops_the_trailing_answer(client, started):
    run_id, run = started
    client.post(_step(run, "count"), data={"count": "2"}, follow=True)
    client.post(_step(run, "item-0"), data={"name": "Ada"}, follow=True)
    client.post(_step(run, "item-1"), data={"name": "Grace"}, follow=True)

    # Shrinking the list drops the tail by position: Ada stays, Grace goes.
    client.post(_step(run, "count"), data={"count": "1"}, follow=True)

    assert _state(client, run_id) == [
        {"step": {"count": "1"}},
        {"expand": [{"step": {"name": "Ada"}}]},
    ]


def test_an_empty_expansion_is_skipped(client):
    """A builder that produces no steps leaves nothing behind — the run walks
    straight past the expansion to the step after it."""
    client.get(reverse("empty-expand-wizard"))
    run_id = list(client.session["gandalf_runs"])[0]
    run = reverse("empty-expand-wizard-run", kwargs={"run_id": run_id})

    response = client.post(_step(run, "first"), data={"name": "Ada"})

    assert response["Location"] == _step(run, "review")
    # The empty expansion serialises to nothing, so state holds only the step.
    assert _state(client, run_id) == [{"step": {"name": "Ada"}}]


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

    client.get(reverse("expand-wizard"))
    run_id = list(client.session["gandalf_runs"])[0]
    session = client.session
    session["gandalf_runs"][run_id]["state"] = [{"step": {"count": "1"}}]
    session.save()

    with pytest.raises(ImproperlyConfigured, match="routable name"):
        _drive(_ViewSet, client, run_id)


def test_expansion_cannot_contain_an_expansion(client):
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

    client.get(reverse("expand-wizard"))
    run_id = list(client.session["gandalf_runs"])[0]
    session = client.session
    session["gandalf_runs"][run_id]["state"] = [{"step": {"count": "1"}}]
    session.save()

    with pytest.raises(ImproperlyConfigured, match="cannot contain another expansion"):
        _drive(_ViewSet, client, run_id)


def _drive(viewset_class, client, run_id):
    """Dispatch a bare-run GET at `viewset_class`, which walks and so builds
    the expansion."""
    from django.test import RequestFactory

    request = RequestFactory().get(f"/x/{run_id}/")
    request.session = client.session
    return viewset_class.as_view()(request, run_id=run_id)


# --- Coverage of sealed expansions, path reads over them, and branches
# inside expansions, mirroring the analogous PreservedBranch scenarios. ---


def _sealable_run(client):
    client.get(reverse("sealable-expand-wizard"))
    run_id = list(client.session["gandalf_runs"])[0]
    run = reverse("sealable-expand-wizard-run", kwargs={"run_id": run_id})
    return run_id, run


def test_path_read_is_safe_while_an_expansion_is_sealed(client):
    """The gate is unanswered, so the walk seals before the expansion. A GET
    that renders the gate reads `path`, which must flatten over the sealed
    expansion without rebuilding it."""
    run_id, run = _sealable_run(client)
    session = client.session
    session["gandalf_runs"][run_id]["state"] = [
        {"step": {"count": "1"}},
        {"step": None},
        {"expand": [{"step": {"name": "Ada"}}]},
    ]
    session.save()

    response = client.get(_step(run, "gate"))

    assert response.status_code == HTTPStatus.OK
    # The count is on the active route; the sealed expansion contributes
    # nothing.
    assert response.context["path_names"] == ["count"]


def test_an_invalid_answer_before_a_sealed_expansion_persists_it_verbatim(client):
    run_id, run = _sealable_run(client)
    session = client.session
    session["gandalf_runs"][run_id]["state"] = [
        {"step": {"count": "1"}},
        {"step": None},
        {"expand": [{"step": {"name": "Ada"}}]},
    ]
    session.save()

    # An invalid gate answer parks on the gate and persists — the sealed
    # expansion is serialised back untouched rather than rebuilt.
    client.post(_step(run, "gate"), data={"name": ""}, follow=True)

    assert client.session["gandalf_runs"][run_id]["state"][2] == {
        "expand": [{"step": {"name": "Ada"}}]
    }


def test_merge_cleaned_data_over_an_expanded_run_at_completion(client):
    run_id, run = _sealable_run(client)
    client.post(_step(run, "count"), data={"count": "1"}, follow=True)
    client.post(_step(run, "gate"), data={"name": "Ada"}, follow=True)
    client.post(_step(run, "item-0"), data={"name": "Grace"}, follow=True)

    response = client.post(_step(run, "review"), data={"confirmed": "on"})

    # done() folds cleaned_data across the runtime tree, descending the
    # expansion.
    assert response.content == b"count=1 name=Grace"


def test_an_expansion_can_build_a_branch(client):
    client.get(reverse("branching-expand-wizard"))
    run_id = list(client.session["gandalf_runs"])[0]
    run = reverse("branching-expand-wizard-run", kwargs={"run_id": run_id})

    # Answering the count builds an expansion whose subtree is a branch; the
    # run parks on the selected arm's first step.
    response = client.post(_step(run, "count"), data={"count": "1"})

    assert response["Location"] == _step(run, "biz")
