import tempfile
import uuid

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.views.generic.edit import FormView

import gandalf.wizard
from gandalf import tree
from gandalf.file_storage import WizardFileStorage
from gandalf.runtime import BoundWizard
from gandalf.wizard import ConfiguredWizard, Wizard
from tests.testapp.forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
    OptionalPhotoForm,
    PersonalDetailsForm,
    ProfilePhotoForm,
    ReviewForm,
    SecondStepForm,
)


def _replay(bound_wizard, *args, **kwargs):
    """Walk stored state and render the cursor, mirroring what the viewset
    does over HTTP; returns None when the run is complete."""
    cursor = bound_wizard.cursor(*args, **kwargs)
    if cursor.node is None:
        return None
    return bound_wizard.dispatcher.render_cursor(cursor, *args, **kwargs)


def _make_bound_wizard(wizard, request):
    return BoundWizard(request, wizard.storage_class(request), wizard=wizard)


@pytest.fixture
def temp_file_storage_class():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileSystemStorage(location=tmpdir)

        class TempFileStorage(WizardFileStorage):
            def __init__(self):
                super().__init__(backend=backend)

        yield TempFileStorage


class _Session(dict):
    modified = False


@pytest.fixture
def request_with_session_factory(rf):
    def build_request(path="/wizard/", data=None, method="get", session=None):
        request_factory_method = getattr(rf, method)
        request = request_factory_method(path, data=data or {})
        request.session = _Session()
        if session:
            request.session.update(session)
        return request

    return build_request


@pytest.fixture
def linear_wizard():
    return (
        Wizard()
        .step(
            FirstStepForm,
        )
        .step(
            SecondStepForm,
        )
        .configure(template_name="testapp/linear_wizard.html")
    )


def test_declared_form_step_stores_form_class():
    wizard = Wizard()

    returned_wizard = wizard.step(FirstStepForm)

    assert returned_wizard is not wizard
    assert wizard.tree is None
    assert returned_wizard.tree == tree.Step(declaration=FirstStepForm)


def test_module_step_entry_point_returns_wizard_with_first_step():
    returned = gandalf.wizard.step(FirstStepForm, context={"step_name": "first"})

    assert isinstance(returned, Wizard)
    assert returned.tree == tree.Step(
        declaration=FirstStepForm,
        context={"step_name": "first"},
    )


def test_named_sets_step_name_context():
    wizard = Wizard().step(gandalf.wizard.named("first", FirstStepForm))

    assert wizard.tree == tree.Step(
        declaration=FirstStepForm,
        context={"step_name": "first"},
    )


def test_named_merges_with_explicit_context():
    wizard = Wizard().step(
        gandalf.wizard.named("first", FirstStepForm),
        context={"analytics_key": "x"},
    )

    assert wizard.tree.context == {"step_name": "first", "analytics_key": "x"}


def test_named_explicit_context_step_name_overrides_named():
    wizard = Wizard().step(
        gandalf.wizard.named("first", FirstStepForm),
        context={"step_name": "override"},
    )

    assert wizard.tree.context == {"step_name": "override"}


def test_module_step_entry_point_accepts_named():
    wizard = gandalf.wizard.step(gandalf.wizard.named("first", FirstStepForm))

    assert wizard.tree == tree.Step(
        declaration=FirstStepForm,
        context={"step_name": "first"},
    )


def test_module_branch_entry_point_returns_wizard_with_first_branch():
    sub_wizard = gandalf.wizard.step(FirstStepForm)
    returned = gandalf.wizard.branch(
        gandalf.wizard.condition(lambda request: True, sub_wizard),
        default=gandalf.wizard.step(SecondStepForm),
    )

    assert isinstance(returned, Wizard)
    assert isinstance(returned.tree, tree.Branch)


def test_declared_form_step_stores_context():
    wizard = Wizard()

    returned_wizard = wizard.step(FirstStepForm, context={"step_name": "first"})

    assert returned_wizard.tree == tree.Step(
        declaration=FirstStepForm,
        context={"step_name": "first"},
    )


def test_bound_wizard_find_step_returns_matching_runtime_step(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.runtime import RuntimeStep

    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    found = bound_wizard.find_step(step_name="second")

    assert isinstance(found, RuntimeStep)
    assert found.declaration.declaration is SecondStepForm
    assert found.declaration.context == {"step_name": "second"}


def test_bound_wizard_find_step_on_branching_wizard_finds_step_in_active_arm(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def is_business_account(request):
        return False

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, context={"step_name": "business"}),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"step_name": "personal"}
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"account_type": "personal"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    personal_step = bound_wizard.find_step(step_name="personal")

    assert isinstance(personal_step, RuntimeStep)
    assert personal_step.declaration.declaration is PersonalDetailsForm


def test_bound_wizard_find_step_returns_none_inside_unreached_branch(
    request_with_session_factory,
):
    def is_business_account(request):
        return False

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, context={"step_name": "business"}),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"step_name": "personal"}
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.find_step(step_name="personal") is None
    review_step = bound_wizard.find_step(step_name="review")
    assert review_step is not None
    assert review_step.data is None


def test_bound_wizard_find_step_returns_none_for_step_in_inactive_arm(
    request_with_session_factory,
):
    def is_business_account(request):
        return False

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, context={"step_name": "business"}),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"step_name": "personal"}
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.find_step(step_name="business") is None


def test_bound_wizard_find_step_returns_none_when_no_match(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.find_step(step_name="missing") is None


def test_reducer_supports_custom_initial_and_combine_for_non_list_folds():
    from gandalf.runtime import RuntimeStep

    step2 = RuntimeStep(declaration=tree.Step(FirstStepForm), data={"value": 2})
    step1 = RuntimeStep(
        declaration=tree.Step(FirstStepForm), data={"value": 1}, next=step2
    )

    class SumReducer(tree.Reducer):
        def initial(self):
            return 0

        def combine(self, accumulator, value):
            return accumulator + value

        def visit_step(self, step):
            return step.data["value"]

        def visit_branch(self, branch, sub_result):
            return sub_result

    assert SumReducer().reduce(step1) == 3


def test_reducer_visits_runtime_chain_and_collects_per_node_values():
    from gandalf.runtime import RuntimeBranch, RuntimeStep

    arm_step = RuntimeStep(declaration=tree.Step(FirstStepForm), data={"b": 2})
    step1 = RuntimeStep(declaration=tree.Step(FirstStepForm), data={"a": 1})
    branch = RuntimeBranch(declaration=tree.Branch(arms=()), selected_arm=arm_step)
    step1.next = branch

    class DictReducer(tree.Reducer):
        def visit_step(self, step):
            return {"step": step.data}

        def visit_branch(self, branch, sub_result):
            return {"branch": sub_result}

    result = DictReducer().reduce(step1)

    assert result == [
        {"step": {"a": 1}},
        {"branch": [{"step": {"b": 2}}]},
    ]


def test_bound_wizard_filter_steps_returns_matches_in_walk_order(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"kind": "data"})
        .step(SecondStepForm, context={"kind": "data"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    matches = bound_wizard.filter_steps(kind="data")

    assert [step.declaration.declaration for step in matches] == [
        FirstStepForm,
        SecondStepForm,
    ]


def test_step_builder_does_not_mutate_source_wizard():
    base_wizard = Wizard().step(FirstStepForm)

    derived_wizard = base_wizard.step(SecondStepForm)

    base_nodes = list(base_wizard.tree)
    derived_nodes = list(derived_wizard.tree)

    assert len(base_nodes) == 1
    assert base_nodes[0].declaration is FirstStepForm
    assert len(derived_nodes) == 2
    assert derived_nodes[0].declaration is FirstStepForm
    assert derived_nodes[1].declaration is SecondStepForm


def test_step_builder_allows_independent_variants():
    base_wizard = Wizard().step(FirstStepForm)

    first_variant = base_wizard.step(SecondStepForm)
    second_variant = base_wizard.step(FirstStepForm)

    base_nodes = list(base_wizard.tree)
    first_nodes = list(first_variant.tree)
    second_nodes = list(second_variant.tree)

    assert len(base_nodes) == 1
    assert [node.declaration for node in first_nodes] == [
        FirstStepForm,
        SecondStepForm,
    ]
    assert [node.declaration for node in second_nodes] == [
        FirstStepForm,
        FirstStepForm,
    ]


def test_wizard_does_not_proxy_bound_wizard_lifecycle_methods():
    wizard = Wizard()

    assert not hasattr(wizard, "initialise")
    assert not hasattr(wizard, "bind")


def test_get_bound_wizard_uses_configured_storage_class(request_with_session_factory):
    class FakeStorage:
        def __init__(self, request):
            self.request = request

    request = request_with_session_factory()
    wizard = Wizard().configure(storage_class=FakeStorage)

    bound_wizard = _make_bound_wizard(wizard, request)

    assert isinstance(bound_wizard.storage, FakeStorage)
    assert bound_wizard.storage.request is request


def test_configured_wizard_uses_configured_step_dispatcher_class(
    request_with_session_factory,
):
    captured = {}

    class FakeDispatcher:
        def __init__(self, bound_wizard):
            captured["bound_wizard"] = bound_wizard

        def dispatch(self, *args, **kwargs):
            raise AssertionError("dispatch should not be called by this test")

        def build_request(self, method, submission=None):
            raise AssertionError("build_request should not be called by this test")

        def response_satisfies_step(self, response):
            return True

        def render_cursor(self, cursor, *args, **kwargs):
            return cursor

    request = request_with_session_factory()
    wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            step_dispatcher_class=FakeDispatcher,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)

    assert isinstance(bound_wizard.dispatcher, FakeDispatcher)
    assert captured["bound_wizard"] is bound_wizard


def test_bound_wizard_edit_with_invalid_submission_past_branch_keeps_state(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.edit({}, step_name="review")

    assert response.context_data["form"].errors == {
        "confirmed": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
        {"step": {"confirmed": "on"}},
    ]


def test_configured_wizard_uses_configured_cursor_walker_class(
    request_with_session_factory,
):
    from gandalf.runtime import Cursor

    calls = []

    class FakeWalker:
        def __init__(
            self,
            dispatcher,
            entries,
            pending_submission,
            args,
            kwargs,
            bound_wizard,
            pending_files=None,
        ):
            calls.append(("init", pending_submission))

        def walk(self, root):
            calls.append(("walk", root))

        def cursor(self):
            return Cursor(node=None, state=None)

    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            cursor_walker_class=FakeWalker,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"})

    assert calls[0] == ("init", {"name": "Ada"})


def test_configured_wizard_uses_configured_form_view_factory():
    sentinel = type("SentinelView", (FormView,), {"form_class": FirstStepForm})

    def fake_factory(form_class, *, template_name):
        return sentinel

    wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            form_view_factory=fake_factory,
        )
    )

    assert wizard.tree.form_view is sentinel


def test_configured_wizard_uses_configured_state_serializer_class(
    request_with_session_factory,
):
    class FakeSerializer:
        def reduce(self, root):
            return ["fake-entry"]

    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            state_serializer_class=FakeSerializer,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"})

    assert request.session["gandalf_runs"]["existing-run"]["state"] == ["fake-entry"]


def test_wizard_configure_returns_configured_wizard():
    wizard = Wizard()

    configured_wizard = wizard.configure()

    assert isinstance(configured_wizard, ConfiguredWizard)
    assert configured_wizard.configuration == {}


def test_configured_wizard_configure_raises_useful_error():
    configured_wizard = Wizard().configure()

    with pytest.raises(
        ImproperlyConfigured,
        match="ConfiguredWizard instances cannot be configured.",
    ):
        configured_wizard.configure(template_name="testapp/linear_wizard.html")


def test_wizard_configure_requires_template_for_form_steps():
    wizard = Wizard().step(FirstStepForm)

    with pytest.raises(
        ImproperlyConfigured,
        match=(
            "Wizard.configure\\(\\) must receive template_name when generating "
            "FormView steps from Form classes."
        ),
    ):
        wizard.configure()


def test_wizard_configure_generates_form_views_for_form_steps():
    wizard = Wizard().step(FirstStepForm)

    configured_wizard = wizard.configure(template_name="testapp/linear_wizard.html")

    configured_step = configured_wizard.tree
    assert configured_step.declaration is FirstStepForm
    assert issubclass(configured_step.form_view, FormView)
    assert configured_step.form_view.form_class is FirstStepForm
    assert configured_step.form_view.template_name == "testapp/linear_wizard.html"
    assert wizard.tree == tree.Step(declaration=FirstStepForm)


def test_wizard_configure_applies_template_to_generated_form_views():
    wizard = Wizard().step(FirstStepForm)

    configured_wizard = wizard.configure(template_name="testapp/linear_wizard.html")

    configured_step = configured_wizard.tree
    assert configured_step.declaration is FirstStepForm
    assert configured_step.form_view.form_class is FirstStepForm
    assert configured_step.form_view.template_name == "testapp/linear_wizard.html"
    assert wizard.tree == tree.Step(declaration=FirstStepForm)


def test_wizard_configure_preserves_explicit_form_view_steps():
    class ExplicitStepView(FormView):
        form_class = FirstStepForm
        template_name = "testapp/explicit_step.html"

    wizard = Wizard().step(ExplicitStepView)

    configured_wizard = wizard.configure(template_name="testapp/linear_wizard.html")

    assert configured_wizard.tree == tree.Step(
        declaration=ExplicitStepView,
        form_view=ExplicitStepView,
    )


def test_bound_wizard_initialise_creates_session_run(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()
    bound_wizard = _make_bound_wizard(linear_wizard, request)

    bound_wizard.initialise()

    assert uuid.UUID(bound_wizard.run_id)
    assert request.session["gandalf_runs"] == {
        bound_wizard.run_id: {},
    }


def test_bound_wizard_initialise_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()
    bound_wizard = _make_bound_wizard(linear_wizard, request)

    bound_wizard.initialise()

    assert request.session.modified is True


def test_bound_wizard_replays_submissions_from_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )

    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")
    response = _replay(bound_wizard)

    assert bound_wizard.run_id == "existing-run"
    assert response.context_data["form"].__class__ is SecondStepForm


def test_bound_wizard_replays_submissions_from_uuid_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    run_id = uuid.uuid4()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                str(run_id): {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )

    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve(run_id)
    response = _replay(bound_wizard)

    assert bound_wizard.run_id == run_id
    assert response.context_data["form"].__class__ is SecondStepForm


def test_bound_wizard_retrieve_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )

    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    assert request.session.modified is True


def test_bound_wizard_get_run_data_returns_current_run_data(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    run_data = bound_wizard.get_run_data()

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_bound_wizard_replays_submissions_to_render_next_form_view(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"})
    response = _replay(bound_wizard)

    assert response.context_data["form"].__class__ is SecondStepForm


def test_bound_wizard_renders_first_step_in_matching_branch(
    request_with_session_factory,
):
    class AccountTypeForm(forms.Form):
        account_type = forms.ChoiceField(
            choices=[
                ("personal", "Personal"),
                ("business", "Business"),
            ],
        )

    class BusinessDetailsForm(forms.Form):
        business_name = forms.CharField()

    class PersonalDetailsForm(forms.Form):
        preferred_name = forms.CharField()

    class ReviewForm(forms.Form):
        confirmed = forms.BooleanField()

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"account_type": "business"})
    response = _replay(bound_wizard)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is BusinessDetailsForm


def test_bound_wizard_renders_first_step_in_default_branch(
    request_with_session_factory,
):
    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"account_type": "personal"})
    response = _replay(bound_wizard)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is PersonalDetailsForm


def test_bound_wizard_submit_inside_branch_arm_records_nested_state(
    request_with_session_factory,
):
    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"account_type": "business"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"business_name": "Acme"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"account_type": "business"}},
            {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        ],
    }


def test_bound_wizard_submit_after_completed_branch_arm_appends_at_top_level(
    request_with_session_factory,
):
    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"confirmed": "on"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"account_type": "business"}},
            {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
            {"step": {"confirmed": "on"}},
        ],
    }


def test_bound_wizard_replay_returns_invalid_stored_step_response(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": ""}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    response = _replay(bound_wizard)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is FirstStepForm
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }


def test_bound_wizard_persists_submissions_by_url_run_id(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"})

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "state": [{"step": {"name": "Ada"}}],
        },
    }


def test_bound_wizard_submissions_are_isolated_between_url_run_ids(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "first-run": {},
                "second-run": {},
            },
        },
    )
    first_bound_wizard = _make_bound_wizard(linear_wizard, request)
    first_bound_wizard.retrieve("first-run")

    first_bound_wizard.submit({"name": "Ada"})
    second_bound_wizard = _make_bound_wizard(linear_wizard, request)
    second_bound_wizard.retrieve("second-run")
    first_response = _replay(first_bound_wizard)
    second_response = _replay(second_bound_wizard)

    assert first_response.context_data["form"].__class__ is SecondStepForm
    assert second_response.context_data["form"].__class__ is FirstStepForm


def test_bound_wizard_preserves_valid_previous_submissions_when_updating_next_step(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"email": "ada@example.com"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ],
    }


def test_bound_wizard_replaces_invalid_stored_submission(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": ""}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"name": "Ada"}},
        ],
    }


def test_bound_wizard_does_not_append_submission_after_complete_path(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"email": "grace@example.com"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ],
    }


def test_bound_wizard_replay_returns_none_after_complete_path(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    response = _replay(bound_wizard)

    assert response is None


def test_bound_wizard_render_edit_returns_form_with_initial_from_stored_data(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.render_edit(step_name="first")

    assert response.status_code == 200
    form = response.context_data["form"]
    assert form.__class__ is FirstStepForm
    assert form.is_bound is False
    assert form.initial == {"name": "Ada"}


def test_bound_wizard_render_edit_finds_step_inside_branch(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"step_name": "business_name"}
                ),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"step_name": "personal_name"}
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.render_edit(step_name="business_name")

    form = response.context_data["form"]
    assert form.__class__ is BusinessDetailsForm
    assert form.initial == {"business_name": "Acme"}


def test_bound_wizard_render_edit_raises_step_not_found_for_unknown_context(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.runtime import StepNotFound

    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    with pytest.raises(StepNotFound):
        bound_wizard.render_edit(step_name="missing")


def test_bound_wizard_edit_replaces_step_data_and_preserves_downstream(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"name": "Grace"}, step_name="first")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Grace"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_bound_wizard_edit_with_invalid_submission_returns_error_render(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.edit({"name": ""}, step_name="first")

    assert response.context_data["form"].__class__ is FirstStepForm
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Ada"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_bound_wizard_edit_with_valid_submission_returns_none(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.edit({"name": "Grace"}, step_name="first") is None


def test_bound_wizard_edit_preserves_branch_state_when_arm_unchanged(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"account_type": "business"}, step_name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_bound_wizard_edit_keeps_dormant_arm_state_when_arm_changes(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"account_type": "personal"}, step_name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]
    response = _replay(bound_wizard)
    assert response.context_data["form"].__class__ is PersonalDetailsForm


def test_bound_wizard_edit_step_inside_branch_replaces_nested_entry(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"step_name": "business_name"}
                ),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"business_name": "Globex"}, step_name="business_name")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Globex"}}]}},
    ]


def _branching_review_wizard():
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    return (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"step_name": "business_name"}
                ),
            ),
            default=Wizard().step(
                PersonalDetailsForm, context={"step_name": "preferred_name"}
            ),
        )
        .step(ReviewForm, context={"step_name": "review"})
        .configure(template_name="testapp/linear_wizard.html")
    )


def test_bound_wizard_cursor_returns_first_unanswered_step(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    cursor = bound_wizard.cursor()

    assert cursor.node.matches_context(step_name="second")


def test_bound_wizard_cursor_node_is_none_when_run_is_complete(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.cursor().node is None


def test_bound_wizard_find_step_at_sees_preserved_tail_but_not_dormant_arms(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "personal"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    cursor = bound_wizard.cursor()

    preserved = bound_wizard.find_step_at(cursor, step_name="review")
    dormant = bound_wizard.find_step_at(cursor, step_name="business_name")
    at_cursor = bound_wizard.find_step_at(cursor, step_name="preferred_name")

    assert preserved.data == {"confirmed": "on"}
    assert dormant is None
    assert at_cursor.declaration is cursor.node


def test_bound_wizard_previous_step_walks_the_active_route(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    cursor = bound_wizard.cursor()

    account = bound_wizard.find_step_at(cursor, step_name="account_type")
    business = bound_wizard.find_step_at(cursor, step_name="business_name")
    review = bound_wizard.find_step_at(cursor, step_name="review")

    assert bound_wizard.previous_step(cursor, account.declaration) is None
    assert (
        bound_wizard.previous_step(cursor, business.declaration).declaration
        is account.declaration
    )
    assert (
        bound_wizard.previous_step(cursor, review.declaration).declaration
        is business.declaration
    )


def test_bound_wizard_previous_step_is_none_for_unknown_declaration(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    cursor = bound_wizard.cursor()

    foreign_declaration = tree.Step(FirstStepForm)

    assert bound_wizard.previous_step(cursor, foreign_declaration) is None


def test_bound_wizard_previous_step_is_none_behind_a_preserved_branch(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": None},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    cursor = bound_wizard.cursor()

    review = bound_wizard.find_step_at(cursor, step_name="review")

    assert bound_wizard.previous_step(cursor, review.declaration) is None


def _cross_branch_wizard():
    """Wizard whose second branch's predicate dereferences a step inside the
    first branch's business arm — the issue #45 crash shape when that step
    is dormant or unanswered."""
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    def business_was_acme(request):
        business_step = request.wizard.find_step(step_name="business_name")
        return business_step.data["business_name"] == "Acme"

    return (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="preferred_name"),
        )
        .branch(
            gandalf.wizard.condition(
                business_was_acme,
                Wizard().step(SecondStepForm, name="second"),
            ),
        )
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )


def test_bound_wizard_edit_succeeds_with_cross_branch_predicate_mid_divert(
    request_with_session_factory,
):
    wizard = _cross_branch_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "personal"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                        {"branch": {"0": [{"step": {"email": "ada@example.com"}}]}},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert (
        bound_wizard.edit({"account_type": "personal"}, step_name="account_type")
        is None
    )
    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0] == {"step": {"account_type": "personal"}}
    assert state[1] == {"branch": {"0": [{"step": {"business_name": "Acme"}}]}}


def test_bound_wizard_path_is_safe_with_cross_branch_predicate_mid_divert(
    request_with_session_factory,
):
    wizard = _cross_branch_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "personal"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                        {"branch": {"0": [{"step": {"email": "ada@example.com"}}]}},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    names = [step.declaration.context["step_name"] for step in _iter_path(bound_wizard)]

    assert names == ["account_type", "review"]


def _iter_path(bound_wizard):
    node = bound_wizard.path
    while node is not None:
        yield node
        node = node.next


class _StubUrls:
    def get_wizard_url(self, run_id):
        return f"/wizard/{run_id}/"

    def get_step_url(self, run_id, step_segment):
        return f"/wizard/{run_id}/{step_segment}/"


def test_bound_wizard_back_and_run_urls_derive_from_render_context(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    bound_wizard.urls = _StubUrls()
    cursor = bound_wizard.cursor()

    bound_wizard.mark_rendering(cursor, cursor.node)

    assert bound_wizard.back_url == "/wizard/existing-run/business_name/"
    assert bound_wizard.run_url == "/wizard/existing-run/"


def test_bound_wizard_back_url_is_none_at_the_first_step(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    bound_wizard.urls = _StubUrls()
    cursor = bound_wizard.cursor()

    bound_wizard.mark_rendering(cursor, cursor.node)

    assert bound_wizard.back_url is None
    assert bound_wizard.run_url == "/wizard/existing-run/"


def test_bound_wizard_runtime_tree_reuses_the_render_context_walk(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"account_type": "business"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    cursor = bound_wizard.cursor()

    bound_wizard.mark_rendering(cursor, cursor.node)

    assert bound_wizard.runtime_tree is cursor.state


def test_bound_wizard_nav_urls_are_none_without_reverser_or_render_context(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.back_url is None
    assert bound_wizard.run_url is None

    bound_wizard.urls = _StubUrls()

    assert bound_wizard.back_url is None
    assert bound_wizard.run_url == "/wizard/existing-run/"


def test_bound_wizard_edit_changing_arm_preserves_answers_after_branch(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"account_type": "personal"}, step_name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        {"step": {"confirmed": "on"}},
    ]
    response = _replay(bound_wizard)
    assert response.context_data["form"].__class__ is PersonalDetailsForm


def test_bound_wizard_submit_fills_hole_and_completes_preserved_run(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "personal"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"preferred_name": "Ada"})

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "personal"}},
        {
            "branch": {
                "0": [{"step": {"business_name": "Acme"}}],
                "default": [{"step": {"preferred_name": "Ada"}}],
            }
        },
        {"step": {"confirmed": "on"}},
    ]
    assert _replay(bound_wizard) is None


def test_bound_wizard_edit_flip_flop_restores_dormant_arm_answers(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"account_type": "personal"}, step_name="account_type")
    bound_wizard.edit({"account_type": "business"}, step_name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]
    response = _replay(bound_wizard)
    assert response.context_data["form"].__class__ is ReviewForm


def test_bound_wizard_edit_restoring_stale_dormant_answer_renders_errors(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "personal"}},
                        {
                            "branch": {
                                "0": [{"step": {"business_name": ""}}],
                                "default": [{"step": {"preferred_name": "Ada"}}],
                            }
                        },
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"account_type": "business"}, step_name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {
            "branch": {
                "0": [{"step": {"business_name": ""}}],
                "default": [{"step": {"preferred_name": "Ada"}}],
            }
        },
    ]
    response = _replay(bound_wizard)
    assert response.context_data["form"].__class__ is BusinessDetailsForm
    assert response.context_data["form"].errors == {
        "business_name": ["This field is required."],
    }


def test_bound_wizard_edit_keeps_invalid_downstream_answer_for_correction(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .step(SecondStepForm, context={"step_name": "second"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "not-an-email"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"name": "Grace"}, step_name="first")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Grace"}},
        {"step": {"email": "not-an-email"}},
    ]
    response = _replay(bound_wizard)
    assert response.context_data["form"].__class__ is SecondStepForm
    assert response.context_data["form"].errors == {
        "email": ["Enter a valid email address."],
    }


def test_bound_wizard_edit_raises_step_not_found_for_unknown_context(
    request_with_session_factory,
):
    from gandalf.runtime import StepNotFound

    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "first"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    with pytest.raises(StepNotFound):
        bound_wizard.edit({"name": "Grace"}, step_name="missing")


def test_bound_wizard_edit_with_invalid_submission_inside_branch_keeps_state(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"step_name": "business_name"}
                ),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.edit({"business_name": ""}, step_name="business_name")

    assert response.context_data["form"].errors == {
        "business_name": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]


def test_bound_wizard_edit_raises_when_context_matches_multiple_active_steps(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, context={"step_name": "duplicate"})
        .step(SecondStepForm, context={"step_name": "duplicate"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    with pytest.raises(tree.MultipleStepsReturned):
        bound_wizard.edit({"name": "Grace"}, step_name="duplicate")


def test_bound_wizard_edit_does_not_mutate_original_stored_state(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(
                    BusinessDetailsForm, context={"step_name": "business_name"}
                ),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .configure(template_name="testapp/linear_wizard.html")
    )
    stored_state = [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": stored_state,
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.edit({"business_name": "Globex"}, step_name="business_name")

    assert stored_state == [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]


def test_bound_wizard_replays_submissions_through_form_view_form_valid(
    request_with_session_factory,
    linear_wizard,
):
    class TrackingFirstStepFormView(FormView):
        form_class = FirstStepForm
        form_valid_call_count = 0

        def get_success_url(self):
            return self.request.path

        def form_valid(self, form):
            self.__class__.form_valid_call_count += 1
            return super().form_valid(form)

    linear_wizard = (
        Wizard()
        .step(TrackingFirstStepFormView)
        .step(SecondStepForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    response = _replay(bound_wizard)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is SecondStepForm
    assert TrackingFirstStepFormView.form_valid_call_count == 1


def test_runtime_step_form_exposes_cleaned_data_for_completed_step(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    first_step = bound_wizard.runtime_tree

    assert isinstance(first_step.form, FirstStepForm)
    assert first_step.form.is_valid()
    assert first_step.form.cleaned_data == {"name": "Ada"}


def test_runtime_step_data_still_exposes_raw_submission(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    first_step = bound_wizard.runtime_tree

    assert first_step.data == {"name": "Ada"}


def test_runtime_step_form_reflects_cleaned_values_not_raw_strings(
    request_with_session_factory,
):
    class CoercingForm(forms.Form):
        count = forms.IntegerField()

    wizard = (
        Wizard()
        .step(CoercingForm)
        .configure(template_name="testapp/single_step_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"count": "42"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    first_step = bound_wizard.runtime_tree

    assert first_step.data == {"count": "42"}
    assert first_step.form.cleaned_data == {"count": 42}


def test_bound_wizard_path_is_none_when_no_steps_complete(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    assert bound_wizard.path is None


def test_bound_wizard_path_for_linear_wizard_includes_only_completed_steps(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.runtime import RuntimeStep

    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    path = bound_wizard.path

    assert isinstance(path, RuntimeStep)
    assert path.declaration.declaration is FirstStepForm
    assert path.data == {"name": "Ada"}
    assert path.next is None


def test_bound_wizard_path_inlines_completed_branch_arm_steps(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def is_business(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    path = bound_wizard.path

    assert isinstance(path, RuntimeStep)
    assert path.declaration.declaration is AccountTypeForm
    assert isinstance(path.next, RuntimeStep)
    assert path.next.declaration.declaration is BusinessDetailsForm
    assert path.next.next is None


def test_bound_wizard_path_walkable_by_tree_reducer_to_merge_cleaned_data(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    class MergeCleanedData(tree.Reducer):
        def initial(self):
            return {}

        def combine(self, accumulator, value):
            return {**accumulator, **value}

        def visit_step(self, runtime_step):
            return runtime_step.form.cleaned_data

    payload = MergeCleanedData().reduce(bound_wizard.path)

    assert payload == {"name": "Ada", "email": "ada@example.com"}


def test_runtime_step_form_reconstructs_cleaned_data_for_form_view_step(
    request_with_session_factory,
):
    class FirstStepFormView(FormView):
        form_class = FirstStepForm
        template_name = "testapp/single_step_wizard.html"

        def get_success_url(self):
            return self.request.path

    wizard = (
        Wizard()
        .step(FirstStepFormView)
        .configure(template_name="testapp/single_step_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    runtime_step = bound_wizard.runtime_tree

    assert runtime_step.form.cleaned_data == {"name": "Ada"}


def test_runtime_step_form_honors_form_view_get_form_class_override(
    request_with_session_factory,
):
    class TwoNameForm(forms.Form):
        full_name = forms.CharField()

    class FormClassPickingView(FormView):
        template_name = "testapp/single_step_wizard.html"
        use_two_name_form = True

        def get_form_class(self):
            return TwoNameForm if self.use_two_name_form else FirstStepForm

        def get_success_url(self):
            return self.request.path

    wizard = (
        Wizard()
        .step(FormClassPickingView)
        .configure(template_name="testapp/single_step_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"full_name": "Ada Lovelace"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    form = bound_wizard.runtime_tree.form

    assert isinstance(form, TwoNameForm)
    assert form.cleaned_data == {"full_name": "Ada Lovelace"}


def test_runtime_step_form_honors_form_view_get_form_kwargs_override(
    request_with_session_factory,
):
    class GreetingForm(forms.Form):
        greeting = forms.CharField()

        def __init__(self, *args, salutation, **kwargs):
            super().__init__(*args, **kwargs)
            self.salutation = salutation

    class SalutationInjectingView(FormView):
        form_class = GreetingForm
        template_name = "testapp/single_step_wizard.html"

        def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs["salutation"] = "Captain"
            return kwargs

        def get_success_url(self):
            return self.request.path

    wizard = (
        Wizard()
        .step(SalutationInjectingView)
        .configure(template_name="testapp/single_step_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"greeting": "Ahoy"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    form = bound_wizard.runtime_tree.form

    assert form.cleaned_data == {"greeting": "Ahoy"}
    assert form.salutation == "Captain"


def test_runtime_step_form_merges_cleaned_data_across_form_and_form_view_steps(
    request_with_session_factory,
):
    class SecondStepFormView(FormView):
        form_class = SecondStepForm
        template_name = "testapp/linear_wizard.html"

        def get_success_url(self):
            return self.request.path

    wizard = (
        Wizard()
        .step(FirstStepForm)
        .step(SecondStepFormView)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    payload = gandalf.wizard.MergeCleanedData().reduce(bound_wizard.path)

    assert payload == {"name": "Ada", "email": "ada@example.com"}


def test_splice_submission_preserves_bound_wizard_for_form_access(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.runtime import SpliceSubmission

    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    runtime = bound_wizard.runtime_tree
    spliced = SpliceSubmission(runtime, {"name": "Grace"}).transform(runtime)

    assert spliced.bound_wizard is bound_wizard
    assert spliced.form.cleaned_data == {"name": "Grace"}


def test_bound_wizard_path_drops_branch_with_unmatched_no_default_arm(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def never(request):
        return False

    wizard = (
        Wizard()
        .step(FirstStepForm)
        .branch(
            gandalf.wizard.condition(never, Wizard().step(SecondStepForm)),
        )
        .step(AccountTypeForm, context={"step_name": "after_branch"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"branch": []},
                        {"step": {"account_type": "personal"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    path = bound_wizard.path

    assert isinstance(path, RuntimeStep)
    assert path.declaration.declaration is FirstStepForm
    assert isinstance(path.next, RuntimeStep)
    assert path.next.declaration.declaration is AccountTypeForm
    assert path.next.next is None


def test_bound_wizard_path_walks_multi_step_branch_arm(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def is_business(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business,
                Wizard().step(BusinessDetailsForm).step(SecondStepForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {
                            "branch": [
                                {"step": {"business_name": "Acme"}},
                                {"step": {"email": "acme@example.com"}},
                            ]
                        },
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    path = bound_wizard.path

    assert isinstance(path, RuntimeStep)
    assert path.declaration.declaration is AccountTypeForm
    assert path.next.declaration.declaration is BusinessDetailsForm
    assert path.next.next.declaration.declaration is SecondStepForm
    assert path.next.next.next.declaration.declaration is ReviewForm
    assert path.next.next.next.next is None


def test_merge_cleaned_data_folds_path_into_dict(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.wizard import MergeCleanedData

    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {"step": {"email": "ada@example.com"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(linear_wizard, request)
    bound_wizard.retrieve("existing-run")

    payload = MergeCleanedData().reduce(bound_wizard.path)

    assert payload == {"name": "Ada", "email": "ada@example.com"}


def test_merge_cleaned_data_folds_runtime_tree_across_branch(
    request_with_session_factory,
):
    from gandalf.wizard import MergeCleanedData

    def is_business(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "business"}},
                        {"branch": [{"step": {"business_name": "Acme"}}]},
                        {"step": {"confirmed": "on"}},
                    ],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    payload = MergeCleanedData().reduce(bound_wizard.runtime_tree)

    assert payload == {
        "account_type": "business",
        "business_name": "Acme",
        "confirmed": True,
    }


def test_step_view_can_read_request_wizard_path_mid_wizard(
    request_with_session_factory,
):
    captured = {}

    class CapturingSecondStepView(FormView):
        form_class = SecondStepForm
        template_name = "testapp/linear_wizard.html"

        def get_initial(self):
            path = self.request.wizard.path
            captured["path_head_name"] = (
                path.form.cleaned_data["name"] if path else None
            )
            return super().get_initial()

    wizard = (
        Wizard()
        .step(FirstStepForm)
        .step(CapturingSecondStepView)
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = _replay(bound_wizard)

    assert response.status_code == 200
    assert captured["path_head_name"] == "Ada"


def test_bound_wizard_submit_with_files_persists_file_refs_in_state(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm)
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = bound_wizard.file_storage.save(bound_wizard.run_id, photo)

    bound_wizard.submit({"photo": "avatar.jpg"}, files={"photo": file_key})

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state == [
        {"step": {"photo": "avatar.jpg"}, "files": {"photo": file_key}},
    ]


def test_bound_wizard_replay_reconstitutes_uploaded_file_for_form_validation(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm)
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = bound_wizard.file_storage.save(bound_wizard.run_id, photo)
    bound_wizard.submit({"photo": "avatar.jpg"}, files={"photo": file_key})

    response = _replay(bound_wizard)

    assert response.status_code == 200
    response.render()
    assert b"name" in response.content


def test_bound_wizard_render_edit_passes_stored_file_as_initial(
    request_with_session_factory,
    temp_file_storage_class,
):
    captured = {}

    class CapturingProfileView(FormView):
        form_class = ProfilePhotoForm
        template_name = "testapp/linear_wizard.html"

        def get_success_url(self):
            return self.request.path

        def get_initial(self):
            captured["initial"] = super().get_initial()
            return captured["initial"]

    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(CapturingProfileView, context={"step_name": "photo"})
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = bound_wizard.file_storage.save(bound_wizard.run_id, photo)
    bound_wizard.submit({"photo": "avatar.jpg"}, files={"photo": file_key})

    bound_wizard.render_edit(step_name="photo")

    assert captured["initial"]["photo"].read() == b"binary"


def test_bound_wizard_edit_without_new_file_preserves_stored_ref(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, context={"step_name": "photo"})
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = bound_wizard.file_storage.save(bound_wizard.run_id, photo)
    bound_wizard.submit({"photo": "avatar.jpg"}, files={"photo": file_key})

    bound_wizard.edit({"photo": "avatar.jpg"}, step_name="photo")

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0]["files"] == {"photo": file_key}
    assert bound_wizard.file_storage.open(file_key).read() == b"binary"


def test_bound_wizard_edit_adds_file_to_step_that_had_no_files(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, context={"step_name": "photo"})
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    bound_wizard.submit({"label": "first"})
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    new_key = bound_wizard.file_storage.save(bound_wizard.run_id, photo)

    bound_wizard.edit(
        {"label": "first"},
        files={"photo": new_key},
        step_name="photo",
    )

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0]["files"] == {"photo": new_key}


def test_bound_wizard_edit_with_new_file_replaces_and_deletes_old(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, context={"step_name": "photo"})
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    old_photo = SimpleUploadedFile("v1.jpg", b"first")
    old_ref = bound_wizard.file_storage.save(bound_wizard.run_id, old_photo)
    bound_wizard.submit({"photo": "v1.jpg"}, files={"photo": old_ref})
    new_photo = SimpleUploadedFile("v2.jpg", b"second")
    new_ref = bound_wizard.file_storage.save(bound_wizard.run_id, new_photo)

    bound_wizard.edit(
        {"photo": "v2.jpg"},
        files={"photo": new_ref},
        step_name="photo",
    )

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0]["files"] == {"photo": new_ref}
    assert not bound_wizard.file_storage.backend.exists(old_ref["tmp_name"])
    assert bound_wizard.file_storage.open(new_ref).read() == b"second"


def test_bound_wizard_edit_rejected_deletes_new_files_and_keeps_old(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, context={"step_name": "photo"})
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    old_photo = SimpleUploadedFile("v1.jpg", b"first")
    old_ref = bound_wizard.file_storage.save(bound_wizard.run_id, old_photo)
    bound_wizard.submit(
        {"label": "Original", "photo": "v1.jpg"},
        files={"photo": old_ref},
    )
    new_photo = SimpleUploadedFile("v2.jpg", b"second")
    new_ref = bound_wizard.file_storage.save(bound_wizard.run_id, new_photo)

    response = bound_wizard.edit(
        {"label": "", "photo": "v2.jpg"},
        files={"photo": new_ref},
        step_name="photo",
    )

    assert response.context_data["form"].errors == {
        "label": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {
            "step": {"label": "Original", "photo": "v1.jpg"},
            "files": {"photo": old_ref},
        },
    ]
    assert not bound_wizard.file_storage.backend.exists(new_ref["tmp_name"])
    assert bound_wizard.file_storage.open(old_ref).read() == b"first"


def test_bound_wizard_edit_keeps_old_file_when_rewalk_raises(
    request_with_session_factory,
    temp_file_storage_class,
):
    from django.views.generic.edit import FormView

    class ExplodingStepView(FormView):
        form_class = SecondStepForm
        template_name = "testapp/linear_wizard.html"

        def post(self, request, *args, **kwargs):
            raise RuntimeError("downstream step exploded")

    wizard = (
        Wizard()
        .step(ProfilePhotoForm, context={"step_name": "photo"})
        .step(ExplodingStepView)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    old_photo = SimpleUploadedFile("v1.jpg", b"first")
    old_ref = bound_wizard.file_storage.save(bound_wizard.run_id, old_photo)
    bound_wizard.storage.set_state(
        "existing-run",
        [
            {"step": {"photo": "v1.jpg"}, "files": {"photo": old_ref}},
            {"step": {"email": "ada@example.com"}},
        ],
    )
    new_photo = SimpleUploadedFile("v2.jpg", b"second")
    new_ref = bound_wizard.file_storage.save(bound_wizard.run_id, new_photo)

    with pytest.raises(RuntimeError):
        bound_wizard.edit(
            {"photo": "v2.jpg"},
            files={"photo": new_ref},
            step_name="photo",
        )

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"photo": "v1.jpg"}, "files": {"photo": old_ref}},
        {"step": {"email": "ada@example.com"}},
    ]
    assert bound_wizard.file_storage.open(old_ref).read() == b"first"


def test_bound_wizard_edit_step_not_found_deletes_new_files(
    request_with_session_factory,
    temp_file_storage_class,
):
    from gandalf.runtime import StepNotFound

    wizard = (
        Wizard()
        .step(OptionalPhotoForm, context={"step_name": "photo"})
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("orphan.jpg", b"orphan-bytes")
    new_ref = bound_wizard.file_storage.save(bound_wizard.run_id, photo)

    with pytest.raises(StepNotFound):
        bound_wizard.edit(
            {"label": "ignored"},
            files={"photo": new_ref},
            step_name="missing",
        )

    assert not bound_wizard.file_storage.backend.exists(new_ref["tmp_name"])


def test_bound_wizard_submit_correction_keeps_stored_file_refs(
    request_with_session_factory,
    temp_file_storage_class,
):
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, context={"step_name": "photo"})
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("kept.jpg", b"kept-bytes")
    photo_ref = bound_wizard.file_storage.save(bound_wizard.run_id, photo)
    bound_wizard.submit({"label": "", "photo": "kept.jpg"}, files={"photo": photo_ref})

    bound_wizard.submit({"label": "Fixed", "photo": "kept.jpg"})

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {
            "step": {"label": "Fixed", "photo": "kept.jpg"},
            "files": {"photo": photo_ref},
        },
    ]


def test_bound_wizard_edit_error_render_receives_url_kwargs(
    request_with_session_factory,
):
    from django.views.generic.edit import FormView

    class KwargAwareStepView(FormView):
        form_class = FirstStepForm
        template_name = "testapp/linear_wizard.html"

        def get_success_url(self):
            return self.request.path

        def get_context_data(self, **context):
            context = super().get_context_data(**context)
            context["org"] = self.kwargs["org"]
            return context

    wizard = (
        Wizard()
        .step(KwargAwareStepView, context={"step_name": "first"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.edit(
        {"name": ""},
        url_kwargs={"org": "acme"},
        step_name="first",
    )

    assert response.context_data["org"] == "acme"
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }


def test_bound_wizard_render_edit_receives_url_kwargs(
    request_with_session_factory,
):
    from django.views.generic.edit import FormView

    class KwargAwareStepView(FormView):
        form_class = FirstStepForm
        template_name = "testapp/linear_wizard.html"

        def get_success_url(self):
            return self.request.path

        def get_context_data(self, **context):
            context = super().get_context_data(**context)
            context["org"] = self.kwargs["org"]
            return context

    wizard = (
        Wizard()
        .step(KwargAwareStepView, context={"step_name": "first"})
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.render_edit(
        url_kwargs={"org": "acme"},
        step_name="first",
    )

    assert response.context_data["org"] == "acme"
    assert response.context_data["form"].initial == {"name": "Ada"}


def test_bound_wizard_edit_changing_arm_keeps_dormant_file_refs(
    request_with_session_factory,
    temp_file_storage_class,
):
    import gandalf.wizard

    def is_business_account(request):
        account_step = request.wizard.find_step(step_name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, context={"step_name": "account_type"})
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(ProfilePhotoForm, context={"step_name": "photo"}),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    bound_wizard.submit({"account_type": "business"})
    photo = SimpleUploadedFile("logo.jpg", b"logo-bytes")
    photo_ref = bound_wizard.file_storage.save(bound_wizard.run_id, photo)
    bound_wizard.submit({"photo": "logo.jpg"}, files={"photo": photo_ref})

    bound_wizard.edit({"account_type": "personal"}, step_name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "personal"}},
        {
            "branch": {
                "0": [
                    {
                        "step": {"photo": "logo.jpg"},
                        "files": {"photo": photo_ref},
                    },
                ],
            }
        },
    ]
    assert bound_wizard.file_storage.open(photo_ref).read() == b"logo-bytes"


def test_bound_wizard_cleanup_files_wipes_run_prefix(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = bound_wizard.file_storage.save(bound_wizard.run_id, photo)
    bound_wizard.submit({"photo": "avatar.jpg"}, files={"photo": file_key})

    bound_wizard.cleanup_files()

    _, files = bound_wizard.file_storage.backend.listdir("gandalf/existing-run")
    assert files == []


def test_configured_wizard_uses_configured_file_storage_class(
    request_with_session_factory,
):
    calls = []

    class FakeFileStorage:
        def __init__(self):
            calls.append("init")

        def save(self, run_id, uploaded_file):
            calls.append(("save", run_id, uploaded_file.name))
            return f"fake/{uploaded_file.name}"

        def open(self, key):
            calls.append(("open", key))
            return SimpleUploadedFile(key.rsplit("/", 1)[-1], b"x")

        def delete_run(self, run_id):
            calls.append(("delete_run", run_id))

    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=FakeFileStorage,
        )
    )
    bound_wizard = _make_bound_wizard(wizard, request)
    bound_wizard.retrieve("existing-run")

    assert isinstance(bound_wizard.file_storage, FakeFileStorage)
    bound_wizard.cleanup_files()
    assert ("delete_run", "existing-run") in calls
