# django-gandalf

`django-gandalf` lets you declare **multi-step, tree-shaped Django form flows**
as readable, composable code.

You build a flow with a small, immutable builder — `.step()` to add a form,
`.branch()` to fork on an answer, `.expand()` to grow steps from an answer — and
mount it as an ordinary Django view. Gandalf handles the per-step URLs, the
session state, back-navigation, editing, file uploads, and running your
completion logic exactly once. When one wizard is not enough, it handles the
task list of wizards too: members the user does in any order, lists they
grow, members that unlock or appear because of what they said elsewhere, and
a submit at the end of all of it.

```python
from gandalf.wizard import Wizard, condition

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying_as")
    .branch(
        condition(is_organisation, Wizard().step(OrganisationForm, name="organisation")),
        default=Wizard().step(AboutYouForm, name="about_you"),
    )
    .step(EmailForm, name="contact")
)
```

The only dependency is Django. Coming from `django-formtools`? See
[Appendix D](docs/appendix-d-coming-from-django-formtools.md) for a
declaration-by-declaration mapping.

---

## Installation & setup

```bash
pip install django-gandalf   # or: uv add django-gandalf
```

Gandalf ships no models or migrations, but it does rely on a few pieces of
standard Django plumbing:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django.contrib.sessions",   # wizard state lives in the session
    "gandalf",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",  # required
    "django.middleware.csrf.CsrfViewMiddleware",
    # ...
]

TEMPLATES = [
    {
        # ...
        "OPTIONS": {
            "context_processors": [
                # required so `request.wizard` is reachable in step templates
                "django.template.context_processors.request",
            ],
        },
    }
]
```

Requires Python 3.10+ and Django 4.2+.

---

## How this README works

This README is one worked example. A community grant fund takes applications:
from individuals and from organisations, for a project with a budget, with
referees and a governing document and a final submit. Chapter 1 asks two
questions in a row. Each chapter after it adds one thing the application
needs, says why that thing exists, and leaves a runnable application behind.
By chapter 14 the whole thing is there, and chapter 15 is about knowing what
you built.

Every chapter is real code. It lives in
[`tests/testapp/readme/`](tests/testapp/readme/), one module per chapter, and
each module imports the one before it and grows it — which is itself the
first lesson, since a `Wizard` is a value and the previous chapter's
declaration is still intact after this one has built on it.
[`tests/functional/test_readme_examples.py`](tests/functional/test_readme_examples.py)
drives every chapter through the Django test client, so the snippets below
are checked in CI, not just prose.

To click through them:

```bash
just serve
```

That starts Django at **http://127.0.0.1:8000/**, whose index page lists the
chapters in order. Each chapter ends with a **▶ Try it live** link to
its start URL. These are local URLs — they only resolve while `just serve` is
running.

The reference material — testing, configuration, what replaying costs, and
the `django-formtools` mapping — is in the appendices at the end.

---

## The chapters

- [Chapter 1 — Steps and completion](docs/01-steps-and-completion.md)
- [Chapter 2 — Branching on an answer](docs/02-branching.md)
- [Chapter 3 — Switching on a choice](docs/03-switching.md)
- [Chapter 4 — Expanding from an answer](docs/04-expanding.md)
- [Chapter 5 — A wizard per request](docs/05-a-wizard-per-request.md)
- [Chapter 6 — The summary: check your answers](docs/06-the-summary.md)
- [Chapter 7 — Step views and escapes](docs/07-step-views-and-escapes.md)
- [Chapter 8 — File uploads](docs/08-file-uploads.md)
- [Chapter 9 — Completion hooks and run metadata](docs/09-completion-hooks-and-metadata.md)
- [Chapter 10 — Stashing: leave and come back](docs/10-stashing.md)
- [Chapter 11 — Hubs: a task list of members](docs/11-hubs.md)
- [Chapter 12 — Collections: add another](docs/12-collections.md)
- [Chapter 13 — Blocked and hidden members](docs/13-blocked-and-hidden.md)
- [Chapter 14 — Journeys: scope, memory, nesting and an ending](docs/14-journeys.md)
- [Chapter 15 — Outline, observers and the driver](docs/15-outline-observers-and-the-driver.md)
- [Appendix A — Testing your wizards](docs/appendix-a-testing-your-wizards.md)
- [Appendix B — Configuration](docs/appendix-b-configuration.md)
- [Appendix C — What replaying costs](docs/appendix-c-what-replaying-costs.md)
- [Appendix D — Coming from `django-formtools`](docs/appendix-d-coming-from-django-formtools.md)

---

## Contributing

See `CONTRIBUTING.md` for local setup, workflow expectations, separated unit
and functional test commands, and commit message conventions.
