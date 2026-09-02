"""A JSON-safe bag of facts, written through to wherever it lives the moment
it changes.

Two things in Gandalf want exactly this shape: a run's record of what it did
outside itself (`RunMetadata`, in `gandalf.runtime`), and a journey's record
of what its sections decided (`JourneyMetadata`, in `gandalf.storage`). They
differ only in where the envelope is kept and what the sub-bags are called,
so the mapping lives here, behind a reader and a writer, and each of them is
a thin subclass naming its own buckets.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, MutableMapping
from copy import deepcopy
from typing import Any

from gandalf.types import Metadata


class MetadataBag(MutableMapping[str, Any]):
    """A mapping over one bucket of a stored envelope, written through on
    every change.

    `read` hands back the whole envelope (or `None` for one never written);
    `write` stores a whole envelope. `path` names the bucket this bag
    addresses inside it, so two bags over one envelope cannot tread on each
    other.

    Two things to know. Values must be JSON-safe, like everything else a
    run stores; and only *assignment* writes through — a read hands back a
    deep copy, so mutating a nested value in place (`bag["a"]["b"] = 1`)
    changes that copy and nothing else, on every backend. Assign the whole
    value back, and use `update()` when several keys change together so
    they cost one write rather than one each.
    """

    def __init__(
        self,
        read: Callable[[], Metadata | None],
        write: Callable[[Metadata], None],
        path: tuple[str, ...],
    ) -> None:
        self._read = read
        self._write_envelope = write
        self._path = path

    def _bucket(self) -> Metadata:
        bucket = self._read() or {}
        for key in self._path:
            bucket = bucket.get(key) or {}
        return bucket

    def _write(self, mutate: Any) -> None:
        """Apply `mutate` to this bag and store the whole envelope.

        Read-modify-write, and deliberately not memoised: two handles on one
        envelope are the normal case — a step view's and the viewset's — and
        a cache would let one of them go stale mid-request.
        """
        envelope = self._read() or {}
        node = envelope
        for key in self._path[:-1]:
            node = node.setdefault(key, {})
        bucket = node.setdefault(self._path[-1], {})
        # Mutating before the write means a `KeyError` from `__delitem__`
        # leaves storage untouched rather than half-written.
        mutate(bucket)
        self._write_envelope(envelope)

    def __getitem__(self, key: str) -> Any:
        # Deep copied on the way out, so a caller that mutates what it reads
        # cannot reach through into storage. Without this the behaviour
        # depends on the backend: a session hands back the live dict (the
        # mutation lands, but nothing marks the session, so the middleware
        # never saves it), while a durable store re-reads the row and the
        # mutation is gone at once. Refusing it everywhere beats working in
        # development and losing data in production.
        return deepcopy(self._bucket()[key])

    def __setitem__(self, key: str, value: Any) -> None:
        self._write(lambda bucket: bucket.__setitem__(key, value))

    def update(self, other: Any = (), /, **kwargs: Any) -> None:
        """Set several keys in one write.

        `MutableMapping` would do this by looping over `__setitem__`, which
        is a full read-modify-write of the envelope per key — three keys is
        three `SELECT`s and three `UPDATE`s on a durable backend. Related
        facts usually arrive together (`run_started()` recording what it
        opened and that it is pending), so they go in together.
        """
        changes = dict(other, **kwargs)
        self._write(lambda bucket: bucket.update(changes))

    def __delitem__(self, key: str) -> None:
        self._write(lambda bucket: bucket.__delitem__(key))

    def __iter__(self) -> Iterator[str]:
        return iter(self._bucket())

    def __len__(self) -> int:
        return len(self._bucket())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._bucket()!r})"
