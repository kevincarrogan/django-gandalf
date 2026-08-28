"""Test-client helpers for driving wizards in functional tests.

`WizardTestDriver` binds a Django test client to one wizard's published URL
names (`<url_name>`, `<url_name>-run`, `<url_name>-step`) and hands out
`WizardRun` objects that make requests and read stored state without the
caller ever touching the session keys directly. The module-level functions
peek at (and seed) the session stores for tests that arrange or assert on
raw run and stash payloads, and a journey's record — its member runs and
stashes, its collections, its data, its tombstone — under one journey key,
`"default"` unless the hub is mounted under a journey segment.

Wizards mounted with a custom URL scheme (overriding `get_wizard_url` /
`get_step_url`) fall outside the driver's contract; drive those with the
plain test client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from gandalf.storage import (
    JOURNEY_BUCKET,
    SessionJourneyStore,
    SessionStashStore,
    SessionStorage,
)
from gandalf.types import JourneyRecord, Metadata, RunData, Stash, State


if TYPE_CHECKING:
    # What the test client actually hands back: an `HttpResponse` with the
    # extras a test asserts on (`context`, `templates`, `json()`). The stub
    # is type-check-only, so the runtime name is the plain response class.
    from django.test.client import _MonkeyPatchedWSGIResponse as ClientResponse
else:
    ClientResponse = HttpResponse

__all__ = [
    "RunDiscoveryError",
    "WizardTestDriver",
    "WizardRun",
    "seed_collection_item",
    "seed_journey_complete",
    "seed_journey_data",
    "seed_run",
    "seed_member_run",
    "seed_member_stash",
    "seed_stash",
    "stored_collection_items",
    "stored_journey",
    "stored_journey_data",
    "stored_run",
    "stored_runs",
    "stored_member_run",
    "stored_member_runs",
    "stored_member_stash",
    "stored_member_stashes",
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


def stored_journey(client: Client, journey: str = "default") -> JourneyRecord:
    """The session's record for `journey`, or an empty dict before anything
    has been written to it — its member runs, its stashes, its collections,
    its data, or the tombstone a submitted journey leaves behind."""
    journeys: dict[str, JourneyRecord] = client.session.get(
        SessionJourneyStore.SESSION_KEY, {}
    )
    return journeys.get(journey, {})


def _seed_journey(
    client: Client, journey: str, name: str, key: str, value: Any
) -> None:
    session = client.session
    journeys = session.setdefault(SessionJourneyStore.SESSION_KEY, {})
    record = journeys.setdefault(journey, {})
    record.setdefault(name, {})[key] = value
    session.save()


def stored_member_runs(client: Client, journey: str = "default") -> dict[str, str]:
    """The journey's member-to-run mapping, or an empty dict before any member
    has been entered."""
    runs: dict[str, str] = stored_journey(client, journey).get("runs", {})
    return runs


def stored_member_run(client: Client, key: str, journey: str = "default") -> str | None:
    """The run id recorded for member `key`, or None when the member is not
    being answered.

    A member's completion is its stash, not its run — read it with
    `stored_member_stash(client, key)`.
    """
    return stored_member_runs(client, journey).get(key)


def seed_member_run(
    client: Client, key: str, run_id: str, journey: str = "default"
) -> None:
    """Record `run_id` as where member `key` is being answered.

    Creates the journey's record when the session has never held one. For
    arranging the states a hub reaches only after several requests: a
    member left half-answered, or one pointing at a run the storage no
    longer holds.
    """
    _seed_journey(client, journey, "runs", key, str(run_id))


def stored_member_stashes(client: Client, journey: str = "default") -> dict[str, Stash]:
    """The journey's stash mapping — one payload per finished member — or
    an empty dict before any member has finished."""
    stashes: dict[str, Stash] = stored_journey(client, journey).get("stashes", {})
    return stashes


def stored_member_stash(client: Client, key: str, journey: str = "default") -> Stash:
    """The stash a finished member left under `key`, raising `KeyError` for
    one that has not finished."""
    return stored_member_stashes(client, journey)[key]


def seed_member_stash(
    client: Client, key: str, payload: Stash, journey: str = "default"
) -> None:
    """Record member `key` as finished with `payload`. For arranging a hub
    with members already done, or a hand-built or tampered stash."""
    _seed_journey(client, journey, "stashes", key, payload)


def stored_journey_data(client: Client, journey: str = "default") -> Metadata:
    """The journey's decided facts — the raw envelope `store.data` reads,
    both buckets — or an empty dict before anything was written."""
    data: Metadata = stored_journey(client, journey).get("data", {})
    return data


def seed_journey_data(client: Client, data: Metadata, journey: str = "default") -> None:
    """Merge `data` into the journey's own decided facts (the top-level
    bucket `store.data` reads), keeping what is already there. For arranging
    a hub whose members have already decided something — an answer that
    hides or unlocks another member."""
    session = client.session
    journeys = session.setdefault(SessionJourneyStore.SESSION_KEY, {})
    record = journeys.setdefault(journey, {})
    record.setdefault("data", {}).setdefault(JOURNEY_BUCKET, {}).update(data)
    session.save()


def seed_journey_complete(client: Client, journey: str = "default") -> None:
    """Leave the tombstone a submitted journey leaves, keeping whatever data
    the session already holds for it."""
    session = client.session
    journeys = session.setdefault(SessionJourneyStore.SESSION_KEY, {})
    record = journeys.pop(journey, {})
    tombstone: JourneyRecord = {"completed": True}
    if record.get("data"):
        tombstone["data"] = record["data"]
    journeys[journey] = tombstone
    session.save()


def stored_collection_items(
    client: Client, key: str, journey: str = "default"
) -> list[str]:
    """The item ids a collection lists, in the order the user added them.

    Empty for a collection nobody has added to. A row exists from the moment
    an item is registered, so this includes items with no answers yet — which
    is what makes them distinguishable from items that were never added.
    """
    collections = stored_journey(client, journey).get("collections", {})
    record = collections.get(key)
    if record is None:
        return []
    return [item["id"] for item in record.get("items", [])]


def seed_collection_item(
    client: Client,
    key: str,
    item_id: str,
    title: str | None = None,
    journey: str = "default",
) -> None:
    """Register an item, optionally with the title a finished one would have
    cached. For arranging the states a collection reaches only after several
    requests."""
    session = client.session
    journeys = session.setdefault(SessionJourneyStore.SESSION_KEY, {})
    record = journeys.setdefault(journey, {})
    collections = record.setdefault("collections", {})
    collection = collections.setdefault(key, {"items": [], "declared_done": False})
    collection["items"].append({"id": str(item_id), "title": title})
    session.save()


class WizardTestDriver:
    """Drives one wizard, mounted via `WizardViewSet.urls()`, through a
    Django test client.

    `url_kwargs` are the mount-prefix kwargs (for a wizard mounted under
    `path("prefix/<slug:org>/", include(...))`, pass `org=...`); they are
    forwarded into every URL reversal.

    The `Test` in the name is structural rather than a note about where to
    use it: this takes a `django.test.Client` and cannot work without one,
    so a test is the only place it runs. What it proves is the whole HTTP
    stack — reversal, dispatch, redirects, the session — which is exactly
    what a caller answering a wizard without a browser wants to skip.
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

    def __init__(self, driver: WizardTestDriver, run_id: str) -> None:
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
