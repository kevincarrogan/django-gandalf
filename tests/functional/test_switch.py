"""Switch wizards over HTTP: routing on a value rather than on predicates."""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from gandalf.wizard import Wizard, declared_step_fields, on_field, switch
from tests.testapp import views
from tests.testapp.forms import BusinessDetailsForm


def test_a_switch_routes_to_the_case_its_selector_names(wizard_driver):
    driver = wizard_driver("switch-wizard")
    run = driver.start()

    run.post_step("account_kind", {"kind": "business"})

    response = run.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == run.step_url("business_name")


def test_a_switch_stores_its_answers_under_the_case_name(wizard_driver):
    """Not under a position — so reordering the cases later cannot strand
    the answers behind them."""
    driver = wizard_driver("switch-wizard")
    run = driver.start()

    run.post_steps(
        [
            ("account_kind", {"kind": "personal"}),
            ("preferred_name", {"preferred_name": "Ada"}),
        ]
    )

    assert run.state[1] == {
        "branch": {"personal": [{"step": {"preferred_name": "Ada"}}]}
    }


def test_a_de_selected_case_keeps_its_answers(wizard_driver):
    driver = wizard_driver("switch-wizard")
    run = driver.start()
    run.post_steps(
        [
            ("account_kind", {"kind": "business"}),
            ("business_name", {"business_name": "Ada Ltd"}),
        ]
    )

    run.post_step("account_kind", {"kind": "personal"})

    stored = run.state[1]["branch"]
    assert stored["business"] == [{"step": {"business_name": "Ada Ltd"}}]


def test_a_value_no_case_names_takes_the_default(wizard_driver):
    driver = wizard_driver("switch-wizard")
    run = driver.start()

    run.post_step("account_kind", {"kind": "charity"})

    response = run.get()
    assert response["Location"] == run.step_url("anything_else")


def test_a_switch_can_be_the_wizards_very_first_node(client):
    """Declared with the module-level entry point, so the switch decides
    before any step has been answered."""
    response = client.get(reverse("switch-entry-wizard"), follow=True)

    assert response.status_code == HTTPStatus.OK
    assert "second" in response.redirect_chain[-1][0]


def test_a_switch_case_cannot_be_called_default():
    with pytest.raises(ImproperlyConfigured, match="default"):
        switch(
            on_field("account_type", "account_type"),
            {"default": Wizard().step(BusinessDetailsForm, name="business")},
        )


def test_on_field_naming_no_field_of_its_step_is_refused():
    """The value of a field nothing asks is "", which names no case, so the
    run would take `default` with nothing going wrong out loud."""
    with pytest.raises(ImproperlyConfigured, match="names no field of step"):
        (
            Wizard()
            .step(views.AccountKindForm, name="account_kind")
            .switch(
                on_field("account_kind", "nonexistent"),
                {"business": Wizard().step(BusinessDetailsForm, name="business")},
            )
            .configure(template_name="testapp/linear_wizard.html")
        )


def test_on_field_naming_a_repeated_step_is_refused():
    """A formset answers with a row per entry, so a row's field has no
    single value to switch on. The declaration says "no fields at step
    level" rather than "unknown", which is the difference between refusing
    this now and dying mid-walk on the `cleaned_data.get()` of a list."""
    wizard = (
        Wizard()
        .step(views.OpeningHoursStepView, name="opening-hours")
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert declared_step_fields(wizard) == {"opening-hours": {}}

    with pytest.raises(ImproperlyConfigured, match="no fields of its own"):
        (
            Wizard()
            .step(views.OpeningHoursStepView, name="opening-hours")
            .switch(
                on_field("opening-hours", "day"),
                {"monday": Wizard().step(BusinessDetailsForm, name="business")},
            )
            .configure(template_name="testapp/linear_wizard.html")
        )


def test_an_unnamed_step_is_not_a_name_a_selector_can_be_checked_against():
    """A step with no name cannot be addressed, so it is absent from what
    the declaration offers a selector."""
    wizard = (
        Wizard()
        .step(BusinessDetailsForm)
        .configure(template_name="testapp/linear_wizard.html")
    )

    assert declared_step_fields(wizard) == {}


def test_configure_refuses_a_key_it_does_not_read():
    with pytest.raises(ImproperlyConfigured, match="does not read observer_clas"):
        Wizard().step(BusinessDetailsForm, name="business").configure(
            template_name="testapp/linear_wizard.html", observer_clas=object
        )


def test_on_field_naming_an_undeclared_step_is_refused_before_any_walk(
    wizard_driver,
):
    """The wizard cannot be configured at all: a step name nothing declares
    can only ever read `""`, which names no case."""
    with pytest.raises(ImproperlyConfigured, match="nowhere"):
        wizard_driver("misdeclared-switch-wizard").start()


def test_on_field_names_a_declared_step_this_run_did_not_walk(wizard_driver):
    """The declaration is sound — the step is real — so it is the walk that
    finds nothing, and it says which step the selector wanted."""
    run = wizard_driver("off-route-switch-wizard").start()

    with pytest.raises(ImproperlyConfigured, match="never_walked"):
        run.post_step("account_kind", {"kind": "business"})


def _outline_of(viewset_class):
    return viewset_class.wizard.configure(
        template_name="testapp/linear_wizard.html"
    ).outline()


def test_a_wizard_describes_every_route_it_declares():
    """A description of the declaration, so it needs no run: every step,
    every fork with all of its possible routes, and a marker where the
    tree grows from an answer."""
    from tests.testapp.readme import ch04_expand

    branching = _outline_of(views.BranchingWizardViewSet)
    [_, branch, _] = branching
    assert branch["kind"] == "branch"
    assert [step["name"] for step in branch["arms"][0]["steps"]] == ["business_name"]
    assert [step["name"] for step in branch["default"]] == ["preferred_name"]

    # The README's organisation arm ends in an expansion, inside a branch.
    [_, branch, _] = _outline_of(ch04_expand.ExpandingApplicationViewSet)
    organisation = branch["arms"][0]["steps"]
    assert [entry["kind"] for entry in organisation] == [
        "step",
        "step",
        "switch",
        "step",
        "expand",
    ]


def test_a_switch_on_an_answer_says_which_answer_decides_it():
    switch = next(
        entry
        for entry in _outline_of(views.SwitchWizardViewSet)
        if entry["kind"] == "switch"
    )

    assert switch["source"] == {"step": "account_kind", "field": "kind"}
    assert [case["case"] for case in switch["cases"]] == ["business", "personal"]


def test_a_switch_decided_by_computation_still_names_its_outcomes():
    """An `on_field` switch says which answer decides it. One decided by
    arbitrary code cannot, but the outcomes are declared either way — so a
    caller still knows what the answers could be."""
    switch = next(
        entry
        for entry in _outline_of(views.SwitchEntryWizardViewSet)
        if entry["kind"] == "switch"
    )

    assert switch["decided_by"] == "_always_the_second_case"
    assert [case["case"] for case in switch["cases"]] == ["first", "second"]
    assert "source" not in switch
