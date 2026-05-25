import uuid

from gandalf import tree
from gandalf.storage import SessionStorage, WizardState
from tests.testapp.forms import (
    AccountTypeForm,
    BusinessDetailsForm,
    FirstStepForm,
    PersonalDetailsForm,
    ReviewForm,
    SecondStepForm,
)


def _select_first_arm(branch_node, submissions):
    return branch_node.arms[0][1]


class _Session(dict):
    modified = False


class _Request:
    def __init__(self, session=None):
        self.session = _Session()
        if session:
            self.session.update(session)


def test_session_storage_initialise_creates_session_run():
    request = _Request()
    storage = SessionStorage(request)

    run_id = storage.initialise_run()

    assert uuid.UUID(run_id)
    assert request.session["gandalf_runs"] == {
        run_id: {},
    }


def test_session_storage_initialise_marks_session_modified():
    request = _Request()
    storage = SessionStorage(request)

    storage.initialise_run()

    assert request.session.modified is True


def test_session_storage_retrieve_run_preserves_url_run_id():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    run_id = storage.retrieve_run("existing-run")

    assert run_id == "existing-run"


def test_session_storage_retrieve_marks_session_modified():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    storage.retrieve_run("existing-run")

    assert request.session.modified is True


def test_session_storage_get_run_data_uses_url_run_id():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    storage = SessionStorage(request)

    run_data = storage.get_run_data("existing-run")

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_session_storage_get_run_data_accepts_uuid_run_id():
    run_id = uuid.uuid4()
    request = _Request(
        session={
            "gandalf_runs": {
                str(run_id): {
                    "state": [{"step": {"name": "Ada"}}],
                },
            },
        },
    )
    storage = SessionStorage(request)

    run_data = storage.get_run_data(run_id)

    assert run_data == {
        "state": [{"step": {"name": "Ada"}}],
    }


def test_session_storage_get_state_defaults_to_empty_list():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    state = storage.get_state("existing-run")

    assert state == []


def test_session_storage_set_state_persists_by_url_run_id():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    storage.set_state("existing-run", [{"step": {"name": "Ada"}}])

    assert request.session["gandalf_runs"] == {
        "existing-run": {
            "state": [{"step": {"name": "Ada"}}],
        },
    }


def test_session_storage_set_state_marks_session_modified():
    request = _Request(
        session={
            "gandalf_runs": {
                "existing-run": {},
            },
        },
    )
    storage = SessionStorage(request)

    storage.set_state("existing-run", [{"step": {"name": "Ada"}}])

    assert request.session.modified is True


def _arm_is_business(request):
    return request.wizard.get_submissions()[0]["account_type"] == "business"


def _branching_tree():
    return tree.Step(
        AccountTypeForm,
        next=tree.Branch(
            arms=((_arm_is_business, tree.Step(BusinessDetailsForm)),),
            default=tree.Step(PersonalDetailsForm),
            next=tree.Step(ReviewForm),
        ),
    )


def test_wizard_state_walk_yields_step_stored_pairs_in_order():
    state = WizardState(
        [
            {"step": {"name": "Ada"}},
            {"step": {"email": "ada@example.com"}},
        ],
    )
    root = tree.Step(FirstStepForm, next=tree.Step(SecondStepForm))

    pairs = list(state.walk(root, _select_first_arm))

    assert pairs == [
        (root, {"name": "Ada"}),
        (root.next, {"email": "ada@example.com"}),
    ]


def test_wizard_state_walk_yields_one_none_after_stored_entries():
    state = WizardState([{"step": {"name": "Ada"}}])
    root = tree.Step(
        FirstStepForm,
        next=tree.Step(SecondStepForm, next=tree.Step(FirstStepForm)),
    )

    pairs = list(state.walk(root, _select_first_arm))

    assert pairs == [
        (root, {"name": "Ada"}),
        (root.next, None),
    ]


def test_wizard_state_walk_descends_into_matching_branch_arm():
    state = WizardState(
        [
            {"step": {"account_type": "business"}},
            {"branch": [{"step": {"business_name": "Acme"}}]},
        ],
    )
    root = _branching_tree()

    pairs = list(state.walk(root, _select_first_arm))

    account_step = root
    business_step = root.next.arms[0][1]
    review_step = root.next.next
    assert pairs == [
        (account_step, {"account_type": "business"}),
        (business_step, {"business_name": "Acme"}),
        (review_step, None),
    ]


def test_wizard_state_submissions_flattens_branch_substate():
    state = WizardState(
        [
            {"step": {"account_type": "business"}},
            {"branch": [{"step": {"business_name": "Acme"}}]},
            {"step": {"confirmed": True}},
        ],
    )

    assert state.submissions() == [
        {"account_type": "business"},
        {"business_name": "Acme"},
        {"confirmed": True},
    ]
