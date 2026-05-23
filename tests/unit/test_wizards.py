import uuid

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.views.generic.edit import FormView

import gandalf.wizards
from gandalf import tree
from gandalf.wizards import ConfiguredWizard, Wizard
from tests.testapp.forms import FirstStepForm, SecondStepForm


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


def test_step_builder_does_not_mutate_source_wizard():
    base_wizard = Wizard().step(FirstStepForm)

    derived_wizard = base_wizard.step(SecondStepForm)

    base_nodes = list(base_wizard.tree.walk())
    derived_nodes = list(derived_wizard.tree.walk())

    assert len(base_nodes) == 1
    assert base_nodes[0].declaration is FirstStepForm
    assert len(derived_nodes) == 2
    assert derived_nodes[0].declaration is FirstStepForm
    assert derived_nodes[1].declaration is SecondStepForm


def test_step_builder_allows_independent_variants():
    base_wizard = Wizard().step(FirstStepForm)

    first_variant = base_wizard.step(SecondStepForm)
    second_variant = base_wizard.step(FirstStepForm)

    base_nodes = list(base_wizard.tree.walk())
    first_nodes = list(first_variant.tree.walk())
    second_nodes = list(second_variant.tree.walk())

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

    bound_wizard = wizard.get_bound_wizard(request)

    assert isinstance(bound_wizard.storage, FakeStorage)
    assert bound_wizard.storage.request is request


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
    bound_wizard = linear_wizard.get_bound_wizard(request)

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
    bound_wizard = linear_wizard.get_bound_wizard(request)

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

    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")
    response = bound_wizard.replay()

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

    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve(run_id)
    response = bound_wizard.replay()

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

    bound_wizard = linear_wizard.get_bound_wizard(request)
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
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    run_data = bound_wizard.get_run_data()

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_bound_wizard_get_submissions_unwraps_step_entries(
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
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    submissions = bound_wizard.get_submissions()

    assert submissions == [
        {"name": "Ada"},
        {"email": "ada@example.com"},
    ]


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
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"name": "Ada"})
    response = bound_wizard.replay()

    assert response.context_data["form"].__class__ is SecondStepForm


@pytest.mark.xfail(reason="Branch traversal is not implemented yet.")
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
        account_type_submission = request.wizard.get_submissions()[0]
        return account_type_submission["account_type"] == "business"

    wizard = (
        Wizard()
        .step(AccountTypeForm)
        .branch(
            gandalf.wizards.condition(
                is_business_account,
                Wizard().step(BusinessDetailsForm),
            ),
            default=Wizard().step(PersonalDetailsForm),
        )
        .step(ReviewForm)
        .configure()
    )
    request = request_with_session_factory(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    bound_wizard = wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    bound_wizard.submit({"account_type": "business"})
    response = bound_wizard.replay()

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is BusinessDetailsForm


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
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.replay()

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
    bound_wizard = linear_wizard.get_bound_wizard(request)
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
    first_bound_wizard = linear_wizard.get_bound_wizard(request)
    first_bound_wizard.retrieve("first-run")

    first_bound_wizard.submit({"name": "Ada"})
    second_bound_wizard = linear_wizard.get_bound_wizard(request)
    second_bound_wizard.retrieve("second-run")
    first_response = first_bound_wizard.replay()
    second_response = second_bound_wizard.replay()

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
    bound_wizard = linear_wizard.get_bound_wizard(request)
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
    bound_wizard = linear_wizard.get_bound_wizard(request)
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
    bound_wizard = linear_wizard.get_bound_wizard(request)
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
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.replay()

    assert response is None


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
    bound_wizard = linear_wizard.get_bound_wizard(request)
    bound_wizard.retrieve("existing-run")

    response = bound_wizard.replay()

    assert response.status_code == 200
    assert response.context_data["form"].__class__ is SecondStepForm
    assert TrackingFirstStepFormView.form_valid_call_count == 1
