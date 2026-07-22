"""Drives a generated wizard through a full run, one HTTP request at a time.

Redirects are followed by hand rather than with `follow=True` so that every
record is exactly one request: the PRG cycle means completing a step costs a
POST *and* the GET that renders the next one, and those two have very
different costs. Collapsing them would hide the shape.

State is never seeded directly — the run is driven the way a user would, so
the numbers include everything a real request pays for.
"""

import time
import types
from dataclasses import dataclass
from http import HTTPStatus

from django.test import Client, override_settings
from django.urls import reverse

from benchmarks.instrumentation import COUNTER, RequestLog


MAX_REDIRECTS = 10

REDIRECTS = frozenset({HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.FOUND})


@dataclass
class RequestRecord:
    index: int
    method: str
    path: str
    status: int
    log: RequestLog
    seconds: float
    # Index of the step this request belongs to, or None for the requests
    # that start the run before any step is answered.
    step_index: int | None


def _urlconf(viewset_class):
    """A throwaway urlconf module publishing just this wizard."""
    module = types.ModuleType("benchmarks._urlconf")
    module.urlpatterns = viewset_class.urls()
    return module


def _request(client, records, method, path, step_index, data=None):
    COUNTER.start()
    started = time.perf_counter()
    if method == "GET":
        response = client.get(path)
    else:
        response = client.post(path, data=data)
    elapsed = time.perf_counter() - started
    records.append(
        RequestRecord(
            index=len(records),
            method=method,
            path=path,
            status=response.status_code,
            log=COUNTER.finish(),
            seconds=elapsed,
            step_index=step_index,
        )
    )
    return response


def _follow(client, records, path, step_index):
    """GET `path`, following redirects, recording each hop separately."""
    for _ in range(MAX_REDIRECTS):
        response = _request(client, records, "GET", path, step_index)
        if response.status_code not in REDIRECTS:
            return response, path
        path = response["Location"]
    raise RuntimeError(f"redirect loop reaching {path}")


def _segment(path):
    return path.rstrip("/").rsplit("/", 1)[-1]


def run_journey(benchmark):
    """Answer every step of `benchmark` in order, returning one record per
    HTTP request made."""
    records = []
    with override_settings(ROOT_URLCONF=_urlconf(benchmark.viewset_class)):
        client = Client()
        start_url = reverse(benchmark.viewset_class.url_name)
        _, path = _follow(client, records, start_url, None)

        for step_index in range(benchmark.path_length):
            payload = benchmark.payloads[_segment(path)]
            response = _request(client, records, "POST", path, step_index, payload)
            if response.status_code not in REDIRECTS:
                # The run finished: the final POST rendered done() directly
                # rather than redirecting on to another step.
                break
            _, path = _follow(client, records, response["Location"], step_index)

    return records


def _accumulate(target, log):
    """Add `log` into `target`, which is always a bucket owned by the caller
    — never a record's own log, which would corrupt later totals."""
    target.validations += log.validations
    target.renders += log.renders
    target.walks += log.walks
    target.post_builds += log.post_builds
    return target


@dataclass
class StepCost:
    """The cost of completing one step: its POST, plus every GET that
    followed before the user could answer the next one."""

    step_index: int
    post: RequestLog
    get: RequestLog

    @property
    def validation_cost(self):
        return self.post.validation_cost + self.get.validation_cost

    @property
    def walks(self):
        return self.post.walks + self.get.walks


def step_costs(records):
    costs = []
    for record in records:
        if record.step_index is None:
            continue
        if record.method == "POST":
            costs.append(
                StepCost(
                    step_index=record.step_index,
                    post=_accumulate(RequestLog(), record.log),
                    get=RequestLog(),
                )
            )
        elif costs:
            _accumulate(costs[-1].get, record.log)
    return costs


def journey_totals(records):
    total = RequestLog()
    for record in records:
        _accumulate(total, record.log)
    return total
