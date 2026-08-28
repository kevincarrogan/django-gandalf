"""Switch wizards over HTTP: routing on a value rather than on predicates."""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from gandalf.wizard import Wizard, on_field, switch
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


def test_on_field_names_the_step_it_could_not_find(wizard_driver):
    """A selector reading a step that is not on the route is a declaration
    mistake, and says which step it wanted."""
    driver = wizard_driver("misdeclared-switch-wizard")
    run = driver.start()

    with pytest.raises(ImproperlyConfigured, match="nowhere"):
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
