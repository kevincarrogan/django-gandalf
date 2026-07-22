import tempfile
from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from gandalf.viewsets import WizardViewSet
from gandalf.wizard import ConfiguredWizard, Wizard
from tests.testapp.forms import (
    FirstStepForm,
    ProfilePhotoForm,
    ReviewForm,
    SecondStepForm,
)


class _Session(dict):
    modified = False


def test_step_name_router_resolves_step_name_context_from_url_kwargs():
    from gandalf.wizard import StepNameRouter

    router = StepNameRouter()

    assert router.resolve({"gandalf_step": "account_type"}) == {
        "step_name": "account_type",
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
    named_step = tree.Step(FirstStepForm, context={"step_name": "first"})
    unnamed_step = tree.Step(FirstStepForm)

    assert router.reverse(named_step) == "first"
    assert router.reverse(unnamed_step) is None


def test_step_name_router_clean_url_kwargs_strips_marker():
    from gandalf.wizard import StepNameRouter

    router = StepNameRouter()

    assert router.clean_url_kwargs({"gandalf_step": "first", "org": "acme"}) == {
        "org": "acme",
    }


def test_wizard_configure_overrides_step_router_class():
    class FakeRouter:
        pass

    wizard = Wizard().configure(step_router_class=FakeRouter)

    assert wizard.step_router_class is FakeRouter


def test_wizard_viewset_uses_configured_step_router_class(rf):
    from gandalf.wizard import StepNameRouter

    captured = {}

    class CustomRouter(StepNameRouter):
        def resolve(self, url_kwargs):
            captured["resolved"] = dict(url_kwargs)
            return super().resolve(url_kwargs)

    class CustomViewSet(WizardViewSet):
        wizard = (
            Wizard()
            .step(FirstStepForm, name="first")
            .configure(
                template_name="testapp/single_step_wizard.html",
                step_router_class=CustomRouter,
            )
        )

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
    configured = viewset.configure_wizard(viewset.get_wizard(bound_wizard=None))
    assert isinstance(configured, ConfiguredWizard)


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

        def done(self, bound_wizard):
            from django.http import HttpResponse

            return HttpResponse(f"completed {bound_wizard.run_id}")

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


def test_wizard_viewset_uses_configured_wizard():
    configured_wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(template_name="testapp/single_step_wizard.html")
    )

    class ConfiguredWizardViewSet(WizardViewSet):
        wizard = configured_wizard
        template_name = "testapp/single_step_wizard.html"

    wizard = ConfiguredWizardViewSet().get_wizard(bound_wizard=None)

    assert wizard is configured_wizard


def test_wizard_viewset_does_not_reconfigure_configured_wizard():
    configured_wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(template_name="testapp/single_step_wizard.html")
    )

    class ConfiguredWizardViewSet(WizardViewSet):
        wizard = configured_wizard
        template_name = "testapp/other_wizard.html"

    viewset = ConfiguredWizardViewSet()
    wizard = viewset.configure_wizard(viewset.get_wizard(bound_wizard=None))

    assert wizard is configured_wizard
    assert wizard.tree.form_view.template_name == "testapp/single_step_wizard.html"


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


def test_wizard_viewset_rejects_invalid_wizard_type():
    class InvalidWizardViewSet(WizardViewSet):
        wizard = object()

    viewset = InvalidWizardViewSet()

    with pytest.raises(
        TypeError,
        match="WizardViewSet.wizard must be a Wizard or ConfiguredWizard",
    ):
        viewset.configure_wizard(viewset.get_wizard(bound_wizard=None))


def test_wizard_viewset_configures_plain_wizard_from_get_wizard(rf):
    class PlainWizardFromGetterViewSet(WizardViewSet):
        template_name = "testapp/single_step_wizard.html"

        def get_wizard(self, bound_wizard):
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

        def get_wizard(self, bound_wizard):
            state = bound_wizard.get_state()
            wizard = Wizard().step(ItemCountForm, name="count")
            if state:
                count = int(state[0]["step"]["count"])
                for index in range(count):
                    wizard = wizard.step(
                        ItemForm, context={"index": index}, name=f"item-{index}"
                    )
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


class _RoutedViewSet(WizardViewSet):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .step(ReviewForm, context={"step_name": "review"})
    )
    template_name = "testapp/linear_wizard.html"

    def get_wizard_url(self, run_id):
        return f"/wizard/{run_id}/"

    def get_step_url(self, run_id, step_segment):
        return f"/wizard/{run_id}/{step_segment}/"

    def get_start_url(self):
        return "/wizard/"

    def done(self, bound_wizard):
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

    step_wizard = response.context_data["view"].request.wizard
    assert step_wizard.back_url == "/wizard/existing-run/first/"
    assert step_wizard.run_url == "/wizard/existing-run/"


def test_wizard_viewset_first_step_render_has_no_back_url(rf):
    request = rf.get("/wizard/existing-run/first/")
    request.session = _routed_session([])

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="first"
    )

    step_wizard = response.context_data["view"].request.wizard
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

    step_wizard = response.context_data["view"].request.wizard
    assert step_wizard.back_url == "/wizard/existing-run/first/"


def test_wizard_viewset_rejected_edit_render_annotates_back_url(rf):
    request = rf.post("/wizard/existing-run/second/", data={"email": ""})
    request.session = _routed_session(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ]
    )

    response = _RoutedViewSet.as_view()(
        request, run_id="existing-run", gandalf_step="second"
    )

    assert response.context_data["form"].errors
    step_wizard = response.context_data["view"].request.wizard
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


def test_wizard_viewset_routed_post_invalid_edit_renders_errors(rf):
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

    assert response.status_code == HTTPStatus.OK
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Ada"}},
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
        def run_unavailable(self, bound_wizard, reason):
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
            .step(FirstStepForm, context={"step_name": "first"})
            .step(SecondStepForm, context={"step_name": "second"})
            .configure(template_name="testapp/linear_wizard.html")
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
        wizard = wizard.step(form, context={"step_name": name})

    class _EscapingViewSet(_RoutedViewSet):
        pass

    _EscapingViewSet.wizard = wizard
    if done_body is not None:
        _EscapingViewSet.done = lambda self, bound_wizard: HttpResponse(
            done_body(bound_wizard)
        )
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
        done_body=lambda bound_wizard: ",".join(
            sorted(bound_wizard.runtime_tree.form.cleaned_data)
        ),
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


def test_wizard_viewset_editing_a_step_into_an_escape_stores_the_edit(rf):
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

    # Editing a completed step never escapes: the raise only marks the step
    # satisfied, so the edit is stored and the run carries on.
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/wizard/existing-run/second/"
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"email": "ada@example.com", "subscribe": "on"}},
    ]
