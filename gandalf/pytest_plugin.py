"""Pytest plugin exposing the `wizard_driver` fixture.

Loaded through the `pytest11` entry point in every project with
django-gandalf installed — and imported at pytest bootstrap, before Django
settings are configured and before coverage starts. It therefore imports
only pytest at module level and defers `gandalf.testing` (and with it
Django) into the fixture body. Disable with `-p no:gandalf`.
"""

import pytest


@pytest.fixture
def wizard_driver(client):
    """Factory for `WizardDriver` bound to pytest-django's `client`:
    `wizard_driver("signup")` or `wizard_driver("onboarding", org="acme")`.
    """
    from gandalf.testing import WizardDriver

    def factory(url_name, **url_kwargs):
        return WizardDriver(client, url_name, **url_kwargs)

    return factory
