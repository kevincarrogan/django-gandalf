# Reference

One page per thing. Each page is in three parts — **Reference** (every
attribute, hook, argument and default), **Usage** (short, copy-pasteable
examples) and **Troubleshooting** (symptoms, causes, fixes) — and ends with
a pointer back to the [Learn](../learn/README.md) chapter that introduces it.

## Declaring a wizard

- [Wizard](wizard.md) — the builder: `.step()`, `.branch()`, `.switch()`, `.expand()`; `condition`, `on_field`, `outline()`, `MergeCleanedData`, `Reducer`
- [Configuration](configuration.md) — every seam on the viewset and its default: `template_name`, `storage_class`, `observer_class`, …; settings and versions

## Serving it

- [WizardViewSet](viewsets.md) — URL names and hooks, `get_wizard()`, `run_started()`, `done()`, `run_unavailable()`, `begin()` / `inspect()` / `reopen()` / `resolve()`
- [Step views](step-views.md) — `StepFormView`, what a step may read, template context
- [Escapes](escapes.md) — `Park`, `Advance`, `Obliterate`
- [Summary](summary.md) — `SummaryMixin`, `Answer`, `Question`, `Hide`, rows
- [File uploads](file-uploads.md) — `WizardFileStorage`, refs, replay, cleanup

## The run

- [The run](run.md) — `Run`, `Path`, `RuntimeStep`, `WizardContext`, the stored state shape
- [Run metadata](run-metadata.md) — `run.metadata` and its write-through semantics
- [Proofs](proofs.md) — `run.proof()`: holding a check that cannot be performed twice
- [Storage](storage.md) — the `WizardStorage` contract, `SessionStorage`, a durable backend
- [Stashing](stashing.md) — `stash()`, `resurrect()`, `SessionStashStore`
- [Walk costs](walk-costs.md) — what re-proving a run costs

## A task list of wizards

- [Task lists](tasklists.md) — `TaskList`, `Section`, `Group`, `TaskListViewSet`, `SectionViewSet`, statuses, `blocked()` / `hidden()`, journeys, groups, ending
- [Add another](add-another.md) — `AddAnother`, `AddAnotherViewSet`, `ItemViewSet`, add / change / remove
- [Journey store](journey-store.md) — `SessionJourneyStore`, `store.metadata`, the `JourneyStore` / `ItemStore` protocols

## From outside

- [Observers](observers.md) — `WizardObserver` events
- [Driver](driver.md) — `RunDriver`: fill a run without a browser
- [Agent](agent.md) — `gandalf.contrib.agent`: drive a wizard with a language model
- [Testing](testing.md) — the `wizard_driver` fixture, `WizardRun`, session seeders
