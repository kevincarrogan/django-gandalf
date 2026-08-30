"""The environment a walk runs in.

A wizard's own code — a branch predicate, an expansion builder, a switch
selector — needs to know things while the walk is happening: what has been
answered so far, who is answering, what the mount prefix was. None of that
is HTTP. It arrived as an `HttpRequest` only because a request was the
object that happened to be in scope, and everything downstream inherited the
assumption: storage was constructed from a request, `Run` held one,
and `gandalf.driver` — which has no browser anywhere near it — had to
manufacture one before it could ask a wizard anything at all.

`WizardContext` is that environment, named. It carries the four things the
walk actually needs (`run`, `actor`, `session`, `url_kwargs`) and keeps the
request itself as one optional field among them, present when a browser is
genuinely involved and `None` when one is not.

The asymmetry is deliberate. A predicate that reads `context.request` is
saying it needs a browser, and under the driver it will fail saying so. That
is the honest answer: previously it was handed a fabricated request and got
a plausible wrong one — `/agent/` for a path, whoever the driver was told to
pretend to be for a user.

One thing here *is* HTTP, and only one: `http_request()`. Dispatching a
step's `FormView` means calling a Django view, and a Django view takes a
request. That is the single seam where one is built, and the single reason
this module knows what a request is.
"""

from __future__ import annotations

from copy import copy
from io import BytesIO
from typing import TYPE_CHECKING, Any, Protocol, cast

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest


if TYPE_CHECKING:
    from gandalf.runtime import Run


class WizardSession(Protocol):
    """The three things a session-backed storage asks of a session.

    Structural, like `WizardStorage`: Django's `SessionBase` satisfies it
    without being told, and so does the plain `Session` below. Narrow on
    purpose — a wizard reads a key, writes a key, and says it changed.
    """

    modified: bool

    def get(self, key: str, default: Any = None) -> Any: ...

    def setdefault(self, key: str, default: Any) -> Any: ...


#: The path a fabricated request reports. A step view's success URL is its
#: own path and the response is discarded unread, so nothing routes on this
#: — it exists because `HttpRequest` insists on having one.
DRIVEN_PATH = "/"


class Session(dict):  # type: ignore[type-arg]
    """A session for a run nobody is browsing.

    `SessionStorage` writes answers and then sets `modified` so Django's
    middleware saves them; with no middleware there is nothing to save, but
    the attribute still has to be there to be set. A dict with a flag is the
    whole of what a session is to a wizard.
    """

    modified = False


def _fabricate(path: str) -> HttpRequest:
    """A request for a run that no browser is driving.

    A `WSGIRequest` specifically, and not the `HttpRequest` its name
    suggests: on the base class `POST` and `FILES` are plain instance
    attributes, so `StepDispatcher`'s `request._files = ...` would be
    written and never read, and every replayed upload would silently
    vanish. `WSGIRequest` reads both through properties, which is what the
    dispatcher — and the browser path it has to behave identically to —
    expects.

    Built here rather than with `django.test.RequestFactory`, which is the
    same construction with a test dependency attached. A shipped module
    should not import from `django.test` to do its ordinary work.
    """
    return WSGIRequest(
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "SCRIPT_NAME": "",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": BytesIO(b""),
            "wsgi.errors": BytesIO(),
            "wsgi.url_scheme": "http",
            "wsgi.version": (1, 0),
            "wsgi.multiprocess": False,
            "wsgi.multithread": False,
            "wsgi.run_once": False,
        }
    )


class WizardContext:
    """What a walk runs against: a run, whoever is answering it, where its
    state is kept, and the mount kwargs it was reached through.

    Build one from a request on the HTTP path::

        context = WizardContext.from_request(request, tenant="acme")

    or directly when there is no request to build one from::

        context = WizardContext(actor=customer)

    `run` is filled in by `Run` as it is constructed, which is what
    lets a predicate reach the answers behind it. Before that moment it is
    `None`, exactly as `request.run` was absent before a dispatch set it.

    Not a dataclass, because `actor` and `session` are read *lazily* off the
    request when there is one. Eagerly touching `request.session` would
    demand session middleware from callers that only ever describe a
    wizard's shape, and eagerly touching `request.user` would resolve a lazy
    object nobody asked about.
    """

    def __init__(
        self,
        *,
        actor: Any = None,
        session: WizardSession | None = None,
        url_kwargs: dict[str, Any] | None = None,
        request: HttpRequest | None = None,
        path: str = DRIVEN_PATH,
    ) -> None:
        self.request = request
        self.url_kwargs = dict(url_kwargs or {})
        self.path = path
        #: The run this context is bound to — `Run` sets it on
        #: construction. What `request.run` used to be.
        self.run: Run | None = None
        self._actor = actor
        self._session: WizardSession | None = session
        self._fabricated: HttpRequest | None = None

    @classmethod
    def from_request(cls, request: HttpRequest, **url_kwargs: Any) -> WizardContext:
        """The context a browser request implies."""
        return cls(request=request, url_kwargs=url_kwargs)

    def addressing(self, **url_kwargs: Any) -> WizardContext:
        """This environment, pointed at a different URL.

        A context is held for as long as whoever it describes — a
        conversation, a management command — while the thing it addresses
        changes within that: one item of a collection, then the next. So
        the url kwargs are the part worth varying, and this varies only
        them. Names given here win over the ones already held, because a
        call is the more specific statement.

        `run` is deliberately not carried over. It belongs to a
        `Run` and the twin is about to be given its own.
        """
        session = self._session
        if session is None and self.request is None:
            # Resolved now rather than left lazy: with no request to read
            # one off, the twin would otherwise invent its own in-memory
            # session, and a run started through it would be one the
            # original context could not find.
            session = self.session
        return type(self)(
            actor=self._actor,
            session=session,
            url_kwargs={**self.url_kwargs, **url_kwargs},
            request=self.request,
            path=self.path,
        )

    @property
    def actor(self) -> Any:
        """Whoever is answering: `request.user` on the HTTP path, or whoever
        a programmatic caller named. `None` when nobody said.

        This is what a durable storage scopes runs by, which is how an agent
        creating a run on somebody's behalf creates it as *theirs* without a
        request to read it from.
        """
        if self._actor is None and self.request is not None:
            self._actor = getattr(self.request, "user", None)
        return self._actor

    @property
    def session(self) -> WizardSession:
        """Where a session-backed storage keeps its runs.

        The browser's session when there is one, an in-memory `Session`
        otherwise — and the *same object* throughout, because the walk reads
        back what it writes within a single dispatch.
        """
        session = self._session
        if session is None:
            session = (
                cast(WizardSession, self.request.session)
                if self.request is not None
                else Session()
            )
            self._session = session
        return session

    def session_changed(self) -> None:
        """Say the session changed — the one call a session-backed storage
        makes after a write.

        Marking it is what a browser request needs; `SessionMiddleware`
        saves the session on the way out. `persist()` is for the callers
        that have no way out, and is a no-op for the ones that do.
        """
        self.session.modified = True
        self.persist()

    def persist(self) -> None:
        """Write the session back now, because nothing later will.

        A session normally reaches its store through `SessionMiddleware`,
        which saves it as the response goes past. A context with no request
        behind it never reaches that moment, and there are two such
        callers. A driven run — a management command, a test, an agent
        tool — handed a real session by `session=` has no response at all
        for the middleware to save against. And the AG-UI
        endpoint's response is a *stream*: the middleware ran when the view
        returned the `StreamingHttpResponse`, before the first tool wrote
        anything, so every run an agent starts would be gone by the time
        the browser asked for it.

        Absence of a request is what says so, rather than a flag somebody
        has to remember: a request is the thing that implies a response
        coming back to carry the session home. On the HTTP path this
        returns immediately, which is the point — saving on every write
        would turn one save per form submission into three.

        A cookie-backed session cannot be written back this way at all: its
        store *is* a response header, and that header has gone. `save()` is
        still the backend's call to answer, and the run stays readable for
        the rest of this walk — it simply will not be there on the next
        request. Agent-written runs need a server-side session backend.
        """
        if self.request is not None:
            return
        # Duck-typed, like the protocol itself: Django's stores save, the
        # in-memory `Session` above has nowhere to save to.
        save = getattr(self.session, "save", None)
        if save is not None:
            save()

    def http_request(self) -> HttpRequest:
        """A request to dispatch a step's `FormView` with.

        A fresh shallow copy every call, so a caller may set `method`,
        `POST` and `_files` on it without disturbing anyone else's — while
        the session, and everything else a browser brought, stay shared by
        reference. That is the behaviour the HTTP path has always had; the
        driven path now gets the same one from a base request built once
        rather than a browser impersonated per run.
        """
        request = copy(self._base())
        # What `request.run` is for: the walk's own code reaches the run
        # through the request it is dispatched with.
        request.run = self.run  # type: ignore[attr-defined]
        return request

    def _base(self) -> HttpRequest:
        if self.request is not None:
            return self.request
        if self._fabricated is None:
            request = _fabricate(self.path)
            # Both are attributes middleware would have put there. Set
            # through `setattr` because the stubs describe the shapes a
            # browser request carries, and neither is one here.
            setattr(request, "session", self.session)
            if self.actor is not None:
                setattr(request, "user", self.actor)
            self._fabricated = request
        return self._fabricated
