class Wizard():
    def __init__(self, **configuration):
        pass

    def start(self, form):
        return self
    
    def then(self, form):
        return self
    
    def branch(self, *forms, otherwise=None):
        return self
    

class FirstForm:
    pass


class SecondForm:
    pass


class ThirdForm:
    pass


class MaybeThisForm:
    pass


class MaybeThatForm:
    pass


class MyFinalForm:
    pass


class AWizardFirstForm:
    pass


class AWizardSecondForm:
    pass


class BWizardFirstForm:
    pass


class BWizardSecondForm:
    pass


class BWizardThirdForm:
    pass


def is_this(wizard):
    pass


def is_that(wizard):
    pass


def condition(cond, flow):
    pass


that_wizard = (
    Wizard()
    .start(BWizardFirstForm)
    .branch(
        condition(is_this, BWizardSecondForm),
        otherwise=BWizardThirdForm,
    )
)


main_wizard = (
    Wizard()  # This will be used for high-level configuration
    .start(FirstForm)  # This could possibly be a view instead (need to work out that concept) - also starts to feel annoying to have to `start` each time, but maybe that's explicit
    .then(SecondForm)
    .then(ThirdForm)
    .branch(
        condition(
            is_this,
            Wizard().start(AWizardFirstForm).then(AWizardSecondForm),
        ),
        condition(is_that, that_wizard),
        # If neither condition is met then this would be skipped instead of erroring
    )
    .then(MyFinalForm)
)


class ManagementFormClass:
    pass


configured = (
    Wizard(management_form_class=ManagementFormClass)
    .start(FirstForm)
    .then(SecondForm)
)
