"""Dispatch-count report: `just bench`.

Answers, exactly and reproducibly, how many times a request re-validates a
completed step. Wall time is shown alongside but is not the point of this
pass — these are single unwarmed runs on whatever machine you are on.
"""

import os

import django


def _setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "benchmarks.settings")
    django.setup()


_setup()

from benchmarks.journey import (  # noqa: E402
    journey_totals,
    run_journey,
    step_costs,
)
from benchmarks.wizards import (  # noqa: E402
    branching_wizard,
    dynamic_wizard,
    linear_wizard,
)


def print_requests(benchmark):
    """Every request of one run, so the PRG shape is visible."""
    records = run_journey(benchmark)
    print(f"\n{benchmark.label} — every request\n")
    header = f"{'#':>3}  {'method':<6}  {'step':>4}  {'walks':>5}  {'valid':>5}  {'rebuild':>7}  {'render':>6}  {'ms':>7}"
    print(header)
    print("-" * len(header))
    for record in records:
        step = "-" if record.step_index is None else record.step_index
        log = record.log
        print(
            f"{record.index:>3}  {record.method:<6}  {step:>4}  "
            f"{log.walks:>5}  {log.validations:>5}  {log.form_rebuilds:>7}  "
            f"{log.renders:>6}  {record.seconds * 1000:>7.1f}"
        )
    return records


def print_step_costs(benchmark, records):
    """Per-step cost, which is where the linear-in-position growth shows."""
    print(f"\n{benchmark.label} — cost of completing each step\n")
    header = (
        f"{'step':>4}  {'POST walks':>10}  {'POST valid':>10}  "
        f"{'GET walks':>9}  {'GET valid':>9}  {'validations':>11}"
    )
    print(header)
    print("-" * len(header))
    for cost in step_costs(records):
        print(
            f"{cost.step_index:>4}  {cost.post.walks:>10}  "
            f"{cost.post.validation_cost:>10}  {cost.get.walks:>9}  "
            f"{cost.get.validation_cost:>9}  {cost.validation_cost:>11}"
        )


def print_scaling(builder, sizes, describe):
    """Whole-journey totals across sizes — the quadratic, if it is there."""
    print(f"\nScaling — {describe}\n")
    header = (
        f"{'steps':>6}  {'requests':>8}  {'walks':>6}  {'validations':>11}  "
        f"{'per step':>8}  {'ratio':>6}  {'ms':>8}"
    )
    print(header)
    print("-" * len(header))
    previous = None
    for size in sizes:
        benchmark = builder(size)
        records = run_journey(benchmark)
        totals = journey_totals(records)
        seconds = sum(record.seconds for record in records)
        steps = benchmark.path_length
        ratio = "-" if previous is None else f"{totals.validation_cost / previous:.2f}"
        previous = totals.validation_cost
        print(
            f"{steps:>6}  {len(records):>8}  {totals.walks:>6}  "
            f"{totals.validation_cost:>11}  "
            f"{totals.validation_cost / steps:>8.1f}  {ratio:>6}  "
            f"{seconds * 1000:>8.1f}"
        )


def print_shapes(benchmarks):
    """Walks per POST by wizard shape.

    `_refreshed_cursor` reuses the walk `_routed_post` already did when
    re-resolving hands back the same wizard object. That holds for a
    `ConfiguredWizard` class attribute; a plain `Wizard` is reconfigured
    into a new object every resolve, and a dynamic `get_wizard()` builds a
    genuinely new tree — so both keep the fourth walk, the latter because it
    must.
    """
    print("\nWalks per POST by wizard shape\n")
    header = f"{'shape':<50}  {'walks/POST':>10}  {'validations':>11}"
    print(header)
    print("-" * len(header))
    for benchmark in benchmarks:
        records = run_journey(benchmark)
        totals = journey_totals(records)
        walks = sorted({r.log.walks for r in records if r.method == "POST"})
        spread = ",".join(str(w) for w in walks)
        print(f"{benchmark.label:<50}  {spread:>10}  {totals.validation_cost:>11}")


def main():
    small = linear_wizard(steps=5)
    records = print_requests(small)
    print_step_costs(small, records)

    print_scaling(
        lambda steps: linear_wizard(steps=steps),
        [5, 10, 15, 20, 30],
        "linear wizard, 1 field, free clean(). "
        "Doubling the steps should roughly quadruple validations.",
    )

    print_scaling(
        lambda steps: linear_wizard(steps=steps, fields=10),
        [5, 15, 30],
        "linear wizard, 10 fields. Counts should be identical to 1 field — "
        "fields change the cost of a validation, not how many happen.",
    )

    print_shapes(
        [
            linear_wizard(steps=10, preconfigured=True),
            linear_wizard(steps=10, preconfigured=False),
            dynamic_wizard(items=9),
        ]
    )

    # Same path length as a 12-step linear wizard, so any difference in
    # validations is what branching itself costs.
    branching = branching_wizard(sections=3, arm_steps=3)
    branching_records = run_journey(branching)
    linear_twelve = linear_wizard(steps=12)
    linear_records = run_journey(linear_twelve)
    print("\nBranching vs linear at the same path length\n")
    for label, totals, length in (
        (
            branching.label,
            journey_totals(branching_records),
            branching.path_length,
        ),
        (
            linear_twelve.label,
            journey_totals(linear_records),
            linear_twelve.path_length,
        ),
    ):
        print(
            f"  {label:<52} path={length:<3} walks={totals.walks:<5} "
            f"validations={totals.validation_cost:<5} "
            f"(dispatched={totals.validations}, "
            f"predicate rebuilds={totals.form_rebuilds})"
        )


if __name__ == "__main__":
    main()
