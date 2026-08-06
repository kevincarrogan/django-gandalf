"""Test-client helpers for driving wizards in functional tests.

`WizardDriver` binds a Django test client to one wizard's published URL
names (`<url_name>`, `<url_name>-run`, `<url_name>-step`) and hands out
`WizardRun` objects that make requests and read stored state without the
caller ever touching the session keys directly. The module-level functions
peek at (and seed) the session stores for tests that arrange or assert on
raw run and stash payloads.

Wizards mounted with a custom URL scheme (overriding `get_wizard_url` /
`get_step_url`) fall outside the driver's contract; drive those with the
plain test client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from gandalf.storage import SessionSectionStore, SessionStashStore, SessionStorage
from gandalf.types import RunData, Stash, State


if TYPE_CHECKING:
    # What the test client actually hands back: an `HttpResponse` with the
    # extras a test asserts on (`context`, `templates`, `json()`). The stub
    # is type-check-only, so the runtime name is the plain response class.
    from django.test.client import _MonkeyPatchedWSGIResponse as ClientResponse
else:
    ClientResponse = HttpResponse

__all__ = [
    "RunDiscoveryError",
    "WizardDriver",
    "WizardRun",
    "seed_run",
    "seed_section_run",
    "seed_stash",
    "stored_run",
    "stored_runs",
    "stored_section_run",
    "stored_section_runs",
    "stored_stash",
    "stored_stashes",
]


class RunDiscoveryError(AssertionError):
    """The session does not identify exactly one run — none where one was
    expected, or several where the discovery needed to be unambiguous."""


def stored_runs(client: Client) -> dict[str, RunData]:
    """The session's run mapping, or an empty dict before any run exists.

    Live runs map to `{"state": [...]}`-shaped entries (an empty dict before
    the first answer); completed runs leave `{"completed": True}` tombstones.
    """
    runs: dict[str, RunData] = client.session.get(SessionStorage.SESSION_KEY, {})
    return runs


def stored_run(client: Client, run_id: str) -> RunData:
    """The raw session entry for `run_id`.

    Raises `KeyError` for a run this session does not hold — never started,
    obliterated, or lost with an expired session.
    """
    return stored_runs(client)[str(run_id)]


def seed_run(client: Client, run_id: str, data: RunData) -> None:
    """Write `data` verbatim as the session entry for `run_id`.

    Creates the run mapping when the session has never held one. For
    arranging runs the request cycle cannot produce: legacy state shapes,
    tampered entries, or runs addressed by a custom URL scheme.
    """
    session = client.session
    runs = session.setdefault(SessionStorage.SESSION_KEY, {})
    runs[str(run_id)] = data
    session.save()


def stored_stashes(client: Client) -> dict[str, Stash]:
    """The session's stash mapping, or an empty dict before any stash."""
    stashes: dict[str, Stash] = client.session.get(SessionStashStore.SESSION_KEY, {})
    return stashes


def stored_stash(client: Client, key: str) -> Stash:
    """The stash payload under `key`, raising `KeyError` when absent."""
    return stored_stashes(client)[key]


def seed_stash(client: Client, key: str, payload: Stash) -> None:
    """Write `payload` under `key` in the session stash store.

    Creates the stash mapping when the session has never held one. For
    arranging hand-built or tampered stashes.
    """
    session = client.session
    stashes = session.setdefault(SessionStashStore.SESSION_KEY, {})
    stashes[key] = payload
    session.save()


def stored_section_runs(client: Client) -> dict[str, str]:
    """The hub's section-to-run mapping, or an empty dict before any section
    has been entered."""
    runs: dict[str, str] = client.session.get(SessionSectionStore.RUNS_SESSION_KEY, {})
    return runs


def stored_section_run(client: Client, key: str) -> str | None:
    """The run id recorded for section `key`, or None when the section is not
    being answered.

    A section's completion lives in the stash store, not here — read it with
    `stored_stash(client, key)`.
    """
    return stored_section_runs(client).get(key)


def seed_section_run(client: Client, key: str, run_id: str) -> None:
    """Record `run_id` as where section `key` is being answered.

    Creates the mapping when the session has never held one. For arranging
    the states a hub reaches only after several requests: a section left
    half-answered, or one pointing at a run the storage no longer holds.
    """
    session = client.session
    runs = session.setdefault(SessionSectionStore.RUNS_SESSION_KEY, {})
    runs[key] = str(run_id)
    session.save()


class WizardDriver:
    """Drives one wizard, mounted via `WizardViewSet.urls()`, through a
    Django test client.

    `url_kwargs` are the mount-prefix kwargs (for a wizard mounted under
    `path("prefix/<slug:org>/", include(...))`, pass `org=...`); they are
    forwarded into every URL reversal.
    """

    def __init__(self, client: Client, url_name: str, **url_kwargs: Any) -> None:
        self.client = client
        self.url_name = url_name
        self.url_kwargs = url_kwargs

    @property
    def start_url(self) -> str:
        """The wizard's start URL, which GETs into a fresh run."""
        return reverse(self.url_name, kwargs=self.url_kwargs)

    def run_url(self, run_id: str) -> str:
        """The bare run URL for `run_id`."""
        return reverse(
            f"{self.url_name}-run",
            kwargs={**self.url_kwargs, "run_id": run_id},
        )

    def step_url(self, run_id: str, step: str) -> str:
        """The routed URL for step segment `step` of `run_id`."""
        return reverse(
            f"{self.url_name}-step",
            kwargs={**self.url_kwargs, "run_id": run_id, "gandalf_step": step},
        )

    def start(self) -> WizardRun:
        """GET the start URL and return the `WizardRun` it created.

        The run id is discovered by diffing the session's run ids around the
        request, so starting works regardless of how many runs the session
        already holds. Raises `RunDiscoveryError` when the GET did not
        create exactly one run.
        """
        known = set(stored_runs(self.client))
        self.client.get(self.start_url)
        return self.new_run(*known)

    def drive(
        self, steps: list[tuple[str, dict[str, Any] | None]]
    ) -> tuple[ClientResponse | None, WizardRun]:
        """Start a run and POST each `(step, data)` pair in order, following
        redirects. Returns `(final_response, run)`."""
        run = self.start()
        return run.post_steps(steps), run

    def run(self, run_id: str) -> WizardRun:
        """Bind an existing run id — one a resurrect view created, a seeded
        run, or an id that was never started — without making a request."""
        return WizardRun(self, run_id)

    def only_run(self) -> WizardRun:
        """The session's only run, as a `WizardRun`.

        Raises `RunDiscoveryError` unless the session holds exactly one run
        (completion tombstones count).
        """
        runs = stored_runs(self.client)
        if len(runs) != 1:
            raise RunDiscoveryError(
                f"expected the session to hold exactly one run, found {len(runs)}"
            )
        (run_id,) = runs
        return self.run(run_id)

    def new_run(self, *known: WizardRun | str) -> WizardRun:
        """The one run in the session that is not in `known` (given as
        `WizardRun` instances or run-id strings).

        Raises `RunDiscoveryError` unless exactly one run is new.
        """
        known_ids = set()
        for run in known:
            if isinstance(run, WizardRun):
                known_ids.add(run.run_id)
            else:
                known_ids.add(str(run))
        new_ids = set(stored_runs(self.client)) - known_ids
        if len(new_ids) != 1:
            raise RunDiscoveryError(
                f"expected exactly one run the session did not already "
                f"hold, found {len(new_ids)}"
            )
        return self.run(new_ids.pop())


class WizardRun:
    """One run of a driver's wizard: request helpers and stored-state access
    keyed by `run_id`.

    Request helpers default to `follow=False`, matching `django.test.Client`,
    so redirect assertions read naturally; pass `follow=True` to land on the
    rendered step. `post_steps` always follows, because advancing through
    the POST-redirect-GET cycle is its whole point.
    """

    def __init__(self, driver: WizardDriver, run_id: str) -> None:
        self.driver = driver
        self.run_id = str(run_id)

    @property
    def url(self) -> str:
        """The bare run URL — GETs redirect to the cursor step, or complete
        the run."""
        return self.driver.run_url(self.run_id)

    def step_url(self, step: str) -> str:
        """This run's routed URL for step segment `step`."""
        return self.driver.step_url(self.run_id, step)

    def get(self, follow: bool = False) -> ClientResponse:
        """GET the bare run URL."""
        return self.driver.client.get(self.url, follow=follow)

    def get_step(self, step: str, follow: bool = False) -> ClientResponse:
        """GET a step URL — the render, or the edit render of an answered
        step."""
        return self.driver.client.get(self.step_url(step), follow=follow)

    def post(
        self, data: dict[str, Any] | None = None, follow: bool = False
    ) -> ClientResponse:
        """POST to the bare run URL — the step-less POST the viewset bounces
        back to the cursor."""
        return self.driver.client.post(self.url, data=data, follow=follow)

    def post_step(
        self, step: str, data: dict[str, Any] | None = None, follow: bool = False
    ) -> ClientResponse:
        """POST `data` to a step URL. Uploads ride along as ordinary `data`
        values (`SimpleUploadedFile` and friends) — the test client
        multipart-encodes them as usual."""
        return self.driver.client.post(self.step_url(step), data=data, follow=follow)

    def post_steps(
        self, steps: list[tuple[str, dict[str, Any] | None]]
    ) -> ClientResponse | None:
        """POST each `(step, data)` pair in order with `follow=True`,
        returning the last response."""
        response = None
        for step, data in steps:
            response = self.post_step(step, data, follow=True)
        return response

    @property
    def data(self) -> RunData:
        """The raw session entry: `{}` for a fresh run, `{"state": [...]}`
        once answered, `{"completed": True}` after completion. Exact-shape
        assertions (tombstones, `files` entries) go through this."""
        return stored_run(self.driver.client, self.run_id)

    @property
    def state(self) -> State:
        """The stored state list — empty for a fresh or completed run."""
        state: State = self.data.get("state", [])
        return state

    @property
    def is_completed(self) -> bool:
        """Whether the run has finished, leaving a completion tombstone."""
        completed: bool = self.data.get("completed", False)
        return completed

    def seed_state(self, state: State) -> None:
        """Overwrite this run's stored state list, arranging session state
        the request cycle cannot produce."""
        data = dict(self.data)
        data["state"] = state
        seed_run(self.driver.client, self.run_id, data)
