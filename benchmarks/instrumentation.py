"""Counting wrappers around the runtime's two hot seams.

The point of counting rather than timing: dispatch counts are exact,
machine-independent and reproducible, so they answer "how many times does a
request re-validate a completed step?" as a fact rather than an estimate.
Wall time answers a different question and belongs in a separate pass.

Both wrappers are installed through `configure()`, so nothing in `gandalf`
knows they exist:

    wizard.configure(
        step_dispatcher_class=CountingStepDispatcher,
        cursor_walker_class=CountingCursorWalker,
    )
"""

import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from gandalf.runtime import CursorWalker, StepDispatcher


@dataclass
class RequestLog:
    """What one HTTP request cost the runtime.

    `validations` is the number the architecture is on trial for: it is the
    count of completed steps re-proved by re-dispatching their form view, and
    it should grow with the run's length.
    """

    validations: int = 0
    renders: int = 0
    walks: int = 0
    # Every POST request the dispatcher built, whether or not it went on to
    # be dispatched. See `form_rebuilds`.
    post_builds: int = 0
    # One `(caller, caller's caller, validations)` per root walk, so a
    # request's walks can be attributed to the code that asked for them
    # rather than inferred by reading.
    walk_sites: list = dataclass_field(default_factory=list)

    @property
    def dispatches(self):
        return self.validations + self.renders

    @property
    def form_rebuilds(self):
        """`RuntimeStep.form` accesses — branch predicates, mostly.

        `.form` reconstructs and re-validates a step's form *without* going
        through `StepDispatcher.dispatch`: it instantiates the view and calls
        `get_form()` directly (`gandalf/runtime.py`). So it is invisible to a
        dispatch counter, even though it costs a full form validation.

        It does still go through `build_request("POST")`, and every walk
        dispatch is preceded by exactly one of those, so the difference is
        the number of reconstructions.
        """
        return self.post_builds - self.validations

    @property
    def validation_cost(self):
        """Full form validations, however they were reached."""
        return self.validations + self.form_rebuilds


class DispatchCounter:
    """Collects counts for the request currently being measured.

    A module-level singleton rather than per-`BoundWizard` state because a
    single request builds several walkers and dispatchers, and the question
    is about the request as a whole. Benchmarks are single-threaded; this is
    not safe for concurrent use and is not meant to be.
    """

    def __init__(self):
        self._log = None
        self._depth = 0
        self._walk_started_at = 0

    def start(self):
        self._log = RequestLog()
        self._depth = 0

    def finish(self):
        log, self._log = self._log, None
        return log

    def record_dispatch(self, method):
        """A step form view was dispatched.

        POST means the walk is re-proving a stored answer; GET means a step
        is actually being rendered for the user (the cursor render, or an
        edit form pre-filled from storage).
        """
        if self._log is None:
            return
        if method == "POST":
            self._log.validations += 1
        else:
            self._log.renders += 1

    def record_build(self, method):
        if self._log is not None and method == "POST":
            self._log.post_builds += 1

    def enter_walk(self):
        """Count root walks only.

        `CursorWalker.visit_branch` recurses by constructing another walker
        of the same class and calling `walk()` on the selected arm, so
        counting every call would report tree shape rather than how many
        times the request walked.
        """
        if self._log is not None and self._depth == 0:
            self._log.walks += 1
            self._log.walk_sites.append(_walk_site())
            self._walk_started_at = self._log.validations
        self._depth += 1

    def exit_walk(self):
        self._depth -= 1
        if self._log is not None and self._depth == 0:
            site = self._log.walk_sites[-1]
            self._log.walk_sites[-1] = (
                *site,
                self._log.validations - self._walk_started_at,
            )


def _walk_site():
    """Who asked for this walk: the `BoundWizard` method, and its caller.

    Frame 0 is this function, 1 is `enter_walk`, 2 is
    `CountingCursorWalker.walk`, so the runtime method that started the walk
    is frame 3 and the viewset method that wanted it is frame 4.
    """
    return (
        sys._getframe(3).f_code.co_name,
        sys._getframe(4).f_code.co_name,
    )


COUNTER = DispatchCounter()


class CountingStepDispatcher(StepDispatcher):
    def dispatch(self, step, request, *args, **kwargs):
        COUNTER.record_dispatch(request.method)
        return super().dispatch(step, request, *args, **kwargs)

    def build_request(self, method, submission=None, files=None):
        COUNTER.record_build(method)
        return super().build_request(method, submission=submission, files=files)


class CountingCursorWalker(CursorWalker):
    def walk(self, root):
        COUNTER.enter_walk()
        try:
            return super().walk(root)
        finally:
            COUNTER.exit_walk()
