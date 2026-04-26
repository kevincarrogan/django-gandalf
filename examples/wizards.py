from .core import Wizard, condition, is_that, is_this
from .forms import (
    AWizardFirstForm,
    AWizardSecondForm,
    BWizardFirstForm,
    BWizardSecondForm,
    BWizardThirdForm,
    FirstForm,
    ManagementFormClass,
    MyFinalForm,
    SecondForm,
    ThirdForm,
)

that_wizard = (
    Wizard()
    .step(BWizardFirstForm)
    .branch(
        condition(is_this, BWizardSecondForm),
        default=BWizardThirdForm,
    )
)

main_wizard = (
    Wizard()  # This will be used for high-level configuration
    .step(
        FirstForm,
    )  # This could possibly be a view instead (need to work out that concept)
    .step(SecondForm)
    .step(ThirdForm)
    .branch(
        condition(
            is_this,
            (
                Wizard()
                .step(
                    AWizardFirstForm,
                )
                .step(
                    AWizardSecondForm,
                )
            ),
        ),
        condition(is_that, that_wizard),
        # If neither condition is met then this would be skipped instead of erroring
    )
    .step(MyFinalForm)
)

configured = (
    Wizard(management_form_class=ManagementFormClass)
    .step(
        FirstForm,
    )
    .step(
        SecondForm,
    )
)
