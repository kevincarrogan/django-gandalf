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

from gandalf.tasklists import TaskListViewSet
from gandalf.viewsets import WizardViewSet


# URL kwargs the wizard's own patterns own. Anything else a pattern captures
# is mount-prefix context that only the catalogue can supply.
RUN_URL_KWARGS = frozenset({"run_id", "gandalf_step", "entry", "item"})

#: The journey the walkthrough's chapter 15 examples are listed under. Any slug
#: works — a journey is minted by the setup wizard, and the index only needs
#: the URLs to reverse.
JOURNEY = {"journey": "example"}


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
        "Start here — the Learn walkthrough, chapter by chapter",
        "One grant application, built up a chapter at a time. Each entry is "
        "the code its docs/learn chapter shows, running for real, and every one "
        "is driven by tests/functional/test_readme_examples.py — so what you "
        "click through here is what the documentation promises.",
        (
            Example("readme-first", note="Chapter 1. Two steps, then done()."),
            Example(
                "readme-branching",
                note="Chapter 2. Answer 'organisation' to take the other arm.",
            ),
            Example(
                "readme-switch", note="Chapter 3. A case per kind of organisation."
            ),
            Example("readme-expand", note="Chapter 4. One trustee step per trustee."),
            Example(
                "readme-paper",
                note="Chapter 5. Sign in at /readme/staff/sign-in/ and a staff "
                "member is asked the date the paper application was received; "
                "/readme/staff/sign-out/ takes the step away again.",
            ),
            Example(
                "readme-fund",
                url_kwargs={"fund": "sport"},
                title="FundApplicationViewSet (sport fund)",
                note="Chapter 5. The fund in the URL decides the shape.",
            ),
            Example(
                "readme-fund",
                url_kwargs={"fund": "arts"},
                title="FundApplicationViewSet (arts fund)",
                note="Chapter 5. The same viewset asks for a portfolio too.",
            ),
            Example(
                "readme-step-view",
                note="Chapter 6. The website step is pre-filled from the email's domain.",
            ),
            Example(
                "readme-review",
                note="Chapter 7. Change an answer from the summary; flip the arm and back.",
            ),
            Example(
                "readme-escape",
                note="Chapter 8. Answer existing@example.com to be parked at the login page.",
            ),
            Example(
                "readme-upload",
                note="Chapter 9. An organisation uploads its governing document.",
            ),
            Example(
                "readme-record",
                note="Chapter 10. A draft record opened at the start, submitted at the end.",
            ),
            Example(
                "readme-stash",
                note="Chapter 11. Finish this first; it fills the stash.",
            ),
            Example(
                "readme-stash-reopen",
                title="reopen_contact_details",
                description="Re-opens the stashed contact details in a fresh run.",
                note="Chapter 11. Only works once the wizard above has completed.",
            ),
            Example(
                "readme-task-list",
                note="Chapter 12. The task list; enter the sections from here.",
            ),
            Example(
                "readme-task-list-contact",
                note="Chapter 12. A section, reached from the task list.",
            ),
            Example(
                "readme-task-list-address",
                note="Chapter 12. A section, reached from the task list.",
            ),
            Example(
                "readme-project",
                note="Chapter 13. A task list whose second row is an add-another list.",
            ),
            Example(
                "readme-project-project",
                note="Chapter 13. The project section beside the budget.",
            ),
            Example(
                "readme-project-budget",
                note="Chapter 13. Add a few budget lines, then change and remove them.",
            ),
            Example(
                "readme-gated",
                note="Chapter 14. Ask for over 10,000 and a section appears.",
            ),
            Example("readme-gated-project"),
            Example("readme-gated-referees"),
            Example("readme-gated-match-funding"),
            Example(
                "readme-apply-start",
                note="Chapter 15. Start here — it mints an application and lands on its page.",
            ),
            Example(
                "readme-apply",
                url_kwargs=JOURNEY,
                note="Chapter 15. The task list of one application. Reach it from the setup wizard.",
            ),
            Example("readme-apply-setup", url_kwargs=JOURNEY),
            Example("readme-apply-contact", url_kwargs=JOURNEY),
            Example("readme-apply-project", url_kwargs=JOURNEY),
            Example("readme-apply-budget", url_kwargs=JOURNEY),
            Example("readme-apply-match-funding", url_kwargs=JOURNEY),
            Example("readme-apply-supporting-referees", url_kwargs=JOURNEY),
            Example("readme-apply-supporting-documents", url_kwargs=JOURNEY),
            Example("readme-apply-supporting", url_kwargs=JOURNEY),
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
            Example(
                "opening-hours-wizard",
                note="A formset step: seven compact rows on one page rather "
                "than seven pages. Its bounds are enforced, so its schema "
                "states them. Compare AddAnother, where an item earns a page.",
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
            Example(
                "off-route-switch-wizard",
                note="A switch reading a declared step this run did not "
                "walk: the declaration is sound, the walk is not.",
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
            Example(
                "run-metadata-wizard",
                note="run_started() opens a record and remembers it in the "
                "run's metadata; the second step reads it back on every "
                "request, and done() names it.",
            ),
            Example(
                "one-time-token-wizard",
                note="the token step consumes what it checks, so it holds "
                "the result in run.proof() and re-checks that instead. Go "
                "back and change the first answer to watch the proof fall "
                "away and the check be performed again.",
            ),
            Example(
                "one-time-token-done-wizard",
                note="the same check, finishing on a page that reads the "
                "run back — which validates the token step again after the "
                "run has been tombstoned.",
            ),
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
            Example("member-editing-wizard"),
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
            Example("grouped-summary-wizard"),
            Example(
                "templated-summary-wizard",
                note="A group naming its own template: the review page "
                "includes it, so the markup for an address lives with the "
                "address rather than as an if in the summary template.",
            ),
            Example(
                "dynamic-summary-wizard",
                note="A group naming more than a per-request form asks: the "
                "declaration cannot check it, so it survives asking for less.",
            ),
            Example("expanded-summary-wizard"),
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
                title="resurrect_members_stash",
                description="Consumes the members stash and re-opens it at "
                "the count step.",
                note="Then this — it pops the stash, so it only works once.",
            ),
            Example(
                "stashed-member-keys",
                title="stashed_member_keys",
                description="Plain text: which stashes this session holds.",
            ),
            Example(
                "discard-members-stash",
                title="discard_members_stash",
                description="Throws the members stash away.",
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
        "Task lists",
        "Parallel sections instead of one line: a task list where each row is "
        "an independent run with its own status. Enter the sections from "
        "the page — a section's own URL starts a run the page is not tracking.",
        (
            Example("scenario-task-list", note="Start here."),
            Example("scenario-task-list-plain"),
            Example("scenario-task-list-advancing"),
            Example(
                "org-task-list",
                url_kwargs={"org": "acme"},
                note="A task list whose sections carry the tenant slug.",
            ),
            Example("org-task-list-details", url_kwargs={"org": "acme"}),
            Example("counting-task-list", note="Start here."),
            Example("counting-task-list-counting"),
            Example("counting-task-list-other"),
            Example(
                "gated-task-list",
                note="The second row waits on the first: Cannot start yet, "
                "and the door turns you away until it unlocks.",
            ),
            Example("gated-task-list-first"),
            Example("gated-task-list-second"),
        ),
    ),
    Group(
        "Add another — lists the user grows",
        "A list the user grows: each item is its own run, separately "
        "resumable, changeable and removable. The page asks whether there is "
        "another to add, because nothing in storage can answer that. Reach an "
        "item from its list page — the item wizard's own URL needs an "
        "item id, and the list is what mints them.",
        (
            Example(
                "submit-task-list",
                url_kwargs={"journey": "example"},
                note="A task list under a journey segment; finish both rows, then submit.",
            ),
            Example("submit-task-list-first", url_kwargs={"journey": "example"}),
            Example("submit-task-list-second", url_kwargs={"journey": "example"}),
            Example(
                "party-task-list",
                note="Start here — a task list with an add-another list.",
            ),
            Example(
                "standalone-guests",
                note="The same list mounted on its own, returning to the party task list.",
            ),
            Example(
                "party-task-list-venue",
                note="A plain section beside the add-another list.",
            ),
            Example(
                "party-task-list-guests",
                note="The list page. Add a few, then change and remove them.",
            ),
            Example(
                "minimum-guests",
                note='Needs at least one item, so answering "no" while empty '
                "still reads as Incomplete.",
            ),
            Example(
                "locked-guests",
                note="Every item locked, so the item door declines rather "
                "than handing back a URL it never built.",
            ),
            Example(
                "advancing-guests",
                note="Items that park with every answer valid — the state a "
                "bare run URL would complete on a GET.",
            ),
            Example(
                "org-task-list-org_guests",
                url_kwargs={"org": "acme"},
                note="An add-another list whose items carry the tenant slug.",
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
            Example(
                "durable-task-list", note="Start here; its runs survive a restart."
            ),
            Example("durable-task-list-durable"),
            Example("titled-guests"),
            Example(
                "durable-guests",
                note="An add-another list whose registry is a table, so two tabs "
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
                note="ImproperlyConfigured: a switch reading a step the "
                "wizard does not declare, refused before any walk.",
            ),
            Example(
                "duplicate-context-wizard",
                note="ImproperlyConfigured: two steps claim one URL segment.",
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
    Group(
        "Ported from django-formtools",
        "Three wizards taken from projects that ship, translated whole from "
        "django-formtools and driven by tests/functional/test_from_formtools.py. "
        "Each one lands in a different half of the library, and each module's "
        "docstring says what stops being the application's problem once the "
        "port is done.",
        (
            Example(
                "formtools-djangogirls",
                note="Django Girls' organise-an-event application. Upstream "
                "needs two opposite predicates for the workshop question; "
                "here it is one branch with two arms. The organisers step is "
                "a formset.",
            ),
            Example(
                "formtools-squest",
                note="Squest's request-a-service wizard. The survey form is "
                "built from the first step's answer — read by name, where "
                "upstream indexes into raw session storage by position.",
            ),
            Example(
                "formtools-two-factor",
                note="django-two-factor-auth's setup wizard. The shape comes "
                "from a method registry, and the code verifies once: enter it, "
                "then go back and change an answer to watch the proof void.",
            ),
            Example(
                "formtools-two-factor-single",
                note="The same wizard with one method registered. Upstream "
                "deletes the step and forges its answer into storage; here "
                "the step is simply never declared.",
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
    """Every wizard and task list *start* URL the test app mounts.

    Derived from the URLconf rather than declared, so a wizard added to
    `urls.py` and forgotten here shows up as a test failure. The per-run,
    per-step, per-section and per-item patterns are skipped: they are ways
    back into something that already exists, not places to begin. A
    list's items are per-item wherever the segment sits, so the whole
    item wizard is reached from its list page rather than the index.
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
        if not issubclass(view_class, (WizardViewSet, TaskListViewSet)):
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
