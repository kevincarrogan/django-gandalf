"""Benchmark harness for the sealed-walk runtime (see issue #46).

Deliberately outside `tests/` so it stays clear of the 100% coverage gate:
these modules are run by hand via `just bench`, not by pytest.
"""
