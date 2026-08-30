# django-gandalf

`django-gandalf` lets you declare **multi-step, tree-shaped Django form flows**
as readable, composable code.

You build a flow with a small, immutable builder — `.step()` to add a form,
`.branch()` to fork on an answer, `.expand()` to grow steps from an answer —
and mount it as an ordinary Django view. Gandalf handles the per-step URLs,
the session state, back-navigation, editing, file uploads, and running your
completion logic exactly once. When one wizard is not enough, it handles the
task list of wizards too: sections the user does in any order, lists they
grow, sections that unlock or appear because of what they said elsewhere, and
a submit at the end of all of it.

```python
from gandalf.wizard import Wizard, condition

application = (
    Wizard()
    .step(ApplyingAsForm, name="applying-as")
    .branch(
        condition(is_organisation, Wizard().step(OrganisationForm, name="organisation")),
        default=Wizard().step(AboutYouForm, name="about-you"),
    )
    .step(EmailForm, name="contact")
)
```

The only dependency is Django. Requires Python 3.10+ and Django 4.2+.

## Installation

```bash
pip install django-gandalf   # or: uv add django-gandalf
```

Gandalf ships no models or migrations, but it relies on standard Django
plumbing — the sessions app and middleware, and the `request` context
processor. [Configuration](docs/reference/configuration.md) has the exact
settings.

## Documentation

The docs are in two halves, and you can start at either.

**[Learn](docs/learn/README.md)** is a walkthrough: one community grant
application, built up a chapter at a time. Each chapter adds one idea, says
why it exists, and leaves a runnable application behind. It deliberately does
not cover every hook and every edge — read it start to finish the first time.

**[Reference](docs/reference/README.md)** is one page per thing —
`Wizard`, `WizardViewSet`, the summary, task lists, add another, storage, the
driver, the testing helpers — each with the complete API, worked usage, and
troubleshooting. Come here when you know what you are looking for.

| I want to… | Go to |
| --- | --- |
| build my first wizard | [Learn, chapter 1](docs/learn/01-steps-and-completion.md) |
| see every builder method | [Reference: Wizard](docs/reference/wizard.md) |
| override a viewset hook | [Reference: WizardViewSet](docs/reference/viewsets.md) |
| build a task list of wizards | [Learn, chapter 12](docs/learn/12-task-lists.md) · [Reference: Task lists](docs/reference/tasklists.md) |
| test a wizard | [Reference: Testing](docs/reference/testing.md) |
| migrate from `django-formtools` | [Coming from formtools](docs/learn/coming-from-django-formtools.md) |
| know what replaying costs | [Reference: Walk costs](docs/reference/walk-costs.md) |
| drive a wizard from a script or an agent | [Reference: Driver](docs/reference/driver.md) |

Every Learn chapter is real code under
[`tests/testapp/readme/`](tests/testapp/readme/), driven end to end by
[`tests/functional/test_readme_examples.py`](tests/functional/test_readme_examples.py).
`just serve` runs them at http://127.0.0.1:8000/ so you can click through.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup, the separated unit
and functional test commands, and commit conventions.
[`ARCHITECTURE.md`](ARCHITECTURE.md) is the runtime-level view of how the
pieces fit; [`AGENT_ACCESS.md`](AGENT_ACCESS.md) is the design behind the
driver and the agent.
