import tempfile
from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import engines
from django.template.response import SimpleTemplateResponse
from django.test import override_settings

from gandalf.file_storage import WizardFileStorage
from gandalf.storage import SessionStorage
from gandalf.viewsets import WizardViewSet
from gandalf.observers import WizardObserver
from gandalf.wizard import ConfiguredWizard, StepNameRouter, Wizard
from tests.testapp.forms import (
    FirstStepForm,
    ProfilePhotoForm,
    ReviewForm,
    SecondStepForm,
)
from tests.support import configured


class _Session(dict):
    modified = False


def test_step_name_router_resolves_name_context_from_url_kwargs():
    from gandalf.wizard import StepNameRouter

    router = StepNameRouter()

    assert router.resolve({"gandalf_step": "account_type"}) == {
        "name": "account_type",
    }


def test_step_name_router_returns_none_without_url_kwarg():
    from gandalf.wizard import StepNameRouter

    router = StepNameRouter()

    assert router.resolve({}) is None
    assert router.resolve({"gandalf_step": ""}) is None
    assert router.resolve({"org": "acme"}) is None


def test_step_name_router_reverses_step_declaration_to_segment():
    from gandalf import tree
    from gandalf.wizard import StepNameRouter

    router = StepNameRouter()
    named_step = tree.Step(FirstStepForm, context={"name": "first"})
    unnamed_step = tree.Step(FirstStepForm)

    assert router.reverse(named_step) == "first"
    assert router.reverse(unnamed_step) is None


def test_step_name_router_clean_url_kwargs_strips_marker():
    from gandalf.wizard import StepNameRouter

    router = StepNameRouter()

    assert router.clean_url_kwargs({"gandalf_step": "first", "org": "acme"}) == {
        "org": "acme",
    }


def test_a_configured_wizard_carries_its_step_router_class():
    class FakeRouter:
        pass

    wizard = configured(Wizard(), step_router_class=FakeRouter)

    assert wizard.step_router_class is FakeRouter


def test_wizard_viewset_uses_configured_step_router_class(rf):
    from gandalf.wizard import StepNameRouter

    captured = {}

    class CustomRouter(StepNameRouter):
        def resolve(self, url_kwargs):
            captured["resolved"] = dict(url_kwargs)
            return super().resolve(url_kwargs)

    class CustomViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"
        step_router_class = CustomRouter

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/wizard/{run_id}/{step_segment}/"

    request = rf.get("/wizard/abc/")
    request.session = _Session(gandalf_runs={"abc": {}})

    response = CustomViewSet.as_view()(request, run_id="abc")

    assert captured == {"resolved": {}}
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/abc/first/"


def test_wizard_viewset_configures_plain_wizard(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

    request = rf.get("/wizard/")
    request.session = _Session()

    response = PlainWizardViewSet.as_view()(request)

    assert response.status_code == HTTPStatus.FOUND
    viewset = PlainWizardViewSet()
    wizard = viewset.configure_wizard(viewset.get_wizard(run=None))
    assert isinstance(wizard, ConfiguredWizard)


def test_wizard_viewset_routed_post_invalid_submission_redirects_to_same_step(rf):
    request = rf.post("/wizard/existing-run/first/", data={"name": ""})
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/first/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": ""}},
    ]


def test_wizard_viewset_bare_post_redirects_without_storing(rf):
    request = rf.post("/wizard/existing-run/", data={"name": "Ada"})
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/first/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == []


def test_wizard_viewset_get_returns_done_response_after_complete_path(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"

        def done(self, run):
            from django.http import HttpResponse

            return HttpResponse(f"completed {run.run_id}")

    request = rf.get("/wizard/existing-run/")
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        }
    )

    response = PlainWizardViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"completed existing-run"


def test_wizard_viewset_without_done_raises_not_implemented_on_final_step(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/wizard/{run_id}/{step_segment}/"

    request = rf.post("/wizard/existing-run/first/", data={"name": "Ada"})
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {},
            },
        }
    )

    with pytest.raises(
        NotImplementedError,
        match="WizardViewSet subclasses must define done().",
    ):
        PlainWizardViewSet.as_view()(
            request, run_id="existing-run", gandalf_step="first"
        )


def test_wizard_viewset_get_wizard_returns_the_declaration():
    declared = Wizard().step(FirstStepForm)

    class DeclaredViewSet(WizardViewSet):
        wizard = declared
        template_name = "testapp/single_step_wizard.html"

    assert DeclaredViewSet().get_wizard(run=None) is declared


def test_the_viewsets_seams_reach_the_configured_wizard():
    """A `Wizard` is a value and carries none of this; the viewset says it
    all, and `configure_wizard()` is where it lands."""

    class _Observer(WizardObserver):
        pass

    class _Router(StepNameRouter):
        pass

    class SeamedViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm)
        template_name = "testapp/single_step_wizard.html"
        observer_class = _Observer
        step_router_class = _Router
        file_storage_class = WizardFileStorage

    viewset = SeamedViewSet()
    wizard = viewset.configure_wizard(viewset.get_wizard(run=None))

    assert wizard.tree.form_view.template_name == "testapp/single_step_wizard.html"
    assert wizard.observer_class is _Observer
    assert wizard.step_router_class is _Router
    assert wizard.file_storage_class is WizardFileStorage


def test_one_wizard_mounted_by_two_viewsets_renders_with_each_ones_template():
    """The reason the template is the view's: the same declaration, two
    pages."""
    declared = Wizard().step(FirstStepForm)

    class _First(WizardViewSet):
        wizard = declared
        template_name = "testapp/single_step_wizard.html"

    class _Second(WizardViewSet):
        wizard = declared
        template_name = "testapp/other_wizard.html"

    first = _First().configure_wizard(declared)
    second = _Second().configure_wizard(declared)

    assert first.tree.form_view.template_name == "testapp/single_step_wizard.html"
    assert second.tree.form_view.template_name == "testapp/other_wizard.html"


def test_a_static_wizard_is_configured_once_per_viewset_class():
    """Identity across requests is what lets a POST skip its refresh walk,
    so the configured wizard is kept by the class, not the view instance."""
    declared = Wizard().step(FirstStepForm)

    class _Static(WizardViewSet):
        wizard = declared
        template_name = "testapp/single_step_wizard.html"

    first = _Static()._configured_wizard(declared)
    second = _Static()._configured_wizard(declared)

    assert first is second


def test_wizard_viewset_without_wizard_raises_improperly_configured(rf):
    class MyWizardViewSet(WizardViewSet):
        url_name = "my-wizard"

    request = rf.get("/wizard/")
    request.session = _Session()

    with pytest.raises(
        ImproperlyConfigured,
        match=(
            r"MyWizardViewSet has no wizard to run\. Define "
            r"MyWizardViewSet\.wizard as a Wizard declaration, or override "
            r"MyWizardViewSet\.get_wizard\(\) to build one per request\."
        ),
    ):
        MyWizardViewSet.as_view()(request)


def test_wizard_viewset_rejects_invalid_wizard_type(rf):
    """Refused in `configure_wizard()`'s own words whichever way it is
    reached — directly, or through a dispatch, where the configured-wizard
    cache would otherwise choke on a key it cannot hold weakly."""

    class InvalidWizardViewSet(WizardViewSet):
        url_name = "invalid"
        wizard = object()

    viewset = InvalidWizardViewSet()

    with pytest.raises(TypeError, match="WizardViewSet.wizard must be a Wizard"):
        viewset.configure_wizard(viewset.get_wizard(run=None))

    request = rf.get("/wizard/")
    request.session = _Session()

    with pytest.raises(TypeError, match="WizardViewSet.wizard must be a Wizard"):
        InvalidWizardViewSet.as_view()(request)


def test_wizard_viewset_configures_plain_wizard_from_get_wizard(rf):
    class PlainWizardFromGetterViewSet(WizardViewSet):
        template_name = "testapp/single_step_wizard.html"

        def get_wizard(self, run):
            return Wizard().step(FirstStepForm, name="first")

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

    request = rf.get("/wizard/")
    request.session = _Session()

    response = PlainWizardFromGetterViewSet.as_view()(request)

    assert response.status_code == HTTPStatus.FOUND


def test_wizard_viewset_get_wizard_can_build_tree_from_run_state(rf):
    from tests.testapp.forms import ItemCountForm, ItemForm

    class DynamicViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"

        def get_wizard(self, run):
            state = run.get_state()
            wizard = Wizard().step(ItemCountForm, name="count")
            if state:
                count = int(state[0]["step"]["count"])
                for index in range(count):
                    wizard = wizard.step(ItemForm, index=index, name=f"item-{index}")
            return wizard

        def get_wizard_url(self, run_id):
            return f"/dynamic/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/dynamic/{run_id}/{step_segment}/"

    request = rf.get("/dynamic/existing-run/")
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"count": "3"}}],
                },
            },
        }
    )

    response = DynamicViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/dynamic/existing-run/item-0/"


def test_wizard_viewset_dynamic_wizard_walks_again_before_judging_completion(rf):
    """A dynamic `get_wizard()` derives the tree from stored state, so the
    answer just written can imply steps that did not exist when the request
    began. Judging completion against the pre-write tree would fire `done()`
    mid-run, so the refresh walks again — which a static wizard never does,
    because re-resolving hands back the very same object."""
    from tests.testapp.forms import ItemCountForm, ItemForm

    class _DynamicRoutedViewSet(WizardViewSet):
        template_name = "testapp/linear_wizard.html"

        def get_wizard(self, run):
            state = run.get_state()
            wizard = Wizard().step(ItemCountForm, name="count")
            if state:
                for index in range(int(state[0]["step"]["count"])):
                    wizard = wizard.step(ItemForm, name=f"item-{index}")
            return wizard

        def get_wizard_url(self, run_id):
            return f"/dynamic/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/dynamic/{run_id}/{step_segment}/"

        def done(self, run):  # pragma: no cover - must not fire here
            raise AssertionError("done() fired before the implied steps existed")

    request = rf.post("/dynamic/existing-run/count/", data={"count": "2"})
    request.session = _routed_session([])

    response = _DynamicRoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="count"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/dynamic/existing-run/item-0/"


class _RoutedViewSet(WizardViewSet):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .step(ReviewForm, name="review")
    )
    template_name = "testapp/linear_wizard.html"

    def get_wizard_url(self, run_id):
        return f"/wizard/{run_id}/"

    def get_step_url(self, run_id, step_segment):
        return f"/wizard/{run_id}/{step_segment}/"

    def get_start_url(self):
        return "/wizard/"

    def done(self, run):
        from django.http import HttpResponse

        return HttpResponse(b"done")


def _routed_session(state):
    return _Session({"gandalf_runs": {"existing-run": {"state": state}}})


def test_wizard_viewset_routed_get_renders_cursor_step(rf):
    request = rf.get("/wizard/existing-run/second/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="second"
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context_data["form"].__class__ is SecondStepForm


def test_wizard_viewset_routed_get_annotates_back_and_run_urls(rf):
    request = rf.get("/wizard/existing-run/second/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="second"
    )

    step_wizard = response.context_data["view"].request.run
    assert step_wizard.back_url == "/wizard/existing-run/first/"
    assert step_wizard.run_url == "/wizard/existing-run/"


def test_wizard_viewset_first_step_render_has_no_back_url(rf):
    request = rf.get("/wizard/existing-run/first/")
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    step_wizard = response.context_data["view"].request.run
    assert step_wizard.back_url is None


def test_wizard_viewset_edit_render_annotates_back_url(rf):
    request = rf.get("/wizard/existing-run/second/")
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="second"
    )

    step_wizard = response.context_data["view"].request.run
    assert step_wizard.back_url == "/wizard/existing-run/first/"


def test_wizard_viewset_rejected_submission_render_annotates_back_url(rf):
    """The rejected answer is stored and redirected to (PRG), so the errored
    form is rendered by the follow-up GET — which is where `back_url` is
    derived from the walk it already did."""
    session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )
    post = rf.post("/wizard/existing-run/second/", data={"email": ""})
    post.session = session
    _RoutedViewSet.as_view()(post, run_id="existing-run", gandalf_step="second")
    request = rf.get("/wizard/existing-run/second/")
    request.session = session

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="second"
    )

    assert response.context_data["form"].errors
    step_wizard = response.context_data["view"].request.run
    assert step_wizard.back_url == "/wizard/existing-run/first/"


def test_wizard_viewset_routed_get_renders_completed_step_prefilled(rf):
    request = rf.get("/wizard/existing-run/first/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context_data["form"].initial == {"name": "Ada"}


def test_wizard_viewset_routed_get_unknown_step_redirects_to_cursor(rf):
    request = rf.get("/wizard/existing-run/missing/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="missing"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"


def test_wizard_viewset_routed_get_on_complete_run_redirects_to_run_url(rf):
    request = rf.get("/wizard/existing-run/missing/")
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
            {"step": {"confirmed": "on"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="missing"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/"


def test_wizard_viewset_bare_run_url_redirects_to_cursor_step_url(rf):
    request = rf.get("/wizard/existing-run/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    response = _RoutedViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"


def test_wizard_viewset_routed_post_submits_cursor_step_and_redirects(rf):
    request = rf.post("/wizard/existing-run/first/", data={"name": "Ada"})
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Ada"}},
    ]


def test_wizard_viewset_routed_post_final_step_finishes(rf):
    request = rf.post("/wizard/existing-run/review/", data={"confirmed": "on"})
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="review"
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"done"


def test_wizard_viewset_routed_post_edits_completed_step_and_redirects(rf):
    request = rf.post("/wizard/existing-run/first/", data={"name": "Grace"})
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/review/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Grace"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_wizard_viewset_routed_post_rejected_submission_is_kept(rf):
    request = rf.post("/wizard/existing-run/first/", data={"name": ""})
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    # Placement is placement: the rejected answer is stored and becomes the
    # cursor, so the redirect lands back on it and re-renders its errors.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/first/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": ""}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_wizard_viewset_routed_post_to_wrong_step_redirects_without_storing(rf):
    request = rf.post("/wizard/existing-run/review/", data={"confirmed": "on"})
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="review"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Ada"}},
    ]


def test_wizard_viewset_urls_derives_patterns_from_url_name():
    class NamedViewSet(WizardViewSet):
        url_name = "routed-wizard"
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/linear_wizard.html"

    patterns = NamedViewSet.urls()

    assert [pattern.name for pattern in patterns] == [
        "routed-wizard",
        "routed-wizard-run",
        "routed-wizard-step",
    ]


def test_wizard_viewset_urls_requires_url_name():
    from django.core.exceptions import ImproperlyConfigured

    class NamelessViewSet(WizardViewSet):
        pass

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        NamelessViewSet.urls()


def test_wizard_viewset_default_url_hooks_reverse_url_name_patterns():
    class NamedViewSet(WizardViewSet):
        url_name = "routed-wizard"

    viewset = NamedViewSet()
    run_id = "11111111-1111-1111-1111-111111111111"

    assert viewset.get_start_url() == "/routed-wizard/"
    assert viewset.get_wizard_url(run_id) == f"/routed-wizard/{run_id}/"
    assert viewset.get_step_url(run_id, "first") == f"/routed-wizard/{run_id}/first/"


def test_wizard_viewset_get_url_kwargs_strips_wizard_owned_kwargs():
    class NamedViewSet(WizardViewSet):
        url_name = "routed-wizard"

    viewset = NamedViewSet()
    viewset.kwargs = {
        "org": "acme",
        "run_id": "11111111-1111-1111-1111-111111111111",
        "gandalf_step": "first",
    }

    assert viewset.get_url_kwargs() == {"org": "acme"}


def test_wizard_viewset_default_url_hooks_forward_mount_prefix_kwargs():
    class PrefixMountedViewSet(WizardViewSet):
        url_name = "org-scoped-wizard"

    viewset = PrefixMountedViewSet()
    viewset.kwargs = {"org": "acme"}
    run_id = "11111111-1111-1111-1111-111111111111"

    assert viewset.get_start_url() == "/org-scoped-wizard/acme/"
    assert viewset.get_wizard_url(run_id) == f"/org-scoped-wizard/acme/{run_id}/"
    assert (
        viewset.get_step_url(run_id, "first")
        == f"/org-scoped-wizard/acme/{run_id}/first/"
    )


def test_wizard_viewset_default_url_hooks_require_url_name():
    from django.core.exceptions import ImproperlyConfigured

    viewset = WizardViewSet()

    with pytest.raises(ImproperlyConfigured, match="get_start_url"):
        viewset.get_start_url()
    with pytest.raises(ImproperlyConfigured, match="get_wizard_url"):
        viewset.get_wizard_url("existing-run")
    with pytest.raises(ImproperlyConfigured, match="get_step_url"):
        viewset.get_step_url("existing-run", "first")


def test_wizard_viewset_requires_step_urls(rf):
    from django.core.exceptions import ImproperlyConfigured

    class PlainWizardViewSet(WizardViewSet):
        wizard = (
            Wizard()
            .step(FirstStepForm, name="first")
            .step(SecondStepForm, name="second")
        )
        template_name = "testapp/linear_wizard.html"

    request = rf.get("/wizard/existing-run/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    with pytest.raises(ImproperlyConfigured, match="url_name"):
        PlainWizardViewSet.as_view()(request, run_id="existing-run")


def test_wizard_viewset_rejects_wizard_with_unnamed_step(rf):
    from django.core.exceptions import ImproperlyConfigured

    class UnnamedStepViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm).step(SecondStepForm, name="second")
        template_name = "testapp/linear_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/wizard/{run_id}/{step_segment}/"

    request = rf.get("/wizard/existing-run/")
    request.session = _routed_session([])

    with pytest.raises(ImproperlyConfigured, match="FirstStepForm"):
        UnnamedStepViewSet.as_view()(request, run_id="existing-run")


def test_wizard_viewset_post_with_files_stores_uploads_through_file_storage(rf):
    class PlainWizardViewSet(WizardViewSet):
        wizard = (
            Wizard()
            .step(ProfilePhotoForm, name="photo")
            .step(SecondStepForm, name="second")
        )
        template_name = "testapp/linear_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/wizard/{run_id}/{step_segment}/"

    request = rf.post(
        "/wizard/existing-run/photo/",
        data={"photo": SimpleUploadedFile("portrait.jpg", b"binary")},
    )
    request.session = _Session(
        {
            "gandalf_runs": {
                "existing-run": {},
            },
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            response = PlainWizardViewSet.as_view()(
                request, run_id="existing-run", gandalf_step="photo"
            )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"
    stored = request.session["gandalf_runs"]["existing-run"]["state"]
    assert stored[0]["files"]["photo"]["name"] == "portrait.jpg"


# --- Completion lifecycle -------------------------------------------------


def _completed_session():
    return _Session({"gandalf_runs": {"existing-run": {"completed": True}}})


def test_wizard_viewset_finishing_a_run_retires_it(rf):
    request = rf.post("/wizard/existing-run/review/", data={"confirmed": "on"})
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="review"
    )

    assert response.content == b"done"
    assert request.session["gandalf_runs"]["existing-run"] == {"completed": True}


def test_wizard_viewset_get_on_a_retired_run_does_not_rerun_done(rf):
    request = rf.get("/wizard/existing-run/")
    request.session = _completed_session()

    response = _RoutedViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/"
    assert response.content != b"done"


def test_wizard_viewset_step_get_on_a_retired_run_offers_no_edit(rf):
    request = rf.get("/wizard/existing-run/first/")
    request.session = _completed_session()

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/"


def test_wizard_viewset_post_to_a_retired_run_stores_nothing(rf):
    request = rf.post("/wizard/existing-run/first/", data={"name": "Grace"})
    request.session = _completed_session()

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/"
    assert request.session["gandalf_runs"]["existing-run"] == {"completed": True}


def test_wizard_viewset_finish_fires_done_and_retires_the_run(rf):
    """`finish()` is the programmatic completion: `done()` fires once, the
    run's files are cleaned up, and the run is tombstoned — exactly what a
    completing GET or POST does, without a request cycle."""
    request = rf.get("/wizard/existing-run/")
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
            {"step": {"confirmed": "on"}},
        ]
    )
    view = _RoutedViewSet()
    view.setup(request)
    run = _RoutedViewSet.inspect(request, "existing-run")

    response = view.finish(run)

    assert response.content == b"done"
    assert request.session["gandalf_runs"]["existing-run"] == {"completed": True}


def test_wizard_viewset_finish_keeps_a_deferred_response_readable_until_it_renders(
    rf,
):
    """Issue #39: a `TemplateResponse` from `done()` renders after `finish()`
    has returned, so a completion page reading the finished run back — the
    README's re-entrant pattern — walks it and opens its uploads at that
    point. Both have to outlive `finish()`. The tombstone does not wait with
    them: a completion template that raises must not leave a run whose
    `done()` can fire a second time."""

    class DeferredDoneViewSet(WizardViewSet):
        wizard = Wizard().step(ProfilePhotoForm, name="photo")
        template_name = "testapp/linear_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/wizard/{run_id}/{step_segment}/"

        def done(self, run):
            return SimpleTemplateResponse(
                engines["django"].from_string(
                    "{% for step in wizard.path %}"
                    "{{ step.form.cleaned_data.photo.name }}"
                    "{% endfor %}"
                ),
                {"wizard": run},
            )

    request = rf.get("/wizard/existing-run/")

    with tempfile.TemporaryDirectory() as tmpdir:
        with override_settings(MEDIA_ROOT=tmpdir):
            file_storage = WizardFileStorage()
            ref = file_storage.save(
                "existing-run", SimpleUploadedFile("portrait.jpg", b"binary")
            )
            request.session = _routed_session([{"step": {}, "files": {"photo": ref}}])
            view = DeferredDoneViewSet()
            view.setup(request)
            run = DeferredDoneViewSet.inspect(request, "existing-run")

            response = view.finish(run)

            # Retired already, but not yet swept: the response has not rendered.
            assert run.is_complete
            assert file_storage.backend.exists(ref["tmp_name"])

            response.render()

            assert response.content == b"portrait.jpg"
            assert not file_storage.backend.exists(ref["tmp_name"])


def test_wizard_viewset_finish_with_a_raising_done_leaves_the_run_resumable(rf):
    """The tombstone is written after `done()` returns, so a `done()` that
    raises leaves the run's answers stored and the run still runnable."""

    class ExplodingViewSet(_RoutedViewSet):
        def done(self, run):
            raise RuntimeError("side effect failed")

    state = [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
        {"step": {"confirmed": "on"}},
    ]
    request = rf.get("/wizard/existing-run/")
    request.session = _routed_session(state)
    view = ExplodingViewSet()
    view.setup(request)
    run = ExplodingViewSet.inspect(request, "existing-run")

    with pytest.raises(RuntimeError):
        view.finish(run)

    assert not run.is_complete
    assert request.session["gandalf_runs"]["existing-run"]["state"] == state


def test_wizard_viewset_get_on_an_unknown_run_is_unavailable(rf):
    request = rf.get("/wizard/missing-run/")
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(request, run_id="missing-run")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/"


def test_wizard_viewset_get_without_any_stored_runs_is_unavailable(rf):
    request = rf.get("/wizard/existing-run/")
    request.session = _Session()

    response = _RoutedViewSet.as_view()(request, run_id="existing-run")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/"


def test_wizard_viewset_post_to_an_unknown_run_is_unavailable(rf):
    request = rf.post("/wizard/missing-run/first/", data={"name": "Ada"})
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(
        request, run_id="missing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/"
    assert "missing-run" not in request.session["gandalf_runs"]


def test_wizard_viewset_run_unavailable_hook_receives_the_reason(rf):
    from django.http import HttpResponse

    reasons = []

    class HookedViewSet(_RoutedViewSet):
        def run_unavailable(self, run, reason):
            reasons.append(reason)
            return HttpResponse(b"unavailable")

    completed = rf.get("/wizard/existing-run/")
    completed.session = _completed_session()
    HookedViewSet.as_view()(completed, run_id="existing-run")

    unknown = rf.get("/wizard/missing-run/")
    unknown.session = _routed_session([])
    HookedViewSet.as_view()(unknown, run_id="missing-run")

    assert reasons == ["completed", "unknown"]


def test_wizard_viewset_reuses_an_already_configured_wizard_on_refresh(rf):
    """A pre-configured wizard is the same object on every resolve, so the
    post-submission refresh rebinds nothing and skips re-validating it."""
    validations = []

    class PreConfiguredViewSet(_RoutedViewSet):
        wizard = (
            Wizard()
            .step(FirstStepForm, name="first")
            .step(SecondStepForm, name="second")
        )

        def _validate_routable(self, wizard):
            validations.append(wizard)
            return super()._validate_routable(wizard)

    request = rf.post("/wizard/existing-run/first/", data={"name": "Ada"})
    request.session = _routed_session([])

    response = PreConfiguredViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"
    assert len(validations) == 1


# --- Escape dispositions --------------------------------------------------


def _escaping_viewset(*steps, done_body=None):
    from django.http import HttpResponse

    wizard = Wizard()
    for form, name in steps:
        wizard = wizard.step(form, name=name)

    class _EscapingViewSet(_RoutedViewSet):
        pass

    _EscapingViewSet.wizard = wizard
    if done_body is not None:
        _EscapingViewSet.done = lambda self, run: HttpResponse(done_body(run))
    return _EscapingViewSet


def test_wizard_viewset_parking_escape_rolls_state_back(rf):
    from django.urls import reverse

    from tests.testapp.forms import EmailLookupForm

    viewset = _escaping_viewset(
        (EmailLookupForm, "lookup"),
        (SecondStepForm, "second"),
    )
    request = rf.post(
        "/wizard/existing-run/lookup/", data={"email": "existing@example.com"}
    )
    request.session = _routed_session([])

    response = viewset.as_view()(request, run_id="existing-run", gandalf_step="lookup")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse("escape-landing")
    assert request.session["gandalf_runs"]["existing-run"]["state"] == []


def test_wizard_viewset_advancing_escape_keeps_the_stored_answer(rf):
    from django.urls import reverse

    from tests.testapp.forms import NewsletterForm

    viewset = _escaping_viewset(
        (NewsletterForm, "newsletter"),
        (SecondStepForm, "second"),
    )
    request = rf.post(
        "/wizard/existing-run/newsletter/",
        data={"email": "ada@example.com", "subscribe": "on"},
    )
    request.session = _routed_session([])

    response = viewset.as_view()(
        request, run_id="existing-run", gandalf_step="newsletter"
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse("escape-landing")
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"email": "ada@example.com", "subscribe": "on"}},
    ]


def test_wizard_viewset_obliterating_escape_forgets_the_run(rf):
    from django.urls import reverse

    from tests.testapp.views import CancelSignupStepView

    viewset = _escaping_viewset(
        (CancelSignupStepView, "cancel"),
        (SecondStepForm, "second"),
    )
    request = rf.post(
        "/wizard/existing-run/cancel/",
        data={"reason": "changed my mind", "cancel": "on"},
    )
    request.session = _routed_session([])

    response = viewset.as_view()(request, run_id="existing-run", gandalf_step="cancel")

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == reverse("escape-landing")
    assert "existing-run" not in request.session["gandalf_runs"]


def test_wizard_viewset_rejects_an_escape_naming_no_disposition(rf):
    from tests.testapp.forms import BareEscapeForm

    viewset = _escaping_viewset(
        (BareEscapeForm, "bare"),
        (SecondStepForm, "second"),
    )
    request = rf.post("/wizard/existing-run/bare/", data={"name": "Ada"})
    request.session = _routed_session([])

    with pytest.raises(ImproperlyConfigured, match="names no disposition"):
        viewset.as_view()(request, run_id="existing-run", gandalf_step="bare")


def test_wizard_viewset_reconstructs_the_form_of_an_escaped_answer(rf):
    from tests.testapp.forms import NewsletterForm

    viewset = _escaping_viewset(
        (NewsletterForm, "newsletter"),
        done_body=lambda run: ",".join(sorted(run.runtime_tree.form.cleaned_data)),
    )
    request = rf.get("/wizard/existing-run/")
    request.session = _routed_session(
        [{"step": {"email": "ada@example.com", "subscribe": "on"}}]
    )

    response = viewset.as_view()(request, run_id="existing-run")

    # `.form` swallows the escape the stored answer raises, so the fields
    # cleaned before the raise stay readable.
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"email,subscribe"


def test_wizard_viewset_placing_an_escaping_answer_on_a_completed_step(rf):
    from tests.testapp.forms import NewsletterForm

    viewset = _escaping_viewset(
        (NewsletterForm, "newsletter"),
        (SecondStepForm, "second"),
    )
    request = rf.post(
        "/wizard/existing-run/newsletter/",
        data={"email": "ada@example.com", "subscribe": "on"},
    )
    request.session = _routed_session(
        [{"step": {"email": "ada@example.com", "subscribe": ""}}]
    )

    response = viewset.as_view()(
        request, run_id="existing-run", gandalf_step="newsletter"
    )

    # A step escapes wherever it sits — there is no separate edit path for
    # the disposition to be defined against. `Advance` keeps the answer.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/escaped/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"email": "ada@example.com", "subscribe": "on"}},
    ]


# --- Resurrecting a stash -------------------------------------------------


def _resurrect_payload(state):
    from gandalf.runtime import STASH_VERSION

    return {"version": STASH_VERSION, "state": state}


def _only_run(request):
    (run_id,) = request.session["gandalf_runs"]
    return run_id


def test_wizard_viewset_resurrect_seeds_a_run_and_returns_its_first_step_url(rf):
    """A fully-valid resurrected run must land on a step URL: the bare run
    URL would walk straight to completion and fire `done()` before the user
    edited anything."""
    request = rf.get("/somewhere-else/")
    request.session = _Session()
    payload = _resurrect_payload(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
            {"step": {"confirmed": "on"}},
        ]
    )

    url = _RoutedViewSet.resurrect(request, payload)

    run_id = _only_run(request)
    assert url == f"/wizard/{run_id}/first/"
    assert request.session["gandalf_runs"][run_id]["state"] == payload["state"]


def test_wizard_viewset_resurrect_step_names_the_landing_step(rf):
    request = rf.get("/somewhere-else/")
    request.session = _Session()
    payload = _resurrect_payload([{"step": {"name": "Ada"}}])

    url = _RoutedViewSet.resurrect(request, payload, step="second")

    assert url == f"/wizard/{_only_run(request)}/second/"


def test_wizard_viewset_resurrect_lands_on_the_cursor_of_a_partial_stash(rf):
    """A stash need not be complete — a stripped required-file step or a
    hole leaves the run parked mid-way, and that parking spot is where the
    user has to resume."""
    request = rf.get("/somewhere-else/")
    request.session = _Session()
    payload = _resurrect_payload([{"step": {"name": "Ada"}}])

    url = _RoutedViewSet.resurrect(request, payload)

    assert url == f"/wizard/{_only_run(request)}/second/"


def test_wizard_viewset_resurrect_forwards_mount_prefix_url_kwargs(rf):
    class _PrefixedViewSet(_RoutedViewSet):
        def get_step_url(self, run_id, step_segment):
            org = self.kwargs["org"]
            return f"/{org}/wizard/{run_id}/{step_segment}/"

    request = rf.get("/somewhere-else/")
    request.session = _Session()
    payload = _resurrect_payload([{"step": {"name": "Ada"}}])

    url = _PrefixedViewSet.resurrect(request, payload, org="acme")

    assert url == f"/acme/wizard/{_only_run(request)}/second/"


def test_wizard_viewset_resurrect_of_an_empty_wizard_falls_back_to_the_run_url(rf):
    """A wizard with no steps has no step URL to land on; the bare run URL
    (which completes immediately) is all there is."""

    class _EmptyViewSet(_RoutedViewSet):
        wizard = Wizard()

    request = rf.get("/somewhere-else/")
    request.session = _Session()

    url = _EmptyViewSet.resurrect(request, _resurrect_payload([]))

    assert url == f"/wizard/{_only_run(request)}/"


def test_wizard_viewset_resurrect_propagates_an_invalid_stash(rf):
    from gandalf.runtime import InvalidStash

    request = rf.get("/somewhere-else/")
    request.session = _Session()

    with pytest.raises(InvalidStash):
        _RoutedViewSet.resurrect(request, {"state": "not-a-list"})
    with pytest.raises(InvalidStash):
        _RoutedViewSet.resurrect(
            request,
            _resurrect_payload([{"step": {"name": "Ada"}}]),
            expected_label="contact",
        )
    assert request.session.get("gandalf_runs", {}) == {}


# --- Binding a wizard outside its own request cycle -----------------------


def test_wizard_viewset_begin_returns_a_fresh_run_rather_than_a_redirect(rf):
    """What the start URL does, minus the redirect — a caller that has to
    remember which run a thing is being answered in learns the id at the
    moment it is created."""
    request = rf.get("/somewhere-else/")
    request.session = _Session()

    run = _RoutedViewSet.begin(request)

    assert run.run_id == _only_run(request)
    assert run.get_state() == []
    assert run.entry_url() == f"/wizard/{run.run_id}/first/"


def test_wizard_viewset_inspect_binds_an_existing_run(rf):
    request = rf.get("/somewhere-else/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    run = _RoutedViewSet.inspect(request, "existing-run")

    assert run.run_id == "existing-run"
    assert run.cursor().node.context["name"] == "second"
    assert run.entry_url() == "/wizard/existing-run/second/"


def test_wizard_viewset_inspect_raises_for_a_run_this_storage_does_not_hold(rf):
    from gandalf.storage import RunNotFound

    request = rf.get("/somewhere-else/")
    request.session = _Session()

    with pytest.raises(RunNotFound):
        _RoutedViewSet.inspect(request, "no-such-run")


def test_wizard_viewset_inspect_finds_a_completed_run_rather_than_raising(rf):
    """A tombstone is *found* — it stays addressable so a revisit can be
    answered as finished. `is_complete` is what tells the two apart."""
    request = rf.get("/somewhere-else/")
    request.session = _Session({"gandalf_runs": {"existing-run": {"completed": True}}})

    run = _RoutedViewSet.inspect(request, "existing-run")

    assert run.is_complete
    assert run.get_state() == []


def test_wizard_viewset_inspect_resolves_the_wizard_against_the_stored_state(rf):
    """Retrieve before resolve: a dynamic `get_wizard()` is entitled to read
    the run's state to decide its shape."""
    seen = []

    class _DynamicViewSet(_RoutedViewSet):
        def get_wizard(self, run):
            seen.append(run.get_state())
            return super().get_wizard(run)

    request = rf.get("/somewhere-else/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])

    _DynamicViewSet.inspect(request, "existing-run")

    assert seen == [[{"step": {"name": "Ada"}}]]


def test_wizard_viewset_reopen_returns_the_run_behind_a_resurrection(rf):
    request = rf.get("/somewhere-else/")
    request.session = _Session()
    payload = _resurrect_payload([{"step": {"name": "Ada"}}])

    run = _RoutedViewSet.reopen(request, payload)

    assert run.run_id == _only_run(request)
    assert run.get_state() == [{"step": {"name": "Ada"}}]
    assert run.entry_url() == f"/wizard/{run.run_id}/second/"


def test_wizard_viewset_reopen_resolves_the_wizard_against_the_seeded_state(rf):
    """Seed before resolve, unlike `inspect()`: the state a dynamic
    `get_wizard()` reads is the state the payload just supplied."""
    seen = []

    class _DynamicViewSet(_RoutedViewSet):
        def get_wizard(self, run):
            seen.append(run.get_state())
            return super().get_wizard(run)

    request = rf.get("/somewhere-else/")
    request.session = _Session()

    _DynamicViewSet.reopen(request, _resurrect_payload([{"step": {"name": "Ada"}}]))

    assert seen == [[{"step": {"name": "Ada"}}]]


def test_wizard_viewset_reopen_refuses_a_label_mismatch_before_creating_a_run(rf):
    from gandalf.runtime import InvalidStash

    request = rf.get("/somewhere-else/")
    request.session = _Session()

    with pytest.raises(InvalidStash):
        _RoutedViewSet.reopen(
            request,
            _resurrect_payload([{"step": {"name": "Ada"}}]),
            expected_label="contact",
        )
    assert request.session.get("gandalf_runs", {}) == {}


@pytest.mark.parametrize("method", ["begin", "inspect", "reopen"])
def test_binding_a_wizard_forwards_mount_prefix_url_kwargs(rf, method):
    class _PrefixedViewSet(_RoutedViewSet):
        def get_step_url(self, run_id, step_segment):
            org = self.kwargs["org"]
            return f"/{org}/wizard/{run_id}/{step_segment}/"

    request = rf.get("/somewhere-else/")
    request.session = _routed_session([{"step": {"name": "Ada"}}])
    arguments = {
        "begin": (),
        "inspect": ("existing-run",),
        "reopen": (_resurrect_payload([{"step": {"name": "Ada"}}]),),
    }[method]

    run = getattr(_PrefixedViewSet, method)(request, *arguments, org="acme")

    assert run.entry_url("second") == (f"/acme/wizard/{run.run_id}/second/")


def test_wizard_viewset_rejects_duplicate_step_names(rf):
    """Two steps sharing a name is a declaration error: a URL segment has to
    name exactly one step, and a walk stops at the cursor so it could not see
    a duplicate lying beyond it."""

    class _DuplicateViewSet(WizardViewSet):
        url_name = "wizard"
        template_name = "testapp/linear_wizard.html"
        wizard = (
            Wizard()
            .step(FirstStepForm, name="duplicate")
            .step(SecondStepForm, name="duplicate")
        )

    request = rf.get("/wizard/existing-run/duplicate/")
    request.session = _routed_session([])

    with pytest.raises(ImproperlyConfigured, match="must be unique"):
        _DuplicateViewSet.as_view()(
            request, run_id="existing-run", gandalf_step="duplicate"
        )


def test_wizard_viewset_resolve_binds_the_wizard_without_starting_a_run(rf):
    """The third door: not running a wizard, nor reaching a run, but asking
    what the wizard is. Nothing is left behind by asking."""
    request = rf.get("/wizard/")
    request.session = _Session()

    run = _RoutedViewSet.resolve(request)

    assert [entry["name"] for entry in run.wizard.outline()] == [
        "first",
        "second",
        "review",
    ]
    assert request.session.get("gandalf_runs", {}) == {}


def test_run_started_is_handed_a_run_with_an_id_and_a_resolved_wizard(rf):
    seen = {}

    class StartedViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def run_started(self, run):
            # Both halves matter: without the id there is nowhere to write
            # metadata, and without the wizard a dynamic `get_wizard()`
            # could not have been consulted yet.
            seen["run_id"] = run.run_id
            seen["wizard"] = run.wizard
            run.metadata["opened"] = True

    request = rf.get("/wizard/")
    request.session = _Session()

    response = StartedViewSet.as_view()(request)

    assert response.status_code == HTTPStatus.FOUND
    assert seen["run_id"] is not None
    assert isinstance(seen["wizard"], ConfiguredWizard)
    runs = request.session[SessionStorage.SESSION_KEY]
    assert runs[seen["run_id"]]["meta"] == {"run": {"opened": True}}


def test_run_started_that_raises_leaves_no_run_the_caller_can_use(rf):
    class RefusingViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def run_started(self, run):
            raise RuntimeError("the record could not be opened")

    request = rf.get("/wizard/")
    request.session = _Session()

    # Unlike an observer, this may raise, and a raise propagates: a run
    # that cannot set its record up refuses to start rather than starting
    # one that lies about having done so.
    with pytest.raises(RuntimeError, match="the record could not be opened"):
        RefusingViewSet.as_view()(request)


def test_run_started_does_not_fire_for_a_run_that_already_exists(rf):
    started = []

    class CountingViewSet(WizardViewSet):
        wizard = Wizard().step(FirstStepForm, name="first")
        template_name = "testapp/single_step_wizard.html"

        def get_wizard_url(self, run_id):
            return f"/wizard/{run_id}/"

        def get_step_url(self, run_id, step_segment):
            return f"/wizard/{run_id}/{step_segment}/"

        def run_started(self, run):
            started.append(run.run_id)

    request = rf.get("/wizard/abc/")
    request.session = _Session(gandalf_runs={"abc": {}})

    CountingViewSet.as_view()(request, run_id="abc")

    assert started == []
