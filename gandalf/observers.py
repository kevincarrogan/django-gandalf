"""Watch a run without changing it.

Wizards are where journeys go wrong, and the questions are always the same
sort: which step do people get wrong most often, how many give up at the
address, does the branch that asks for company details lose people. None of
that is answerable from the outside — a run is a session key and a redirect
— and all of it is one line of bookkeeping from the inside.

An observer is that line. Declare one with
`.configure(observer_class=MyObserver)` and it is told what happened, as it
happens, for every run of that wizard: over HTTP, from a script, or from a
test. The default does nothing at all.

**Observers see what happened, never what was said.** A step's answers are
somebody's name, date of birth and address, and a library that handed those
to a metrics hook would put personal data somewhere nobody chose to put it.
So an observer is given the step *declaration* and the outcome — enough to
count, group and compare, and not enough to leak. If you need the answers
themselves, take them where you already have them and where the decision to
do so is visible: your own `done()`, or whatever is driving the run.

One event per placement, which is the other thing worth knowing. The walk
re-proves every stored answer on every request, so a validation is not the
same as a submission — counting validations would count the same mistake
once per later page. `submission()` fires only when an answer is actually
placed.

There is deliberately no "run started" event. A run exists before its
wizard is resolved — that ordering is what lets a dynamic `get_wizard()`
read the run's stored state to decide its own shape — so at the moment a
run is created there is no configured wizard to have an observer. Count
first submissions instead, or record the creation where you make it:
`WizardViewSet.begin()`, or the request that mints it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gandalf import tree
    from gandalf.types import Metadata


class WizardObserver:
    """No-op base. Subclass and override what you care about.

        class CountErrors(WizardObserver):
            def submission(self, step, accepted, metadata):
                if not accepted:
                    statsd.increment(
                        "wizard.rejected",
                        tags=[
                            f"step:{step.context['name']}",
                            f"run:{self.run_id}",
                            f"unattended:{bool((metadata or {}).get('unattended'))}",
                        ],
                    )

        wizard = Wizard().step(EmailForm, name="email").configure(
            template_name="signup/step.html",
            observer_class=CountErrors,
        )

    An observer is built once per run, on first use, and knows which run
    it is watching — so no event has to repeat it. It must not raise: it is
    called from inside the walk, and a metrics backend having a bad day
    should not take the wizard down with it. Catch your own exceptions.

    What it is *not* given is who is on the other end. The library still
    cannot know that: a submission arrives through a request, and whether
    that request is a person in a browser, a script, or a management
    command is your application's knowledge, not a wizard's. What it is
    given is whatever the placement *claimed* about itself — its metadata,
    recorded where that was known and carried here unread. A browser
    submission claims nothing and arrives as `None`; `RunDriver` marks its
    own `{"unattended": True}`. So in a journey people and agents share,
    an observer can count the two apart without the library ever having
    had to guess which it was watching.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def submission(
        self,
        step: tree.Step,
        accepted: bool,
        metadata: Metadata | None,
    ) -> None:
        """An answer was placed at `step`, and either satisfied it or did
        not.

        Fires once per placement — not for the replays the walk performs to
        re-prove earlier answers — so counting `accepted=False` counts
        mistakes people made, not pages they visited afterwards.

        `metadata` is whatever the placement recorded about itself, and is
        `None` for one that recorded nothing — which a browser submission
        always does, because a request carries no such claim. `RunDriver`
        marks its own placements `{"unattended": True}` by default, so an
        observer can count what a person answered separately from what
        something else did, without the library having had to guess.
        """

    def run_completed(self) -> None:
        """The run finished and was tombstoned. Fires after `done()`."""
