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
from gandalf.context import WizardContext
from gandalf.file_storage import WizardFileStorage
from gandalf.form_views import StepFormView
from gandalf.runtime import Run, StepNotFound
from gandalf.storage import SessionStorage
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
    ToppingsForm,
)
from tests.testapp.views import OpeningHoursStepView


def _replay(run, *args, **kwargs):
    """Walk stored state and render the cursor, mirroring what the viewset
    does over HTTP; returns None when the run is complete."""
    cursor = run.cursor(*args, **kwargs)
    if cursor.node is None:
        return None
    return run.dispatcher.render_cursor(cursor, *args, **kwargs)


def _make_run(wizard, request, storage_class=SessionStorage):
    """Mirrors `WizardViewSet._make_run`: storage comes from the
    viewset, not the wizard, because it has to exist before the wizard does."""
    context = WizardContext.from_request(request)
    return Run(context, storage_class(context), wizard=wizard)


def _submit(run, submission, **kwargs):
    """Place a submission at the cursor and store it — what the viewset does
    for a routed POST, with the claim taken from where the run actually is
    rather than from a URL. Walking and persisting are separate so the caller
    can settle escapes and dynamic reshapes before writing."""
    walk = run.walk(claim=run.cursor().node, submission=submission, **kwargs)
    run.persist(walk)
    return walk


def _edit(run, submission, *, files=None, url_kwargs=None, **context):
    """Place a submission at a named step. There is no separate edit path —
    a claim the run cannot reach places nothing, and its uploads are the
    caller's to clean up."""
    walk = run.walk(
        claim=context, submission=submission, files=files, **(url_kwargs or {})
    )
    if not walk.reached:
        run.delete_file_refs(files)
        raise StepNotFound(context)
    run.persist(walk)
    return walk


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
    returned = gandalf.wizard.step(FirstStepForm, name="first")

    assert isinstance(returned, Wizard)
    assert returned.tree == tree.Step(
        declaration=FirstStepForm,
        context={"name": "first"},
    )


def test_every_keyword_becomes_step_context():
    wizard = Wizard().step(FirstStepForm, name="first", analytics_key="x")

    assert wizard.tree.context == {"name": "first", "analytics_key": "x"}


def test_step_without_keywords_carries_no_context():
    wizard = Wizard().step(FirstStepForm)

    assert wizard.tree.context is None


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

    returned_wizard = wizard.step(FirstStepForm, name="first")

    assert returned_wizard.tree == tree.Step(
        declaration=FirstStepForm,
        context={"name": "first"},
    )


def test_run_find_step_returns_matching_runtime_step(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.runtime import RuntimeStep

    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    found = run.path.find_step(name="second")

    assert isinstance(found, RuntimeStep)
    assert found.declaration.declaration is SecondStepForm
    assert found.declaration.context == {"name": "second"}


def test_run_find_step_accepts_name_shorthand(
    request_with_session_factory,
    linear_wizard,
):
    from gandalf.runtime import RuntimeStep

    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    found = run.path.find_step(name="second")

    assert isinstance(found, RuntimeStep)
    assert found.declaration.declaration is SecondStepForm
    assert found.declaration.context == {"name": "second"}


def test_run_filter_steps_accepts_name_shorthand(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {"state": [{"step": {"name": "Ada"}}]},
            },
        },
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    matches = run.path.filter_steps(name="first")

    assert [match.declaration.declaration for match in matches] == [FirstStepForm]


def test_run_find_step_on_branching_wizard_finds_step_in_active_arm(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def is_business_account(request):
        return False

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"account_type": "personal"}},
                        {"branch": {"default": [{"step": {"preferred_name": "Ada"}}]}},
                    ],
                },
            },
        },
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    personal_step = run.path.find_step(name="personal")

    assert isinstance(personal_step, RuntimeStep)
    assert personal_step.declaration.declaration is PersonalDetailsForm


def test_run_find_step_returns_none_inside_unreached_branch(
    request_with_session_factory,
):
    def is_business_account(request):
        return False

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    # The run is empty, so nothing is on the resolved path yet: neither the
    # step inside the unreached branch nor the review step sitting past it.
    assert run.path.find_step(name="personal") is None
    assert run.path.find_step(name="review") is None


def test_run_find_step_returns_none_for_step_in_inactive_arm(
    request_with_session_factory,
):
    def is_business_account(request):
        return False

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    assert run.path.find_step(name="business") is None


def test_run_find_step_returns_none_when_no_match(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    assert run.path.find_step(name="missing") is None


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


def test_run_filter_steps_returns_matches_in_walk_order(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, kind="data")
        .step(SecondStepForm, kind="data")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    matches = run.path.filter_steps(kind="data")

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


def test_wizard_does_not_proxy_run_lifecycle_methods():
    wizard = Wizard()

    assert not hasattr(wizard, "initialise")
    assert not hasattr(wizard, "bind")


def test_run_uses_the_storage_class_it_is_given(
    request_with_session_factory,
):
    class FakeStorage:
        def __init__(self, context):
            self.context = context

    request = request_with_session_factory()
    wizard = Wizard().configure()

    run = _make_run(wizard, request, storage_class=FakeStorage)

    assert isinstance(run.storage, FakeStorage)
    assert run.storage.context is run.context


def test_configuring_storage_class_on_a_wizard_is_rejected():
    class FakeStorage:
        def __init__(self, request):
            self.request = request

    with pytest.raises(ImproperlyConfigured, match="WizardViewSet.storage_class"):
        Wizard().configure(storage_class=FakeStorage)


def test_configured_wizard_uses_configured_step_dispatcher_class(
    request_with_session_factory,
):
    captured = {}

    class FakeDispatcher:
        def __init__(self, run):
            captured["run"] = run

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
    run = _make_run(wizard, request)

    assert isinstance(run.dispatcher, FakeDispatcher)
    assert captured["run"] is run


def test_run_rejected_submission_past_a_branch_is_kept(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm, name="review")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    walk = _edit(run, {}, name="review")

    assert walk.cursor.response.context_data["form"].errors == {
        "confirmed": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        {"step": {}},
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
            args,
            kwargs,
            run,
            claim=None,
            submission=None,
            files=None,
            **extra,
        ):
            calls.append(("init", submission))
            self.reached = False
            self.target = None
            self.replaced_refs = []

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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    # Walk directly: this is about the configuration hook being honoured,
    # not about what placing at the cursor means.
    run.walk(submission={"name": "Ada"})

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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"name": "Ada"})

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


def test_run_initialise_creates_session_run(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()
    run = _make_run(linear_wizard, request)

    run.initialise()

    assert uuid.UUID(run.run_id)
    assert request.session["gandalf_runs"] == {
        run.run_id: {},
    }


def test_run_initialise_marks_session_modified(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory()
    run = _make_run(linear_wizard, request)

    run.initialise()

    assert request.session.modified is True


def test_run_replays_submissions_from_url_run_id(
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

    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")
    response = _replay(run)

    assert run.run_id == "existing-run"
    assert response.context_data["form"].__class__ is SecondStepForm


def test_run_replays_submissions_from_uuid_url_run_id(
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

    run = _make_run(linear_wizard, request)
    run.retrieve(run_id)
    response = _replay(run)

    assert run.run_id == run_id
    assert response.context_data["form"].__class__ is SecondStepForm


def test_run_retrieve_marks_session_modified(
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

    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    assert request.session.modified is True


def test_run_get_run_data_returns_current_run_data(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    run_data = run.get_run_data()

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_run_replays_submissions_to_render_next_form_view(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"name": "Ada"})
    response = _replay(run)

    assert response.context_data["form"].__class__ is SecondStepForm


def test_run_renders_first_step_in_matching_branch(
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

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"account_type": "business"})
    response = _replay(run)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is BusinessDetailsForm


def test_run_renders_first_step_in_default_branch(
    request_with_session_factory,
):
    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"account_type": "personal"})
    response = _replay(run)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is PersonalDetailsForm


def test_run_submit_inside_branch_arm_records_nested_state(
    request_with_session_factory,
):
    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"business_name": "Acme"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"account_type": "business"}},
            {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        ],
    }


def test_run_submit_after_completed_branch_arm_appends_at_top_level(
    request_with_session_factory,
):
    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"confirmed": "on"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"account_type": "business"}},
            {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
            {"step": {"confirmed": "on"}},
        ],
    }


def test_run_replay_returns_invalid_stored_step_response(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    response = _replay(run)

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is FirstStepForm
    assert response.context_data["form"].errors == {
        "name": ["This field is required."],
    }


def test_run_persists_submissions_by_url_run_id(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"name": "Ada"})

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "state": [{"step": {"name": "Ada"}}],
        },
    }


def test_run_submissions_are_isolated_between_url_run_ids(
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
    first_run = _make_run(linear_wizard, request)
    first_run.retrieve("first-run")

    _submit(first_run, {"name": "Ada"})
    second_run = _make_run(linear_wizard, request)
    second_run.retrieve("second-run")
    first_response = _replay(first_run)
    second_response = _replay(second_run)

    assert first_response.context_data["form"].__class__ is SecondStepForm
    assert second_response.context_data["form"].__class__ is FirstStepForm


def test_run_preserves_valid_previous_submissions_when_updating_next_step(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"email": "ada@example.com"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ],
    }


def test_run_replaces_invalid_stored_submission(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"name": "Ada"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"name": "Ada"}},
        ],
    }


def test_run_does_not_append_submission_after_complete_path(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"email": "grace@example.com"})

    assert request.session["gandalf_runs"]["existing-run"] == {
        "state": [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ],
    }


def test_run_replay_returns_none_after_complete_path(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    response = _replay(run)

    assert response is None


def test_run_render_step_returns_form_with_initial_from_stored_data(
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
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(template_name="testapp/linear_wizard.html")
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    response = run.render_step(name="first")

    assert response.status_code == 200
    form = response.context_data["form"]
    assert form.__class__ is FirstStepForm
    assert form.is_bound is False
    assert form.initial == {"name": "Ada"}


def test_run_render_step_finds_step_inside_branch(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal_name"),
        )
        .step(ReviewForm, name="review")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    response = run.render_step(name="business_name")

    form = response.context_data["form"]
    assert form.__class__ is BusinessDetailsForm
    assert form.initial == {"business_name": "Acme"}


def test_run_render_step_raises_step_not_found_for_unknown_context(
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
        .step(FirstStepForm, name="first")
        .configure(template_name="testapp/linear_wizard.html")
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    with pytest.raises(StepNotFound):
        run.render_step(name="missing")


def test_run_edit_replaces_step_data_and_preserves_downstream(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"name": "Grace"}, name="first")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Grace"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_run_placing_an_invalid_submission_parks_on_it(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    walk = _edit(run, {"name": ""}, name="first")

    # The rejected answer is kept and becomes the cursor, so a later walk
    # re-renders it with its errors. The answer after it is sealed, not lost.
    assert walk.cursor.node is walk.target.declaration
    assert walk.cursor.response.context_data["form"].errors == {
        "name": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": ""}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_run_placing_a_valid_submission_keeps_walking(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    walk = _edit(run, {"name": "Grace"}, name="first")

    assert walk.reached is True
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Grace"}},
        {"step": {"email": "ada@example.com"}},
    ]


def test_run_edit_preserves_branch_state_when_arm_unchanged(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"account_type": "business"}, name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]


def test_run_edit_keeps_dormant_arm_state_when_arm_changes(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
                        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
                    ],
                },
            },
        },
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"account_type": "personal"}, name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]
    response = _replay(run)
    assert response.context_data["form"].__class__ is PersonalDetailsForm


def test_run_edit_step_inside_branch_replaces_nested_entry(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"business_name": "Globex"}, name="business_name")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Globex"}}]}},
    ]


def _branching_review_wizard():
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

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
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )


def test_run_cursor_returns_first_unanswered_step(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    cursor = run.cursor()

    assert cursor.node.matches_context(name="second")


def test_run_cursor_node_is_none_when_run_is_complete(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    assert run.cursor().node is None


def test_walk_cannot_reach_a_preserved_tail_or_a_dormant_arm(
    request_with_session_factory,
):
    """A claim is only ever honoured by arriving at it. A step sealed in the
    tail, or sitting in an arm this run did not take, cannot be arrived at."""
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    preserved = run.walk(claim={"name": "review"})
    dormant = run.walk(claim={"name": "business_name"})
    at_cursor = run.walk(claim={"name": "preferred_name"})

    assert preserved.reached is False
    assert dormant.reached is False
    assert at_cursor.reached is True
    assert at_cursor.target.declaration is at_cursor.cursor.node


def test_run_previous_step_walks_the_active_route(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    cursor = run.cursor()

    # `review` is the unanswered cursor, so it is not on `path`; take every
    # declaration from the runtime route, which still mirrors the sealed step.
    from gandalf.runtime import _iter_route_steps

    route = {
        node.declaration.context["name"]: node
        for node in _iter_route_steps(cursor.state)
    }
    account = route["account_type"]
    business = route["business_name"]
    review = route["review"]

    assert run.previous_step(cursor, account.declaration) is None
    assert (
        run.previous_step(cursor, business.declaration).declaration
        is account.declaration
    )
    assert (
        run.previous_step(cursor, review.declaration).declaration
        is business.declaration
    )


def test_run_previous_step_is_none_for_unknown_declaration(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    cursor = run.cursor()

    foreign_declaration = tree.Step(FirstStepForm)

    assert run.previous_step(cursor, foreign_declaration) is None


def _cross_branch_wizard():
    """Wizard whose second branch's predicate dereferences a step inside the
    first branch's business arm — the issue #45 crash shape when that step
    is dormant or unanswered."""
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    def business_was_acme(context):
        business_step = context.run.path.find_step(name="business_name")
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


def test_run_edit_succeeds_with_cross_branch_predicate_mid_divert(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    walk = _edit(run, {"account_type": "personal"}, name="account_type")

    assert walk.reached is True
    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0] == {"step": {"account_type": "personal"}}
    assert state[1] == {"branch": {"0": [{"step": {"business_name": "Acme"}}]}}


def test_run_path_is_safe_with_cross_branch_predicate_mid_divert(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    names = [step.declaration.context["name"] for step in _iter_path(run)]

    assert names == ["account_type", "review"]


def _iter_path(run):
    yield from run.path


class _StubUrls:
    def get_wizard_url(self, run_id):
        return f"/wizard/{run_id}/"

    def get_step_url(self, run_id, step_segment):
        return f"/wizard/{run_id}/{step_segment}/"


def test_run_back_and_run_urls_derive_from_render_context(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    run.urls = _StubUrls()
    cursor = run.cursor()

    run.mark_rendering(cursor, cursor.node)

    assert run.back_url == "/wizard/existing-run/business_name/"
    assert run.run_url == "/wizard/existing-run/"


def test_run_back_url_is_none_at_the_first_step(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    run.urls = _StubUrls()
    cursor = run.cursor()

    run.mark_rendering(cursor, cursor.node)

    assert run.back_url is None
    assert run.run_url == "/wizard/existing-run/"


def test_run_rendering_names_the_step_being_rendered(
    request_with_session_factory,
):
    """What a step view needs to talk about the run it sits in — a summary
    page has to know which step *it* is to drop itself from its own rows."""
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    cursor = run.cursor()

    assert run.rendering is None

    run.mark_rendering(cursor, cursor.node)
    assert run.rendering is cursor.node

    run.clear_rendering()
    assert run.rendering is None


def test_run_runtime_tree_reuses_the_render_context_walk(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    cursor = run.cursor()

    run.mark_rendering(cursor, cursor.node)

    assert run.runtime_tree is cursor.state


def test_run_nav_urls_are_none_without_reverser_or_render_context(
    request_with_session_factory,
):
    wizard = _branching_review_wizard()
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    assert run.back_url is None
    assert run.run_url is None

    run.urls = _StubUrls()

    assert run.back_url is None
    assert run.run_url == "/wizard/existing-run/"


@pytest.fixture
def business_run(request_with_session_factory):
    """A branching run with the business arm answered, parked on review."""
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
    run = _make_run(_branching_review_wizard(), request)
    run.retrieve("existing-run")
    return run


def test_runtime_step_carries_its_name_and_its_own_url(business_run):
    business_run.urls = _StubUrls()

    steps = list(business_run.path)

    assert [step.name for step in steps] == ["account_type", "business_name"]
    assert [step.url for step in steps] == [
        "/wizard/existing-run/account_type/",
        "/wizard/existing-run/business_name/",
    ]


def test_run_builds_a_step_url_from_a_declaration(business_run):
    business_run.urls = _StubUrls()
    step = business_run.path.find_step(name="business_name")

    assert business_run.step_url(step.declaration) == step.url


def test_step_url_is_none_without_a_url_reverser(business_run):
    step = business_run.path.find_step(name="account_type")

    assert step.url is None
    assert business_run.step_url(step) is None


def test_runtime_step_builds_its_form_once(business_run):
    step = business_run.path.find_step(name="account_type")

    assert step.form is step.form
    assert step.form.cleaned_data == {"account_type": "business"}


def test_run_edit_changing_arm_preserves_answers_after_branch(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"account_type": "personal"}, name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "personal"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
        {"step": {"confirmed": "on"}},
    ]
    response = _replay(run)
    assert response.context_data["form"].__class__ is PersonalDetailsForm


def test_run_submit_fills_hole_and_completes_preserved_run(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _submit(run, {"preferred_name": "Ada"})

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
    assert _replay(run) is None


def test_run_edit_flip_flop_restores_dormant_arm_answers(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"account_type": "personal"}, name="account_type")
    _edit(run, {"account_type": "business"}, name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": "Acme"}}]}},
    ]
    response = _replay(run)
    assert response.context_data["form"].__class__ is ReviewForm


def test_run_edit_restoring_stale_dormant_answer_renders_errors(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"account_type": "business"}, name="account_type")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {
            "branch": {
                "0": [{"step": {"business_name": ""}}],
                "default": [{"step": {"preferred_name": "Ada"}}],
            }
        },
    ]
    response = _replay(run)
    assert response.context_data["form"].__class__ is BusinessDetailsForm
    assert response.context_data["form"].errors == {
        "business_name": ["This field is required."],
    }


def test_run_edit_keeps_invalid_downstream_answer_for_correction(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"name": "Grace"}, name="first")

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"name": "Grace"}},
        {"step": {"email": "not-an-email"}},
    ]
    response = _replay(run)
    assert response.context_data["form"].__class__ is SecondStepForm
    assert response.context_data["form"].errors == {
        "email": ["Enter a valid email address."],
    }


def test_run_edit_raises_step_not_found_for_unknown_context(
    request_with_session_factory,
):
    from gandalf.runtime import StepNotFound

    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    with pytest.raises(StepNotFound):
        _edit(run, {"name": "Grace"}, name="missing")


def test_run_rejected_submission_inside_a_branch_is_kept(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    walk = _edit(run, {"business_name": ""}, name="business_name")

    assert walk.cursor.response.context_data["form"].errors == {
        "business_name": ["This field is required."],
    }
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"account_type": "business"}},
        {"branch": {"0": [{"step": {"business_name": ""}}]}},
    ]


def test_run_find_step_raises_when_context_matches_multiple_steps(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(FirstStepForm, name="duplicate")
        .step(SecondStepForm, name="duplicate")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    # Placement no longer needs to detect this — a wizard with duplicate names
    # is rejected when it resolves — but lookups still have to refuse to guess.
    with pytest.raises(tree.MultipleStepsReturned):
        run.path.find_step(name="duplicate")


def test_run_edit_does_not_mutate_original_stored_state(
    request_with_session_factory,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm, name="business_name"),
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    _edit(run, {"business_name": "Globex"}, name="business_name")

    assert stored_state == [
        {"step": {"account_type": "business"}},
        {"branch": [{"step": {"business_name": "Acme"}}]},
    ]


def test_run_replays_submissions_through_form_view_form_valid(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    response = _replay(run)

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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    first_step = run.runtime_tree

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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    first_step = run.runtime_tree

    assert first_step.data == {"name": "Ada"}


def test_runtime_step_form_reads_a_stored_multi_valued_answer_as_a_list(
    request_with_session_factory,
):
    wizard = (
        Wizard()
        .step(ToppingsForm)
        .configure(template_name="testapp/single_step_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"toppings": ["cheese", "basil"]}}],
                },
            },
        },
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    toppings_step = run.runtime_tree

    assert toppings_step.form.cleaned_data == {"toppings": ["cheese", "basil"]}


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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    first_step = run.runtime_tree

    assert first_step.data == {"count": "42"}
    assert first_step.form.cleaned_data == {"count": 42}


def test_run_path_is_empty_when_no_steps_complete(
    request_with_session_factory,
    linear_wizard,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    assert not run.path
    assert list(run.path) == []


def test_run_path_for_linear_wizard_includes_only_completed_steps(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    steps = list(run.path)

    assert len(steps) == 1
    assert isinstance(steps[0], RuntimeStep)
    assert steps[0].declaration.declaration is FirstStepForm
    assert steps[0].data == {"name": "Ada"}


def test_run_path_inlines_completed_branch_arm_steps(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def is_business(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    steps = list(run.path)

    assert all(isinstance(step, RuntimeStep) for step in steps)
    assert [step.declaration.declaration for step in steps] == [
        AccountTypeForm,
        BusinessDetailsForm,
    ]


def test_run_path_walkable_by_tree_reducer_to_merge_cleaned_data(
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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    class MergeCleanedData(tree.Reducer):
        def initial(self):
            return {}

        def combine(self, accumulator, value):
            return {**accumulator, **value}

        def visit_step(self, runtime_step):
            return runtime_step.form.cleaned_data

    payload = MergeCleanedData().reduce(run.path)

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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    runtime_step = run.runtime_tree

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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    form = run.runtime_tree.form

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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    form = run.runtime_tree.form

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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    payload = gandalf.wizard.MergeCleanedData().reduce(run.path)

    assert payload == {"name": "Ada", "email": "ada@example.com"}


def test_run_path_drops_branch_with_unmatched_no_default_arm(
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
        .step(AccountTypeForm, name="after_branch")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    steps = list(run.path)

    assert all(isinstance(step, RuntimeStep) for step in steps)
    assert [step.declaration.declaration for step in steps] == [
        FirstStepForm,
        AccountTypeForm,
    ]


def test_run_path_walks_multi_step_branch_arm(
    request_with_session_factory,
):
    from gandalf.runtime import RuntimeStep

    def is_business(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    steps = list(run.path)

    assert all(isinstance(step, RuntimeStep) for step in steps)
    assert [step.declaration.declaration for step in steps] == [
        AccountTypeForm,
        BusinessDetailsForm,
        SecondStepForm,
        ReviewForm,
    ]


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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    payload = MergeCleanedData().reduce(run.path)

    assert payload == {"name": "Ada", "email": "ada@example.com"}


def _formset_run(request_with_session_factory):
    """A finished run whose second step is a formset, so its answer is a
    list of one entry per form rather than a mapping."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(OpeningHoursStepView, name="opening-hours")
        .configure(template_name="testapp/linear_wizard.html")
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [
                        {"step": {"name": "Ada"}},
                        {
                            "step": {
                                "form-TOTAL_FORMS": "1",
                                "form-INITIAL_FORMS": "0",
                                "form-MIN_NUM_FORMS": "0",
                                "form-MAX_NUM_FORMS": "1000",
                                "form-0-day": "Monday",
                                "form-0-opens": "09:00",
                            },
                        },
                    ],
                },
            },
        },
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    return run


def test_merge_cleaned_data_folds_a_formset_under_its_step_name(
    request_with_session_factory,
):
    """A formset answers with one entry per form, so it has no fields to
    spread across the dict — its rows land under the step's own name. The
    fold stays total: every answer reaches the merged dict, which is what
    skipping the step would have cost."""
    from gandalf.wizard import MergeCleanedData

    run = _formset_run(request_with_session_factory)

    payload = MergeCleanedData().reduce(run.path)

    assert payload == {
        "name": "Ada",
        "opening-hours": [{"day": "Monday", "opens": "09:00"}],
    }


def test_merge_cleaned_data_lets_a_subclass_choose_another_key(
    request_with_session_factory,
):
    """The step name is a default, not a rule — `visit_step` is the seam
    for an application that wants those rows somewhere else."""
    from gandalf.wizard import MergeCleanedData

    class MergeUnderOneKey(MergeCleanedData):
        def visit_step(self, runtime_step):
            cleaned_data = runtime_step.form.cleaned_data
            if isinstance(cleaned_data, list):
                return {"rows": cleaned_data}
            return super().visit_step(runtime_step)

    run = _formset_run(request_with_session_factory)

    payload = MergeUnderOneKey().reduce(run.path)

    assert payload == {"name": "Ada", "rows": [{"day": "Monday", "opens": "09:00"}]}


def test_a_reducer_can_refuse_a_collision_instead_of_last_write_wins(
    request_with_session_factory, linear_wizard
):
    """The smallest contract change the reference documents: `combine`
    alone, because last-write-wins is a choice and not a law."""
    from gandalf.wizard import MergeCleanedData

    class MergeRefusingCollisions(MergeCleanedData):
        def combine(self, accumulator, value):
            clash = accumulator.keys() & value.keys()
            if clash:
                raise ValueError(f"two steps both answered {', '.join(sorted(clash))}")
            return super().combine(accumulator, value)

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
    run = _make_run(linear_wizard, request)
    run.retrieve("existing-run")

    assert MergeRefusingCollisions().reduce(run.path) == {
        "name": "Ada",
        "email": "ada@example.com",
    }


def test_a_reducer_subclass_can_key_answers_by_step(request_with_session_factory):
    """The reference's worked `AnswersByStep`: `tree.Reducer` is the public
    base. Folded over the runtime tree rather than the flattened path, so
    `visit_branch` genuinely fires — and the sub-fold it is handed arrives
    with a top-level fold's shape, which is what lets returning it unchanged
    read the arm's steps inline."""

    class AnswersByStep(tree.Reducer):
        def initial(self):
            return {}

        def combine(self, accumulator, value):
            return {**accumulator, **value}

        def visit_step(self, runtime_step):
            return {runtime_step.name: runtime_step.form.cleaned_data}

        def visit_branch(self, runtime_branch, sub_result):
            return sub_result

    def is_business(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    assert AnswersByStep().reduce(run.runtime_tree) == {
        "account_type": {"account_type": "business"},
        "business": {"business_name": "Acme"},
    }


def test_merge_cleaned_data_folds_runtime_tree_across_branch(
    request_with_session_factory,
):
    from gandalf.wizard import MergeCleanedData

    def is_business(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.form.cleaned_data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    payload = MergeCleanedData().reduce(run.runtime_tree)

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
            path = self.request.run.path
            captured["path_head_name"] = (
                path.head.form.cleaned_data["name"] if path else None
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    response = _replay(run)

    assert response.status_code == 200
    assert captured["path_head_name"] == "Ada"


def test_run_submit_with_files_persists_file_refs_in_state(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = run.file_storage.save(run.run_id, photo)

    _submit(run, {"photo": "avatar.jpg"}, files={"photo": file_key})

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state == [
        {"step": {"photo": "avatar.jpg"}, "files": {"photo": file_key}},
    ]


def test_run_replay_reconstitutes_uploaded_file_for_form_validation(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = run.file_storage.save(run.run_id, photo)
    _submit(run, {"photo": "avatar.jpg"}, files={"photo": file_key})

    response = _replay(run)

    assert response.status_code == 200
    response.render()
    assert b"name" in response.content


def test_run_render_step_passes_stored_file_as_initial(
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
        .step(CapturingProfileView, name="photo")
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = run.file_storage.save(run.run_id, photo)
    _submit(run, {"photo": "avatar.jpg"}, files={"photo": file_key})

    run.render_step(name="photo")

    assert captured["initial"]["photo"].read() == b"binary"


def test_run_edit_without_new_file_preserves_stored_ref(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, name="photo")
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = run.file_storage.save(run.run_id, photo)
    _submit(run, {"photo": "avatar.jpg"}, files={"photo": file_key})

    _edit(run, {"photo": "avatar.jpg"}, name="photo")

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0]["files"] == {"photo": file_key}
    assert run.file_storage.open(file_key).read() == b"binary"


def test_run_edit_adds_file_to_step_that_had_no_files(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, name="photo")
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    _submit(run, {"label": "first"})
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    new_key = run.file_storage.save(run.run_id, photo)

    _edit(
        run,
        {"label": "first"},
        files={"photo": new_key},
        name="photo",
    )

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0]["files"] == {"photo": new_key}


def test_run_edit_with_new_file_replaces_and_deletes_old(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(ProfilePhotoForm, name="photo")
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    old_photo = SimpleUploadedFile("v1.jpg", b"first")
    old_ref = run.file_storage.save(run.run_id, old_photo)
    _submit(run, {"photo": "v1.jpg"}, files={"photo": old_ref})
    new_photo = SimpleUploadedFile("v2.jpg", b"second")
    new_ref = run.file_storage.save(run.run_id, new_photo)

    _edit(
        run,
        {"photo": "v2.jpg"},
        files={"photo": new_ref},
        name="photo",
    )

    state = request.session["gandalf_runs"]["existing-run"]["state"]
    assert state[0]["files"] == {"photo": new_ref}
    assert not run.file_storage.backend.exists(old_ref["tmp_name"])
    assert run.file_storage.open(new_ref).read() == b"second"


def test_run_rejected_submission_keeps_its_own_upload(
    request_with_session_factory,
    temp_file_storage_class,
):
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, name="photo")
        .step(FirstStepForm)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    old_photo = SimpleUploadedFile("v1.jpg", b"first")
    old_ref = run.file_storage.save(run.run_id, old_photo)
    _submit(
        run,
        {"label": "", "photo": "v2.jpg"},
        files={"photo": old_ref},
    )
    new_photo = SimpleUploadedFile("v2.jpg", b"second")
    new_ref = run.file_storage.save(run.run_id, new_photo)

    walk = _edit(
        run,
        {"label": "", "photo": "v2.jpg"},
        files={"photo": new_ref},
        name="photo",
    )

    assert walk.cursor.response.context_data["form"].errors == {
        "label": ["This field is required."],
    }
    # The rejected submission is what is stored now, so its upload is the
    # live one and the ref it superseded is collected rather than orphaned.
    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {
            "step": {"label": "", "photo": "v2.jpg"},
            "files": {"photo": new_ref},
        },
    ]
    assert run.file_storage.open(new_ref).read() == b"second"
    assert not run.file_storage.backend.exists(old_ref["tmp_name"])


def test_run_edit_keeps_old_file_when_rewalk_raises(
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
        .step(ProfilePhotoForm, name="photo")
        .step(ExplodingStepView)
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    old_photo = SimpleUploadedFile("v1.jpg", b"first")
    old_ref = run.file_storage.save(run.run_id, old_photo)
    run.storage.set_state(
        "existing-run",
        [
            {"step": {"photo": "v1.jpg"}, "files": {"photo": old_ref}},
            {"step": {"email": "ada@example.com"}},
        ],
    )
    new_photo = SimpleUploadedFile("v2.jpg", b"second")
    new_ref = run.file_storage.save(run.run_id, new_photo)

    with pytest.raises(RuntimeError):
        _edit(
            run,
            {"photo": "v2.jpg"},
            files={"photo": new_ref},
            name="photo",
        )

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {"step": {"photo": "v1.jpg"}, "files": {"photo": old_ref}},
        {"step": {"email": "ada@example.com"}},
    ]
    assert run.file_storage.open(old_ref).read() == b"first"


def test_run_edit_step_not_found_deletes_new_files(
    request_with_session_factory,
    temp_file_storage_class,
):
    from gandalf.runtime import StepNotFound

    wizard = (
        Wizard()
        .step(OptionalPhotoForm, name="photo")
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("orphan.jpg", b"orphan-bytes")
    new_ref = run.file_storage.save(run.run_id, photo)

    with pytest.raises(StepNotFound):
        _edit(
            run,
            {"label": "ignored"},
            files={"photo": new_ref},
            name="missing",
        )

    assert not run.file_storage.backend.exists(new_ref["tmp_name"])


def test_run_submit_correction_keeps_stored_file_refs(
    request_with_session_factory,
    temp_file_storage_class,
):
    wizard = (
        Wizard()
        .step(OptionalPhotoForm, name="photo")
        .configure(
            template_name="testapp/linear_wizard.html",
            file_storage_class=temp_file_storage_class,
        )
    )
    request = request_with_session_factory(
        session={"gandalf_runs": {"existing-run": {}}},
    )
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("kept.jpg", b"kept-bytes")
    photo_ref = run.file_storage.save(run.run_id, photo)
    _submit(run, {"label": "", "photo": "kept.jpg"}, files={"photo": photo_ref})

    _submit(run, {"label": "Fixed", "photo": "kept.jpg"})

    assert request.session["gandalf_runs"]["existing-run"]["state"] == [
        {
            "step": {"label": "Fixed", "photo": "kept.jpg"},
            "files": {"photo": photo_ref},
        },
    ]


def test_run_edit_error_render_receives_url_kwargs(
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
        .step(KwargAwareStepView, name="first")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    walk = _edit(
        run,
        {"name": ""},
        url_kwargs={"org": "acme"},
        name="first",
    )

    assert walk.cursor.response.context_data["org"] == "acme"
    assert walk.cursor.response.context_data["form"].errors == {
        "name": ["This field is required."],
    }


def test_run_render_step_receives_url_kwargs(
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
        .step(KwargAwareStepView, name="first")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    response = run.render_step(
        url_kwargs={"org": "acme"},
        name="first",
    )

    assert response.context_data["org"] == "acme"
    assert response.context_data["form"].initial == {"name": "Ada"}


def test_run_edit_changing_arm_keeps_dormant_file_refs(
    request_with_session_factory,
    temp_file_storage_class,
):
    import gandalf.wizard

    def is_business_account(context):
        account_step = context.run.path.find_step(name="account_type")
        return account_step.data["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_business_account,
                Wizard().step(ProfilePhotoForm, name="photo"),
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    _submit(run, {"account_type": "business"})
    photo = SimpleUploadedFile("logo.jpg", b"logo-bytes")
    photo_ref = run.file_storage.save(run.run_id, photo)
    _submit(run, {"photo": "logo.jpg"}, files={"photo": photo_ref})

    _edit(run, {"account_type": "personal"}, name="account_type")

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
    assert run.file_storage.open(photo_ref).read() == b"logo-bytes"


def test_run_cleanup_files_wipes_run_prefix(
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")
    photo = SimpleUploadedFile("avatar.jpg", b"binary")
    file_key = run.file_storage.save(run.run_id, photo)
    _submit(run, {"photo": "avatar.jpg"}, files={"photo": file_key})

    run.cleanup_files()

    _, files = run.file_storage.backend.listdir("gandalf/existing-run")
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
    run = _make_run(wizard, request)
    run.retrieve("existing-run")

    assert isinstance(run.file_storage, FakeFileStorage)
    run.cleanup_files()
    assert ("delete_run", "existing-run") in calls


# --- Switch: branching on a value rather than on N predicates ---------------


def _account_type(context):
    """The account type the customer chose."""
    return context.run.path.find_step(name="account_type").form.cleaned_data[
        "account_type"
    ]


def _switch_wizard(selector=_account_type, **kwargs):
    return (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .switch(
            selector,
            {
                "business": Wizard().step(BusinessDetailsForm, name="business"),
                "personal": Wizard().step(PersonalDetailsForm, name="personal"),
            },
            **kwargs,
        )
        .step(ReviewForm, name="review")
        .configure(template_name="testapp/linear_wizard.html")
    )


def test_switch_declares_one_arm_per_case():
    wizard = Wizard().switch(
        _account_type,
        {"business": Wizard().step(BusinessDetailsForm, name="business")},
    )

    node = wizard.tree
    assert isinstance(node, tree.Switch)
    assert isinstance(node, tree.Branch)
    assert node.cases == ("business",)
    assert node.selector is _account_type


def test_switch_arms_are_guards_naming_their_case():
    """A Switch is a Branch whose arms are real guards — each asking "did
    the selector say me?" — so anything that walks a declaration tree
    keeps working, and the equivalence is not a fiction."""
    wizard = Wizard().switch(
        _account_type,
        {
            "business": Wizard().step(BusinessDetailsForm, name="business"),
            "personal": Wizard().step(PersonalDetailsForm, name="personal"),
        },
    )

    guards = [predicate for predicate, _ in wizard.tree.arms]

    assert [guard.case for guard in guards] == ["business", "personal"]
    assert all(guard.selector is _account_type for guard in guards)
    assert wizard.tree.arm_id(1) == "personal"


def test_switch_takes_the_arm_its_selector_names(request_with_session_factory):
    request = request_with_session_factory()
    run = _make_run(_switch_wizard(), request)
    run.initialise()

    _submit(run, {"account_type": "business"})

    assert run.cursor().node.context == {"name": "business"}


def test_switch_falls_back_to_default_for_a_value_no_case_names(
    request_with_session_factory,
):
    request = request_with_session_factory()
    wizard = _switch_wizard(
        selector=lambda request: "sole-trader",
        default=Wizard().step(ReviewForm, name="fallback"),
    )
    run = _make_run(wizard, request)
    run.initialise()

    _submit(run, {"account_type": "business"})

    assert run.cursor().node.context == {"name": "fallback"}


def test_switch_without_a_default_skips_to_what_follows(
    request_with_session_factory,
):
    request = request_with_session_factory()
    wizard = _switch_wizard(selector=lambda request: "neither")
    run = _make_run(wizard, request)
    run.initialise()

    _submit(run, {"account_type": "business"})

    assert run.cursor().node.context == {"name": "review"}


def test_switch_asks_its_selector_once_per_walk(request_with_session_factory):
    """The point of a case statement over N predicates: the decision is
    computed once, however many cases there are, so a selector may do real
    work (a lookup, a call) without paying for it per arm."""
    calls = []

    def counting_selector(request):
        calls.append(1)
        return "personal"

    request = request_with_session_factory()
    run = _make_run(_switch_wizard(counting_selector), request)
    run.initialise()
    _submit(run, {"account_type": "business"})

    calls.clear()
    run.cursor()

    assert len(calls) == 1


def test_switch_stores_its_answers_under_the_case_name(
    request_with_session_factory,
):
    """Storage keyed by the case, not by declaration order, so reordering
    the cases cannot strand the answers behind them."""
    request = request_with_session_factory()
    run = _make_run(_switch_wizard(), request)
    run.initialise()

    _submit(run, {"account_type": "business"})
    _submit(run, {"business_name": "Ada Ltd"})

    state = run.get_state()
    assert state[1] == {
        "branch": {"business": [{"step": {"business_name": "Ada Ltd"}}]}
    }


def test_switch_keeps_a_de_selected_cases_answers(request_with_session_factory):
    """Dormant memory works per case name exactly as it does per arm index."""
    request = request_with_session_factory()
    run = _make_run(_switch_wizard(), request)
    run.initialise()
    _submit(run, {"account_type": "business"})
    _submit(run, {"business_name": "Ada Ltd"})

    _edit(run, {"account_type": "personal"}, name="account_type")

    stored = run.get_state()[1]["branch"]
    assert stored["business"] == [{"step": {"business_name": "Ada Ltd"}}]
    assert run.cursor().node.context == {"name": "personal"}


def test_switch_refuses_a_case_called_default():
    """ "default" is the key the fallback arm's answers are stored under."""
    with pytest.raises(ImproperlyConfigured):
        Wizard().switch(
            _account_type,
            {"default": Wizard().step(BusinessDetailsForm, name="business")},
        )


def test_module_level_switch_entry_point():
    wizard = gandalf.wizard.switch(
        _account_type,
        {"business": Wizard().step(BusinessDetailsForm, name="business")},
    )

    assert isinstance(wizard, Wizard)
    assert isinstance(wizard.tree, tree.Switch)


# --- on_field: the common case, declared rather than computed ---------------


def _on_field_wizard():
    return (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .switch(
            gandalf.wizard.on_field("account_type", "account_type"),
            {
                "business": Wizard().step(BusinessDetailsForm, name="business"),
                "personal": Wizard().step(PersonalDetailsForm, name="personal"),
            },
        )
        .configure(template_name="testapp/linear_wizard.html")
    )


def test_on_field_routes_on_a_previous_answer(request_with_session_factory):
    request = request_with_session_factory()
    run = _make_run(_on_field_wizard(), request)
    run.initialise()

    _submit(run, {"account_type": "personal"})

    assert run.cursor().node.context == {"name": "personal"}


def test_on_field_names_the_answer_it_reads():
    selector = gandalf.wizard.on_field("account_type", "account_type")

    assert selector.step == "account_type"
    assert selector.field == "account_type"
    assert "account_type" in selector.__name__


def test_on_field_naming_an_undeclared_step_is_refused():
    with pytest.raises(ImproperlyConfigured, match="names no step of this wizard"):
        (
            Wizard()
            .step(AccountTypeForm, name="account_type")
            .switch(
                gandalf.wizard.on_field("nowhere", "account_type"),
                {"business": Wizard().step(BusinessDetailsForm, name="business")},
            )
            .configure(template_name="testapp/linear_wizard.html")
        )


def test_on_field_naming_no_field_of_its_step_is_refused():
    """The value of a field nothing asks is "", which names no case."""
    with pytest.raises(ImproperlyConfigured, match="names no field of step"):
        (
            Wizard()
            .step(AccountTypeForm, name="account_type")
            .switch(
                gandalf.wizard.on_field("account_type", "nonexistent"),
                {"business": Wizard().step(BusinessDetailsForm, name="business")},
            )
            .configure(template_name="testapp/linear_wizard.html")
        )


def test_on_field_on_a_step_that_picks_its_form_per_request_is_trusted():
    class _Undecided(StepFormView):
        template_name = "testapp/linear_wizard.html"

        def get_form_class(self):
            return AccountTypeForm

    wizard = (
        Wizard()
        .step(_Undecided, name="account_type")
        .switch(
            gandalf.wizard.on_field("account_type", "whatever"),
            {"business": Wizard().step(BusinessDetailsForm, name="business")},
        )
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert wizard.tree is not None


def test_a_formset_step_declares_no_step_level_fields():
    """A formset declares nothing at step level — its fields belong to each
    of the n rows it repeats — and that is a different answer from the
    `None` a step choosing its form per request gets. One is "no fields",
    which can be checked against; the other is "unknown", which cannot."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(OpeningHoursStepView, name="opening-hours")
        .configure(template_name="testapp/linear_wizard.html")
    )

    fields = gandalf.wizard.declared_step_fields(wizard)

    assert set(fields["first"]) == {"name"}
    assert fields["opening-hours"] == {}


def test_on_field_beside_a_formset_step_still_checks_the_step_it_names():
    """The formset is taken on trust; the step the selector actually names
    is not, so a typo two steps away is still caught."""
    with pytest.raises(ImproperlyConfigured, match="names no field of step"):
        (
            Wizard()
            .step(AccountTypeForm, name="account_type")
            .step(OpeningHoursStepView, name="opening-hours")
            .switch(
                gandalf.wizard.on_field("account_type", "nonexistent"),
                {"business": Wizard().step(BusinessDetailsForm, name="business")},
            )
            .configure(template_name="testapp/linear_wizard.html")
        )


def test_on_field_naming_a_formset_step_is_refused():
    """A formset answers with a row per entry, so there is no single value
    to route on. Before the declaration could say "no fields" rather than
    "unknown" this passed configuration and died mid-walk, on the
    `cleaned_data.get()` of a list."""
    with pytest.raises(ImproperlyConfigured, match="no fields of its own"):
        (
            Wizard()
            .step(OpeningHoursStepView, name="opening-hours")
            .switch(
                gandalf.wizard.on_field("opening-hours", "day"),
                {"monday": Wizard().step(BusinessDetailsForm, name="business")},
            )
            .configure(template_name="testapp/linear_wizard.html")
        )


def test_a_selector_of_your_own_can_route_on_a_formset_answer():
    """The way out the refusal names. `.switch()` takes any callable, so a
    step whose answer `on_field` cannot read is routed by reading it."""

    def opens_on_monday(context):
        rows = context.run.path.find_step(name="opening-hours").answer
        return "monday" if any(row["day"] == "Monday" for row in rows) else "other"

    wizard = (
        Wizard()
        .step(OpeningHoursStepView, name="opening-hours")
        .switch(
            opens_on_monday,
            {"monday": Wizard().step(BusinessDetailsForm, name="business")},
        )
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert wizard.tree is not None


def test_on_field_in_an_expanding_wizard_is_trusted():
    """An expansion grows names mid-walk, so none can be known now."""
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .expand(lambda context: Wizard())
        .switch(
            gandalf.wizard.on_field("grown_later", "whatever"),
            {"business": Wizard().step(BusinessDetailsForm, name="business")},
        )
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert wizard.tree is not None


def test_an_unnamed_step_is_not_a_name_the_declaration_offers():
    """A step with no name cannot be addressed, so it is absent from the
    fields a selector or a summary checks itself against."""
    wizard = (
        Wizard()
        .step(AccountTypeForm)
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert gandalf.wizard.declared_step_fields(wizard) == {}


def test_configure_refuses_a_key_it_does_not_read():
    """Stored and never applied is the failure a typo would otherwise buy."""
    with pytest.raises(ImproperlyConfigured, match="does not read observer_clas"):
        Wizard().step(AccountTypeForm, name="account_type").configure(
            template_name="testapp/linear_wizard.html", observer_clas=object
        )


def test_on_field_says_which_step_it_could_not_find(request_with_session_factory):
    """A selector naming a step the run has not answered is a declaration
    mistake, and says so rather than failing as an attribute error."""
    request = request_with_session_factory()
    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                lambda context: False,
                Wizard().step(BusinessDetailsForm, name="nonexistent"),
            ),
            default=Wizard(),
        )
        .switch(
            gandalf.wizard.on_field("nonexistent", "business_name"),
            {"business": Wizard().step(BusinessDetailsForm, name="business")},
        )
        .configure(template_name="testapp/linear_wizard.html")
    )
    run = _make_run(wizard, request)
    run.initialise()

    with pytest.raises(ImproperlyConfigured, match="nonexistent"):
        _submit(run, {"account_type": "business"})


# --- A wizard describing itself ---------------------------------------------


def test_a_wizard_describes_its_declared_shape():
    """No run, no request, no storage: a description of the declaration."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first")
        .step(SecondStepForm, name="second")
        .configure(template_name="testapp/linear_wizard.html")
    )

    outline = wizard.outline()

    assert [entry["kind"] for entry in outline] == ["step", "step"]
    assert [entry["name"] for entry in outline] == ["first", "second"]
    assert outline[0]["declaration"].declaration is FirstStepForm


def test_a_wizard_describes_every_route_a_fork_could_take():
    wizard = _switch_wizard()

    [_, switch, _] = wizard.outline()

    assert switch["kind"] == "switch"
    assert [case["case"] for case in switch["cases"]] == ["business", "personal"]
    assert [step["name"] for step in switch["cases"][0]["steps"]] == ["business"]


def test_a_wizard_carries_the_context_its_steps_were_declared_with():
    """Not just the routable name: whatever the declaration said, so a
    caller can group or label steps however it declared them."""
    wizard = (
        Wizard()
        .step(FirstStepForm, name="first", label="Your name")
        .configure(template_name="testapp/linear_wizard.html")
    )

    [step] = wizard.outline()

    assert step["context"] == {"name": "first", "label": "Your name"}


def test_a_wizard_describes_a_predicate_fork_in_its_own_words():
    """A branch cannot say what decides it — that is arbitrary code — but
    the predicate names and documents itself, and that is the author's
    description of the choice."""

    def is_a_business(request):
        """The customer asked for a business account."""
        return True

    wizard = (
        Wizard()
        .step(AccountTypeForm, name="account_type")
        .branch(
            gandalf.wizard.condition(
                is_a_business,
                Wizard().step(BusinessDetailsForm, name="business"),
            ),
            default=Wizard().step(PersonalDetailsForm, name="personal"),
        )
        .configure(template_name="testapp/linear_wizard.html")
    )

    [_, branch] = wizard.outline()

    [arm] = branch["arms"]
    assert arm["when"] == "is_a_business"
    assert arm["description"] == "The customer asked for a business account."
    assert [step["name"] for step in arm["steps"]] == ["business"]
    assert [step["name"] for step in branch["default"]] == ["personal"]


def test_a_wizard_says_which_answer_decides_a_declared_switch():
    """The declarative case: the dependency is data, not prose, so a caller
    can work the route out rather than guessing it."""
    wizard = _on_field_wizard()

    [_, switch] = wizard.outline()

    assert switch["source"] == {"step": "account_type", "field": "account_type"}
    assert switch["decided_by"] == "account_type.account_type"
    assert switch["description"] is None


def test_a_wizard_marks_where_it_grows_from_an_answer():
    """An expansion's steps do not exist until the answer that shapes them
    does, so the shape can only say that something grows here."""

    def build_items(request):  # pragma: no cover - never walked here
        return Wizard()

    wizard = (
        Wizard()
        .step(FirstStepForm, name="count")
        .expand(build_items)
        .step(SecondStepForm, name="after")
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert [entry["kind"] for entry in wizard.outline()] == ["step", "expand", "step"]


def test_the_old_context_keyword_is_refused_rather_than_misread():
    """Up to 0.9 a step's context was passed as `context={...}`. Under
    keywords that spelling is not an error but a step whose context has one
    key called "context": the answers still store, the labels vanish and
    the step routes nowhere. Refusing it is the only way an upgrade can
    tell you."""
    with pytest.raises(ImproperlyConfigured, match="context="):
        Wizard().step(FirstStepForm, context={"name": "first"})


def test_a_step_can_still_be_given_any_other_context_key():
    wizard = Wizard().step(FirstStepForm, name="first", label="Your name")

    assert wizard.tree.context == {"name": "first", "label": "Your name"}
