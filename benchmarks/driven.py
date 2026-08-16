"""The same wizard, driven from Python instead of through a browser.

`journey.py` answers "what does a request cost?". This answers the question
the driver raises: an agent does not make one request per step — it asks for
an outline, checks a bag of answers, then places them all at once — so what
does *that* cost, and how does it compare to the fourteen requests a person
would have made?

The same counting wrappers, so the numbers are comparable: a validation here
is a validation there.
"""

import time
import types
from dataclasses import dataclass

from django.test import override_settings

from benchmarks.instrumentation import COUNTER, RequestLog
from gandalf.driver import RunDriver, fabricate_request


@dataclass
class OperationRecord:
    """What one driver operation cost the runtime."""

    name: str
    log: RequestLog
    seconds: float


def _urlconf(viewset_class):
    module = types.ModuleType("benchmarks._urlconf")
    module.urlpatterns = viewset_class.urls()
    return module


def _timed(records, name, operation):
    COUNTER.start()
    started = time.perf_counter()
    result = operation()
    elapsed = time.perf_counter() - started
    records.append(OperationRecord(name=name, log=COUNTER.finish(), seconds=elapsed))
    return result


def run_driven(benchmark):
    """Fill `benchmark` the way an agent does — outline, check, prefill —
    returning one record per operation."""
    records = []
    answers = dict(benchmark.payloads)
    with override_settings(ROOT_URLCONF=_urlconf(benchmark.viewset_class)):
        request = fabricate_request()

        _timed(
            records,
            "outline",
            lambda: RunDriver.outline_for(benchmark.viewset_class, request=request),
        )
        driver = _timed(
            records,
            "begin",
            # The whole fill is measured, `done()` included, so this driver
            # is one that may conclude a run.
            lambda: RunDriver.begin(
                benchmark.viewset_class, request=request, may_finish=True
            ),
        )
        _timed(records, "check", lambda: driver.check(answers))
        _timed(records, "prefill", lambda: driver.prefill(answers))
        if driver.describe().complete:
            _timed(records, "finish", driver.finish)

    return records


def driven_totals(records):
    """Everything the whole fill cost."""
    total = RequestLog()
    for record in records:
        total.validations += record.log.validations
        total.renders += record.log.renders
        total.walks += record.log.walks
        total.post_builds += record.log.post_builds
    return total
