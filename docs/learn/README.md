# Learn django-gandalf

This is a walkthrough, not a manual. It builds one thing — a community grant
fund's application form — a chapter at a time. Chapter 1 asks two questions
in a row. Each chapter after it adds one thing the application needs, says
why that thing exists, and leaves a runnable application behind. By chapter
14 the whole thing is there, and chapter 15 is about knowing what you built.

It deliberately does not list every hook, every attribute or every edge case.
Where a chapter touches something with more to it, it links to the
[Reference](../reference/README.md), which does.

Every chapter is real code. It lives in
[`tests/testapp/readme/`](../../tests/testapp/readme/), one module per chapter,
and each module imports the one before it and grows it — which is itself the
first lesson, since a `Wizard` is a value and the previous chapter's
declaration is still intact after this one has built on it.
[`test_readme_examples.py`](../../tests/functional/test_readme_examples.py)
drives every chapter through the Django test client, so the snippets are
checked in CI, not just prose.

To click through them:

```bash
just serve
```

That starts Django at **http://127.0.0.1:8000/**, whose index page lists the
chapters in order. Each chapter ends with a **▶ Try it live** link to its
start URL. These are local URLs — they only resolve while `just serve` is
running.

## One wizard

1. [Steps and completion](01-steps-and-completion.md) — two forms, a viewset, one URL include
2. [Branching on an answer](02-branching.md) — `.branch()`, and why a wizard is a value
3. [Switching on a choice](03-switching.md) — `.switch()` for *which*, not *whether*
4. [Expanding from an answer](04-expanding.md) — `.expand()` grows the tree mid-walk
5. [A wizard per request](05-a-wizard-per-request.md) — `get_wizard()` and mount prefixes
6. [The summary: check your answers](06-the-summary.md) — editing is a link; `SummaryMixin`
7. [Step views and escapes](07-step-views-and-escapes.md) — bring your own `FormView`; `Park`, `Advance`, `Obliterate`
8. [File uploads](08-file-uploads.md) — bytes outside the session
9. [Completion hooks and run metadata](09-completion-hooks-and-metadata.md) — `run_started()`, `done()` once, the metadata bag
10. [Stashing: leave and come back](10-stashing.md) — save answers and re-open them

## A task list of wizards

11. [Task lists: sections in any order](11-task-lists.md) — sections, statuses, one door
12. [Add another: a list the user grows](12-add-another.md) — items, change and remove
13. [Blocked and hidden sections](13-blocked-and-hidden.md) — sections that unlock or appear
14. [Journeys: scope, memory, groups and an ending](14-journeys.md) — everything, put together

## Knowing what you built

15. [Outline, observers and the driver](15-outline-observers-and-the-driver.md) — the shape, the events, and no browser

## Also

- [Coming from `django-formtools`](coming-from-django-formtools.md) — a declaration-by-declaration mapping
