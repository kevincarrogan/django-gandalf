"""Pytest plugin exposing the `wizard_driver` fixture.

Loaded through the `pytest11` entry point in every project with
django-gandalf installed — and imported at pytest bootstrap, before Django
settings are configured and before coverage starts. It therefore imports
only pytest at module level and defers `gandalf.testing` (and with it
Django) into the fixture body. Disable with `-p no:gandalf`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import pytest


if TYPE_CHECKING:
    from django.test import Client

    from gandalf.testing import WizardTestDriver


@pytest.fixture
def wizard_driver(client: Client) -> Callable[..., WizardTestDriver]:
    """Factory for `WizardTestDriver` bound to pytest-django's `client`:
    `wizard_driver("signup")` or `wizard_driver("onboarding", org="acme")`.
    """
    from gandalf.testing import WizardTestDriver

    def factory(url_name: str, **url_kwargs: Any) -> WizardTestDriver:
        return WizardTestDriver(client, url_name, **url_kwargs)

    return factory
