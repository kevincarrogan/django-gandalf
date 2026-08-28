"""The demo site's front door and the banner it puts on every wizard page.

`just serve` publishes every wizard in the test app. These tests hold the
catalogue that organises them honest: a wizard nobody grouped is a wizard
nobody can find, and a wizard page that does not say which example it is
leaves the reader guessing at exactly the moment they are trying to test
something.
"""

from http import HTTPStatus

from django.urls import reverse
import pytest
from pytest_django.asserts import assertContains, assertTemplateUsed

from tests.testapp import catalogue


def test_every_published_wizard_is_catalogued():
    """A wizard mounted but ungrouped would vanish from the index."""
    catalogued = {
        example.url_name for group in catalogue.groups() for example in group.examples
    }

    assert catalogue.published_url_names() - catalogued == set()


def test_no_example_is_catalogued_under_two_groups():
    """One home each, so the index reads as a taxonomy rather than a pile."""
    homes = {}
    for group in catalogue.groups():
        for example in group.examples:
            homes.setdefault(example.url_name, set()).add(group.title)

    assert {name: titles for name, titles in homes.items() if len(titles) > 1} == {}


def test_every_catalogued_example_resolves_to_a_live_url():
    """Including the ones mounted under a tenant or plan prefix, which only
    reverse when the catalogue supplies the kwarg."""
    resolved = [example for group in catalogue.resolve() for example in group.examples]

    assert resolved
    assert all(example.url for example in resolved)


def test_index_page_groups_the_examples_with_an_explanation(client):
    # `just serve` lands on this page.
    response = client.get(reverse("index"))

    assert response.status_code == HTTPStatus.OK
    assertTemplateUsed(response, "testapp/index.html")
    groups = response.context["groups"]
    assert [group.title for group in groups] == [
        group.title for group in catalogue.groups()
    ]
    # Each group says what it is for, not just what is in it.
    assert all(group.blurb for group in groups)
    assertContains(response, groups[0].blurb)


def test_index_page_links_to_examples_that_need_a_mount_kwarg(client):
    """`org-scoped-wizard` is mounted under a tenant slug, so it never
    reversed bare and used to be dropped from the index altogether."""
    response = client.get(reverse("index"))

    assertContains(response, reverse("org-scoped-wizard", kwargs={"org": "acme"}))


@pytest.mark.parametrize(
    "url_name, expected",
    [
        ("linear-wizard", "LinearWizardViewSet"),
        ("readme-first", "FirstApplicationViewSet"),
    ],
)
def test_a_wizard_page_names_the_example_it_is_running(client, url_name, expected):
    """Thirty wizards share `linear_wizard.html`; without the banner the page
    cannot tell you which of them you are looking at."""
    response = client.get(reverse(url_name), follow=True)

    assert response.status_code == HTTPStatus.OK
    assertContains(response, expected)
    assertContains(response, catalogue.entry_for(url_name).description)


def test_a_wizard_page_names_the_template_rendering_it(client):
    """Several examples exist only to prove which template got picked."""
    response = client.get(reverse("other-linear-wizard"), follow=True)

    assertContains(response, "testapp/other_linear_wizard.html")


def test_a_wizard_page_links_back_to_the_index(client):
    response = client.get(reverse("linear-wizard"), follow=True)

    assertContains(response, f'href="{reverse("index")}"')
