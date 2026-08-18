"""What the demo site knows about itself.

`just serve` publishes every wizard in the test app. Flat and alphabetical
that is a wall of names, and the only way to learn what one of them does is
to go and read its viewset — which is a poor deal for someone who opened the
site to *look* at a behaviour rather than read about it.

This module is the missing key. It puts every published wizard in a group,
says what that group demonstrates, and adds the ordering notes a description
of the code cannot give you ("run the wizard first, then follow this link").
Two readers share it: the index page renders the groups, and the banner on
every wizard page looks the current request up by URL name, so a page you
landed on mid-flow still tells you which example you are inside.

Adding a wizard to `urls.py` and not to a group here fails
`tests/functional/test_examples_index.py` — an ungrouped wizard is one
nobody can find.
"""

from dataclasses import dataclass, replace
from functools import lru_cache

from django.urls import NoReverseMatch, get_resolver, reverse

from gandalf.collections import CollectionView
from gandalf.sections import HubView
from gandalf.viewsets import WizardViewSet


# URL kwargs the wizard's own patterns own. Anything else a pattern captures
# is mount-prefix context that only the catalogue can supply.
RUN_URL_KWARGS = frozenset({"run_id", "gandalf_step", "section", "item"})


@dataclass(frozen=True)
class Example:
    """One entry on the index, and one lookup key for the banner.

    `url_name` is the wizard's start URL. `url_kwargs` fills in a mount
    prefix (a tenant slug, a plan) for the wizards that cannot reverse
    without one. `title` overrides the viewset's class name, which is only
    needed where one viewset is listed twice under different kwargs.
    `note` is what to *do* with the example, as opposed to what it is.
    """

    url_name: str
    url_kwargs: dict = None
    title: str = None
    note: str = ""
    # Filled in by resolve(); read off the URLconf rather than declared.
    url: str = ""
    description: str = ""

    @property
    def label(self):
        return self.title or self.url_name


@dataclass(frozen=True)
class Group:
    title: str
    blurb: str
    examples: tuple


GROUPS = (
    Group(
        "Start here — the README examples",
        "The worked examples from README.md, running for real. Every one of "
        "these is also driven by tests/functional/test_readme_examples.py, so "
        "what you click through here is what the documentation promises.",
        (
            Example("readme-signup"),
            Example("readme-branching"),
            Example(
                "readme-onboarding",
                url_kwargs={"plan": "solo"},
                title="OnboardingWizardViewSet (solo plan)",
                note="Two steps: the plan in the URL decides the shape.",
            ),
            Example(
                "readme-onboarding",
                url_kwargs={"plan": "team"},
                title="OnboardingWizardViewSet (team plan)",
                note="The same viewset, three steps — compare with the solo "
                "plan above.",
            ),
            Example("readme-expand"),
            Example("readme-file-upload"),
            Example("readme-form-view"),
            Example(
                "readme-escape",
                note="Answer existing@example.com to trigger the escape.",
            ),
            Example("readme-editing"),
            Example(
                "readme-flip-flop",
                note="Pick business, fill the name in, then go back and switch "
                "to personal and back again — the business name is still there.",
            ),
            Example("readme-summary"),
            Example("readme-stash", note="Finish this first; it fills the stash."),
            Example(
                "readme-stash-reopen",
                title="reopen_contact",
                description="Re-opens the stashed contact answers in a fresh run.",
                note="Only works once the stashing wizard above has completed.",
            ),
            Example("readme-hub", note="The task list. Enter the sections from here."),
            Example("readme-hub-contact", note="A hub section, reached from the hub."),
            Example("readme-hub-address", note="A hub section, reached from the hub."),
            Example(
                "readme-party-hub",
                note="A task list whose second row is a collection.",
            ),
            Example("readme-party-venue", note="A plain section beside it."),
            Example(
                "readme-guests",
                note="Add another: add a few guests, then change and remove them.",
            ),
        ),
    ),
    Group(
        "The basics",
        "One step, then several in a row. These are the shapes every other "
        "group builds on, and most of them differ only in what done() does "
        "with the answers once they are all in.",
        (
            Example("single-step-wizard"),
            Example("single-step-wizard-without-done"),
            Example("single-step-wizard-done-data"),
            Example("single-step-wizard-done-run-data"),
            Example("linear-wizard"),
            Example("done-linear-wizard"),
            Example("merged-payload-wizard"),
            Example("multi-value-wizard"),
            Example(
                "empty-wizard", note="No steps at all, so it completes on arrival."
            ),
        ),
    ),
    Group(
        "Templates and configuration",
        "Where a step's template and the wizard's configuration come from. "
        "Several of these exist only to prove which template got picked, so "
        'the banner\'s "rendered by" line is the thing to watch.',
        (
            Example("other-linear-wizard"),
            Example("recreated-linear-wizard"),
            Example("pre-configured-wizard"),
            Example("double-configured-wizard"),
            Example("form-view-step-wizard"),
        ),
    ),
    Group(
        "Branching",
        "A branch picks its arm from the answers before it, and it is never "
        'stored — the arm is recomputed on every request. Answer "business" '
        "on the first step of most of these to take the non-default arm.",
        (
            Example("branching-wizard"),
            Example("done-branching-wizard"),
            Example("editing-branching-wizard"),
            Example("branch-entry-wizard", note="The branch is the very first node."),
            Example(
                "switch-wizard",
                note="A switch: one case per outcome, named rather than numbered.",
            ),
            Example(
                "switch-entry-wizard",
                note="The switch is the very first node.",
            ),
            Example("branching-merged-payload-wizard"),
            Example("runtime-tree-branching-merge-wizard"),
            Example("empty-branch-arm-merged-payload-wizard"),
            Example("empty-branch-arm-context-finder-wizard"),
            Example("cross-branch-wizard"),
            Example("branch-edit-rejection-wizard"),
            Example("empty-path-branch-wizard"),
        ),
    ),
    Group(
        "Wizards that build themselves",
        "Trees decided per request. get_wizard() rebuilds the whole "
        "declaration from stored state; .expand() grows a subtree mid-walk, "
        "behind an answer that has already validated. Answer the count step "
        "with 2 or 3 to see the steps appear.",
        (
            Example("dynamic-wizard"),
            Example("dynamic-list-payload-wizard"),
            Example("expand-wizard"),
            Example("empty-expand-wizard"),
            Example("sealable-expand-wizard"),
            Example("branching-expand-wizard"),
        ),
    ),
    Group(
        "Reading the run from inside it",
        "Steps that look at context.run while they render — to pre-fill a "
        "field from an earlier answer, or to ask where in the flow they are. "
        "The interesting cases are the awkward positions: the first step, "
        "where the path is empty, and a step the walk replays on every later "
        "request.",
        (
            Example("path-aware-linear-wizard"),
            Example("path-aware-form-view-first-step-wizard"),
            Example("path-aware-walked-past-wizard"),
            Example("empty-path-first-step-wizard"),
            Example("programmatic-lookup-wizard"),
        ),
    ),
    Group(
        "URLs, routing and editing",
        "Every step is addressable, so going back is just visiting its URL. "
        "A step URL is a claim the wizard checks by walking to it: ask for "
        "one you have not reached and you get redirected to where you "
        "actually are.",
        (
            Example("routed-wizard"),
            Example("section-editing-wizard"),
            Example(
                "org-scoped-wizard",
                url_kwargs={"org": "acme"},
                note="Mounted under a tenant slug; the slug rides along "
                "through every step URL and edit.",
            ),
        ),
    ),
    Group(
        "File uploads",
        "Uploads are stored per run and cleaned up when it finishes. Editing "
        "a step that carries a file is the awkward case: replacing, adding, "
        "and leaving it alone all have to work.",
        (
            Example("file-uploading-wizard"),
            Example("file-editing-wizard"),
            Example("file-done-wizard"),
            Example("sniffed-file-wizard"),
        ),
    ),
    Group(
        "Escaping a run",
        "A step can bail out mid-flow by raising. Park leaves the answer "
        "unstored and the run where it was, Advance stores it and carries "
        "on, Obliterate destroys the run and its files. All of these "
        "redirect to the same landing page.",
        (
            Example(
                "escape-park-wizard",
                note="Answer existing@example.com — a known address parks the run.",
            ),
            Example("mid-flow-escape-park-wizard", note="Parks from the second step."),
            Example("escape-park-file-wizard", note="Parks after an upload."),
            Example("escape-advance-wizard"),
            Example("escape-advance-final-step-wizard"),
            Example("escape-obliterate-wizard", note="Tick cancel to destroy the run."),
            Example("escape-editing-wizard"),
            Example(
                "escape-landing",
                title="EscapeLandingView",
                description="Where every escaping wizard sends the user.",
            ),
        ),
    ),
    Group(
        "Check your answers",
        "A summary step lists every answer given so far, formatted for "
        "display, with a change link each. It has to leave itself out of its "
        "own list once the run has been round the houses.",
        (
            Example("summary-wizard"),
            Example("custom-summary-wizard"),
            Example("summary-display-wizard"),
        ),
    ),
    Group(
        "Stashing and re-opening",
        "done() can keep a finished run's answers, so the same wizard can be "
        "re-opened later and edited. The stash drops uploads, which is why "
        "the required-photo variant parks on its photo step when it comes "
        "back. Run the wizard to completion first — the resurrect links need "
        "something to resurrect.",
        (
            Example("stashing-wizard", note="Run this first."),
            Example(
                "stashing-wizard-resurrect",
                title="resurrect_contact_stash",
                description="Re-opens the stashed answers in a fresh run.",
                note="Then this.",
            ),
            Example("required-photo-stashing-wizard", note="Run this first."),
            Example(
                "required-photo-stashing-wizard-resurrect",
                title="resurrect_required_photo_stash",
                description="Re-opens the stash; parks on the photo step, "
                "because the stash dropped the upload.",
                note="Then this.",
            ),
            Example("branching-stashing-wizard", note="Run this first."),
            Example(
                "branching-stashing-wizard-resurrect",
                title="resurrect_sections_stash",
                description="Consumes the sections stash and re-opens it at "
                "the count step.",
                note="Then this — it pops the stash, so it only works once.",
            ),
            Example(
                "stashed-section-keys",
                title="stashed_section_keys",
                description="Plain text: which stashes this session holds.",
            ),
            Example(
                "discard-sections-stash",
                title="discard_sections_stash",
                description="Throws the sections stash away.",
            ),
            Example(
                "resurrect-empty-stash",
                title="resurrect_empty_stash",
                description="Resurrects an empty payload into the stepless "
                "wizard, which completes on arrival.",
            ),
        ),
    ),
    Group(
        "Hub and spoke",
        "Parallel sections instead of one line: a task list where each row is "
        "an independent run with its own status. Enter the sections from "
        "their hub — a section's own URL starts a run the hub is not tracking.",
        (
            Example("scenario-hub", note="Start here."),
            Example("hub-plain-section"),
            Example("hub-advancing-section"),
            Example(
                "org-hub",
                url_kwargs={"org": "acme"},
                note="A hub whose sections carry the tenant slug.",
            ),
            Example("org-hub-section-wizard", url_kwargs={"org": "acme"}),
            Example("counting-hub", note="Start here."),
            Example("counting-hub-section-wizard"),
            Example("other-counting-hub-section-wizard"),
        ),
    ),
    Group(
        "Add another — collections of items",
        "A list the user grows: each item is its own run, separately "
        "resumable, changeable and removable. The page asks whether there is "
        "another to add, because nothing in storage can answer that. Reach an "
        "item from its collection page — the item wizard's own URL needs an "
        "item id, and the collection is what mints them.",
        (
            Example("party-hub", note="Start here — a task list with a collection."),
            Example("party-venue", note="A plain section beside the collection."),
            Example(
                "party-guests",
                note="The collection page. Add a few, then change and remove them.",
            ),
            Example(
                "minimum-guests",
                note='Needs at least one item, so answering "no" while empty '
                "still reads as Incomplete.",
            ),
            Example(
                "advancing-guests",
                note="Items that park with every answer valid — the state a "
                "bare run URL would complete on a GET.",
            ),
            Example(
                "org-guests",
                url_kwargs={"org": "acme"},
                note="A collection whose items carry the tenant slug.",
            ),
            Example(
                "off-route-guests",
                note="Items named by a step that is not on their route, so "
                "every row falls back to a number.",
            ),
            Example(
                "reshaped-guests",
                note="A reshaped item shape: both halves of the label moved, "
                "so a finished item can still be re-opened.",
            ),
        ),
    ),
    Group(
        "Storage and the life of a run",
        "Where a run lives and how it ends. The durable pair swaps session "
        "storage for the database, so its runs outlive the session; the rest "
        "are about completion — a finished run is tombstoned so done() "
        "cannot fire twice, and the tombstones are eventually pruned.",
        (
            Example("durable-hub", note="Start here; its runs survive a restart."),
            Example("durable-section"),
            Example(
                "durable-guests",
                note="A collection whose registry is a table, so two tabs "
                "adding at once cannot lose an item.",
            ),
            Example(
                "pruned-completion-wizard",
                note="Keeps two tombstones, so complete it three times to "
                "watch the oldest go.",
            ),
            Example(
                "run-unavailable-wizard",
                note="Complete it, then revisit the run URL — 410 instead of "
                "a redirect to the start.",
            ),
            Example("walk-counting-wizard"),
        ),
    ),
    Group(
        "Misconfigured on purpose",
        "These are meant to fail, and they fail on the first request. Each "
        "one pins the error message a mistake earns; with DEBUG on you get "
        "Django's yellow page and the exception is the point. Nothing here "
        "is broken.",
        (
            Example("invalid-wizard", note="TypeError: wizard is not a Wizard."),
            Example(
                "wizardless-wizard", note="ImproperlyConfigured: no wizard at all."
            ),
            Example(
                "missing-template-wizard",
                note="ImproperlyConfigured: nothing supplied a template_name.",
            ),
            Example(
                "unroutable-wizard",
                note="ImproperlyConfigured: a step with no routable name.",
            ),
            Example(
                "misdeclared-switch-wizard",
                note="ImproperlyConfigured: a switch reading a step that is "
                "not on its route.",
            ),
            Example(
                "duplicate-context-wizard",
                note="ImproperlyConfigured: two steps claim one URL segment.",
            ),
            Example(
                "drifted-guests",
                note="ImproperlyConfigured: a collection's item label drifts "
                "from its own, so a finished item could never be re-opened.",
            ),
            Example(
                "anonymous-guests",
                note="ImproperlyConfigured at completion: an item wizard with "
                "no answer named as the one that titles its rows.",
            ),
            Example(
                "misconfigured-wizard",
                note="ImproperlyConfigured: hand-written URLs with no url_name "
                "to reverse.",
            ),
            Example(
                "wizard-configured-storage",
                note="ImproperlyConfigured: storage_class belongs on the "
                "viewset, not the wizard.",
            ),
            Example(
                "bare-escape-wizard",
                note="This one renders. Submit the step: raising the base "
                "Escape names no disposition for the run, and the viewset "
                "rejects it.",
            ),
        ),
    ),
)


def groups():
    """The catalogue as declared, without touching the URLconf."""
    return GROUPS


def _iter_leaf_patterns(patterns, prefix_converters=frozenset()):
    """Yield every leaf URLPattern with the converters it inherits.

    A converter can sit on the mount prefix rather than the leaf — an item
    wizard mounted at `path("guest/<uuid:item>/", include(...))` publishes a
    leaf of `""`, and the `item` it cannot begin without is the prefix's. So
    the converters are accumulated on the way down and yielded alongside.
    """
    for pattern in patterns:
        converters = prefix_converters | set(pattern.pattern.converters)
        if hasattr(pattern, "url_patterns"):
            yield from _iter_leaf_patterns(pattern.url_patterns, converters)
        elif hasattr(pattern, "callback"):
            yield pattern, converters


def published_url_names():
    """Every wizard and hub *start* URL the test app mounts.

    Derived from the URLconf rather than declared, so a wizard added to
    `urls.py` and forgotten here shows up as a test failure. The per-run,
    per-step, per-section and per-item patterns are skipped: they are ways
    back into something that already exists, not places to begin. A
    collection's items are per-item wherever the segment sits, so the whole
    item wizard is reached from its collection page rather than the index.
    """
    names = set()
    for pattern, converters in _iter_leaf_patterns(get_resolver(None).url_patterns):
        if pattern.name is None:
            continue
        if RUN_URL_KWARGS & converters:
            continue
        view_class = getattr(pattern.callback, "view_class", None)
        if view_class is None:
            continue
        if not issubclass(view_class, (WizardViewSet, HubView, CollectionView)):
            continue
        names.add(pattern.name)
    return names


def _view_class_for(url_name, url_kwargs):
    """The view class behind `url_name`, or None for a function view."""
    match = get_resolver(None).resolve(reverse(url_name, kwargs=url_kwargs))
    return getattr(match.func, "view_class", None)


def resolve():
    """The catalogue with every example's URL and description filled in.

    Descriptions live on the viewsets, next to the code they describe, so
    this reads them back off the URLconf rather than repeating them here.
    Function views have no class to carry one, so those declare a
    description inline.
    """
    resolved = []
    for group in GROUPS:
        examples = tuple(_resolve_example(example) for example in group.examples)
        resolved.append(replace(group, examples=examples))
    return tuple(resolved)


def _resolve_example(example):
    try:
        url = reverse(example.url_name, kwargs=example.url_kwargs)
    except NoReverseMatch as error:
        raise NoReverseMatch(
            f"The example catalogue lists {example.url_name!r}, which does not "
            "reverse. Give it url_kwargs, or drop it from tests/testapp/"
            f"catalogue.py. ({error})"
        ) from error
    view_class = _view_class_for(example.url_name, example.url_kwargs)
    description = example.description
    if view_class is not None:
        description = getattr(view_class, "description", "") or description
    return replace(
        example,
        url=url,
        title=example.title or (view_class.__name__ if view_class else example.title),
        description=description,
    )


def entry_for(url_name):
    """The catalogue entry a request is inside, by URL name.

    The banner calls this with `request.resolver_match.url_name`, which for
    a run in progress is the `-run` or `-step` pattern published alongside
    the start URL the catalogue lists — so both are tried.
    """
    entry, _ = _lookup(url_name)
    return entry


def group_for(url_name):
    """The group an example sits under, for the banner's eyebrow."""
    _, group = _lookup(url_name)
    return group


def _lookup(url_name):
    index = _by_url_name()
    for candidate in _candidate_url_names(url_name):
        if candidate in index:
            return index[candidate]
    return None, None


def _candidate_url_names(url_name):
    yield url_name
    for suffix in ("-step", "-run"):
        if url_name.endswith(suffix):
            yield url_name[: -len(suffix)]


@lru_cache(maxsize=None)
def _by_url_name():
    """Every resolved example keyed by start URL name, first listing wins.

    Built once: the URLconf does not change between requests, and the banner
    would otherwise re-reverse the whole catalogue on every page.
    """
    index = {}
    for group in resolve():
        for example in group.examples:
            index.setdefault(example.url_name, (example, group))
    return index
