"""What a unit test needs to drive a `Run` with no viewset in the way."""

from gandalf.wizard import ConfiguredWizard, Wizard


def configured(wizard: Wizard, **seams: object) -> ConfiguredWizard:
    """A `ConfiguredWizard` for a test that builds a `Run` by hand.

    A viewset builds one from its own attributes (`configure_wizard()`);
    a test that has no viewset says the same seams as keywords. The
    template is the one most tests need, since a bare `Form` step has no
    view without it.
    """
    return ConfiguredWizard(wizard.tree, **seams)  # type: ignore[arg-type]
