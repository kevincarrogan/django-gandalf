"""Counting wrappers for asserting how much work a request does.

Dispatch counts are exact and machine-independent, so a test can assert them
outright where a wall-clock timing could only be flaky. They are installed
through `configure()`, so nothing in `gandalf` knows they exist.

`benchmarks/instrumentation.py` carries a richer version for the benchmark
harness (walk call sites). This is deliberately the minimum the test suite
needs: `validations` counts dispatches made by the walk, and `form_rebuilds`
counts the `RuntimeStep.form` reconstructions the walk never sees — branch
predicates and summary rows, which build a form without going through the
dispatcher.
"""

from contextlib import contextmanager
from dataclasses import dataclass

from gandalf.runtime import CursorWalker, StepDispatcher


@dataclass
class WalkCount:
    # Root walks; a walk that descends into a branch arm still counts once.
    walks: int = 0
    # Stored answers re-proved by re-dispatching their form view.
    validations: int = 0
    # GET dispatches that render a step for the user.
    renders: int = 0
    # POST requests built without being dispatched: every walk dispatch is
    # preceded by exactly one build, so the difference is the number of
    # `RuntimeStep.form` reconstructions.
    post_builds: int = 0

    @property
    def form_rebuilds(self):
        return self.post_builds - self.validations


_active = []
_depth = 0


@contextmanager
def counting_walks():
    """Count the walks and dispatches made inside the block."""
    counts = WalkCount()
    _active.append(counts)
    try:
        yield counts
    finally:
        _active.remove(counts)


class CountingStepDispatcher(StepDispatcher):
    def dispatch(self, step, request, *args, **kwargs):
        if _active:
            counts = _active[-1]
            if request.method == "POST":
                counts.validations += 1
            else:
                counts.renders += 1
        return super().dispatch(step, request, *args, **kwargs)

    def build_request(self, method, *args, **kwargs):
        if _active and method == "POST":
            _active[-1].post_builds += 1
        return super().build_request(method, *args, **kwargs)


class CountingCursorWalker(CursorWalker):
    def walk(self, root):
        global _depth
        # Count root walks only: `visit_branch` recurses by building another
        # walker of this class and walking the selected arm, so counting
        # every call would report tree shape rather than how many times the
        # request walked.
        if _active and _depth == 0:
            _active[-1].walks += 1
        _depth += 1
        try:
            return super().walk(root)
        finally:
            _depth -= 1
