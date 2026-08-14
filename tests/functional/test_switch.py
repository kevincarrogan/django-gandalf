"""Switch wizards over HTTP: routing on a value rather than on predicates."""

from http import HTTPStatus

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from gandalf.wizard import Wizard, on_field, switch
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
