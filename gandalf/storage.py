from __future__ import annotations

import uuid
from typing import cast

from django.http import HttpRequest

from gandalf.types import RunData, Stash, State


class RunNotFound(LookupError):
    """Raised when a run id names no run this session can serve — never
    started, already forgotten, or lost with an expired session."""


class StashNotFound(LookupError):
    """Raised when a stash key names no stored payload — never stashed,
    already popped, or lost with an expired session."""


class SessionStorage:
    SESSION_KEY = "gandalf_runs"
    # A completed run leaves a tombstone behind so a revisit can be answered
    # as finished rather than mistaken for one that never existed. Tombstones
    # are tiny, but a session is not unbounded (the cookie backend caps at
    # 4KB), so only the most recently completed are kept.
    max_completed_runs = 25

    def __init__(self, request: HttpRequest) -> None:
        self.request = request

    def _runs(self) -> dict[str, RunData]:
        # The session is an untyped JSON store; what Gandalf keeps under its
        # own key is this shape by construction.
        return cast(dict[str, RunData], self.request.session.get(self.SESSION_KEY, {}))

    def initialise_run(self) -> str:
        run_id = str(uuid.uuid4())
        gandalf_runs = self.request.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[run_id] = {}
        self.request.session.modified = True
        return run_id

    def retrieve_run(self, run_id: str) -> str:
        """Return the run id as given, raising `RunNotFound` when this
        session holds no such run."""
        self.get_run_data(run_id)
        self.request.session.modified = True
        return run_id

    def get_run_data(self, run_id: str) -> RunData:
        run_data = self._runs().get(str(run_id))
        if run_data is None:
            raise RunNotFound(str(run_id))
        return run_data

    def get_state(self, run_id: str) -> State:
        run_data = self.get_run_data(run_id)
        return cast(State, run_data.get("state", []))

    def set_state(self, run_id: str, state: State) -> None:
        run_data = self.get_run_data(run_id)
        run_data["state"] = state
        self.request.session.modified = True

    def delete_run(self, run_id: str) -> None:
        """Forget the run entirely. Idempotent: deleting an unknown run is
        not an error, so callers need not check first."""
        gandalf_runs = self._runs()
        gandalf_runs.pop(str(run_id), None)
        self.request.session.modified = True

    def complete_run(self, run_id: str) -> None:
        """Replace the run's answers with a completion tombstone.

        The run stays addressable so a revisit is answerable — "this one is
        finished" rather than "no such run" — but its state is gone, so a
        completed run can neither be edited nor keep growing the session.
        Re-inserting the entry orders the mapping by completion, which is
        what lets pruning drop the oldest. Idempotent.
        """
        gandalf_runs = self._runs()
        run_id = str(run_id)
        gandalf_runs.pop(run_id, None)
        gandalf_runs[run_id] = {"completed": True}
        self._prune_completed(gandalf_runs)
        self.request.session.modified = True

    def is_run_complete(self, run_id: str) -> bool:
        run_data = self._runs().get(str(run_id))
        return bool(run_data and run_data.get("completed"))

    def _prune_completed(self, gandalf_runs: dict[str, RunData]) -> None:
        """Drop all but the `max_completed_runs` most recently completed
        tombstones. Runs still in progress are never pruned."""
        completed = [
            run_id for run_id, data in gandalf_runs.items() if data.get("completed")
        ]
        excess = max(0, len(completed) - self.max_completed_runs)
        for run_id in completed[:excess]:
            del gandalf_runs[run_id]


class SessionStashStore:
    """Session-backed home for stash payloads, for the common case where the
    caller has nowhere better to keep them.

    A stash is caller-owned — `BoundWizard.stash()` hands back a payload and
    the application decides where it lives. This store covers the simple
    arrangement: keyed payloads in the Django session, kept server-side so
    they cannot be tampered with in transit.
    """

    SESSION_KEY = "gandalf_stashes"

    def __init__(self, request: HttpRequest) -> None:
        self.request = request

    def _stashes(self) -> dict[str, Stash]:
        return cast(dict[str, Stash], self.request.session.get(self.SESSION_KEY, {}))

    def put(self, key: str, payload: Stash) -> None:
        """Store `payload` under `key`, replacing any existing stash."""
        stashes = self.request.session.setdefault(self.SESSION_KEY, {})
        stashes[key] = payload
        self.request.session.modified = True

    def get(self, key: str) -> Stash:
        """Return the stash under `key`, raising `StashNotFound` without one."""
        payload = self._stashes().get(key)
        if payload is None:
            raise StashNotFound(key)
        return payload

    def pop(self, key: str) -> Stash:
        """Remove and return the stash under `key`, raising `StashNotFound`
        without one."""
        payload = self.get(key)
        del self._stashes()[key]
        self.request.session.modified = True
        return payload

    def delete(self, key: str) -> None:
        """Forget the stash under `key`. Idempotent: deleting an unknown key
        is not an error, so callers need not check first."""
        self._stashes().pop(key, None)
        self.request.session.modified = True

    def keys(self) -> list[str]:
        """The stored stash keys, in insertion order."""
        return list(self._stashes())


class SessionSectionStore:
    """Session-backed home for a hub's bookkeeping: which run each section is
    currently being answered in, and the stash a finished one left behind.

    Two mappings, because they answer different questions and outlive each
    other. A run id says where an unfinished section can be picked up, and is
    forgotten the moment the section finishes. A payload is
    `BoundWizard.stash()` output and *is* the section's completion — a hub
    reads it and needs no run at all, which is what lets a completed section
    survive its run being pruned by `max_completed_runs`.

    The payload half is a plain `SessionStashStore`, so a project already
    stashing into the session keeps the same key space. Only the run registry
    is new.
    """

    RUNS_SESSION_KEY = "gandalf_section_runs"
    stash_store_class = SessionStashStore

    def __init__(self, request: HttpRequest) -> None:
        self.request = request
        self.stashes = self.stash_store_class(request)

    def _runs(self) -> dict[str, str]:
        return cast(dict[str, str], self.request.session.get(self.RUNS_SESSION_KEY, {}))

    def get_run(self, key: str) -> str | None:
        """The run this section is being answered in, or None when it is not
        being answered at all."""
        return self._runs().get(key)

    def set_run(self, key: str, run_id: str) -> None:
        """Record `run_id` as where this section is answered, replacing any
        run already recorded for it."""
        runs = self.request.session.setdefault(self.RUNS_SESSION_KEY, {})
        runs[key] = str(run_id)
        self.request.session.modified = True

    def clear_run(self, key: str) -> None:
        """Forget where this section was being answered. Idempotent: clearing
        a section with no run is not an error, so callers need not check
        first."""
        self._runs().pop(key, None)
        self.request.session.modified = True

    def get_stash(self, key: str) -> Stash:
        """The finished section's stash, raising `StashNotFound` without
        one."""
        return self.stashes.get(key)

    def has_stash(self, key: str) -> bool:
        """Whether this section has finished — what a hub row asks, answered
        without an exception to catch."""
        return key in self.keys()

    def put_stash(self, key: str, payload: Stash) -> None:
        """Record this section as finished, replacing any earlier answers."""
        self.stashes.put(key, payload)

    def delete_stash(self, key: str) -> None:
        """Forget that this section ever finished. Idempotent."""
        self.stashes.delete(key)

    def keys(self) -> list[str]:
        """The sections holding a stash, in insertion order."""
        return self.stashes.keys()
