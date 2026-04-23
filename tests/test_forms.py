import pytest

from django.urls import reverse


@pytest.fixture()
def wizard_url():
    return reverse("wizard")


def test_first_step(client, wizard_url):
    response = client.get(wizard_url)
    assert response.status_code == 200
