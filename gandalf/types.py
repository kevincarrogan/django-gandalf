"""Type aliases for the shapes that cross module boundaries.

Wizard state is JSON — it has to survive a session round-trip — so these
are aliases over plain containers rather than classes. They exist to name
the shapes the docstrings already describe: what a stored submission is,
what one positional slot in the state list holds, what a stash is.

The authoritative description of the state shape lives on `CursorWalker`
and `StateSerializer` in `gandalf.runtime`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias

from django.http import HttpRequest

from gandalf.file_storage import FileRef


if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

    from gandalf.context import WizardContext
    from gandalf.runtime import BoundWizard

    #: Display text that may still be a lazy translation — what Django hands
    #: back for a field label or a `gettext_lazy()` string, and what a
    #: template renders either way.
    StrOrPromise: TypeAlias = "str | _StrPromise"
else:
    StrOrPromise = str


#: One step's stored answer: the POST keys it was submitted with, each
#: holding the single value sent or the list of values for a key the
#: browser sent more than once.
Submission: TypeAlias = dict[str, Any]

#: The uploads stored against one step, keyed by form field name.
FileRefs: TypeAlias = dict[str, FileRef]

#: What a placement recorded about itself: who made it and how, parked
#: beside the answer rather than inside it. A step's `context` is the
#: declaration and is the same for every run; this belongs to one answer in
#: one run. JSON-safe values only — it is stored with the state.
#:
#: Also the shape of a run's own metadata — the bag `BoundWizard.metadata`
#: reads and writes, which is stored *beside* the state rather than in it.
#: See `RunMetadata` in `gandalf.runtime` for why those are different homes.
Metadata: TypeAlias = dict[str, Any]

#: One positional slot in a state list: `{"step": <submission or None>}`,
#: `{"branch": {<arm id>: [<entries>]}}`, or `{"expand": [<entries>]}`.
StateEntry: TypeAlias = dict[str, Any]

#: A wizard's stored state: a full-tree positional mirror, with holes.
State: TypeAlias = list[StateEntry]

#: Everything storage keeps about one run — its state, or the tombstone a
#: completed run leaves behind.
RunData: TypeAlias = dict[str, Any]

#: A caller-owned, JSON-safe payload of a run's answers, from
#: `BoundWizard.stash()` and accepted back by `resurrect()`.
Stash: TypeAlias = dict[str, Any]

#: A step lookup: context keys matched against a step's declared context.
Context: TypeAlias = dict[str, Any]

#: One item of a collection: its opaque id, and the title its own section
#: cached the last time it finished (`None` until it has).
CollectionItem: TypeAlias = dict[str, Any]

#: Everything a store keeps about one collection — its items in the order the
#: user added them, and whether the user has said there are no more to add.
CollectionData: TypeAlias = dict[str, Any]


class WizardRequest(HttpRequest):
    """An `HttpRequest` inside a wizard dispatch.

    Never instantiated — it names the one thing a dispatch adds to the
    request, so a step's own view can say what it is handed:

        class BillingStepView(StepFormView):
            def get_initial(self):
                self.request.wizard.path.find_step(name="account")

    Step views get this narrowing from `StepFormView` already.

    Not what a branch predicate, expansion builder or switch selector
    receives — those are walk-time code and are handed a `WizardContext`,
    which is true of a run whether or not a browser is driving it.
    """

    wizard: BoundWizard


class WizardStorage(Protocol):
    """What `WizardViewSet.storage_class` has to provide.

    Structural, not a base class: `SessionStorage` satisfies it without
    inheriting anything, and so does a storage of your own that keeps runs
    somewhere longer-lived. A run id is minted by the storage and opaque to
    everything else, so it need not be a UUID.

    Constructed from the run's `WizardContext` rather than from a request,
    which is what lets a durable backend scope runs by `context.actor`
    whether the person is browsing or an agent is filling it in for them.
    """

    def __init__(self, context: WizardContext) -> None: ...

    def initialise_run(self) -> str: ...

    def retrieve_run(self, run_id: str) -> str: ...

    def get_run_data(self, run_id: str) -> RunData: ...

    def get_state(self, run_id: str) -> State: ...

    def set_state(self, run_id: str, state: State) -> None: ...

    def get_run_metadata(self, run_id: str) -> Metadata: ...

    def set_run_metadata(self, run_id: str, metadata: Metadata) -> None: ...

    def delete_run(self, run_id: str) -> None: ...

    def complete_run(self, run_id: str) -> None: ...

    def is_run_complete(self, run_id: str) -> bool: ...


#: A storage class as it is configured — named on the viewset and called
#: with the request. Spelled as a callable rather than `type[WizardStorage]`
#: because a protocol type cannot be instantiated through the checker.
StorageClass: TypeAlias = (
    "type[WizardStorage] | Callable[[WizardContext], WizardStorage]"
)
