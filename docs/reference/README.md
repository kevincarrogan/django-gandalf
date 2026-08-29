# Reference

One page per thing. Each page is in three parts — **Reference** (every
attribute, hook, argument and default), **Usage** (short, copy-pasteable
examples) and **Troubleshooting** (symptoms, causes, fixes) — and ends with
a pointer back to the [Learn](../learn/README.md) chapter that introduces it.

## Declaring a wizard

- [Wizard](wizard.md) — the builder: `.step()`, `.branch()`, `.switch()`, `.expand()`, `.configure()`; `condition`, `on_field`, `outline()`, `MergeCleanedData`
- [Configuration](configuration.md) — every `.configure()` key and its default; `storage_class`; settings and versions

## Serving it

- [WizardViewSet](viewsets.md) — URL names and hooks, `get_wizard()`, `run_started()`, `done()`, `run_unavailable()`, `begin()` / `inspect()` / `reopen()` / `resolve()`
- [Step views](step-views.md) — `StepFormView`, what a step may read, template context
- [Escapes](escapes.md) — `Park`, `Advance`, `Obliterate`
- [Summary](summary.md) — `SummaryMixin`, `Group`, `Hide`, rows and fields
- [File uploads](file-uploads.md) — `WizardFileStorage`, refs, replay, cleanup

## The run

- [Bound wizard](bound-wizard.md) — `BoundWizard`, `Path`, `RuntimeStep`, `WizardContext`, the stored state shape
- [Run metadata](run-metadata.md) — `bound_wizard.metadata` and its write-through semantics
- [Storage](storage.md) — the `WizardStorage` contract, `SessionStorage`, a durable backend
- [Stashing](stashing.md) — `stash()`, `resurrect()`, `SessionStashStore`
- [Walk costs](walk-costs.md) — what re-proving a run costs

## A task list of wizards

- [Hubs](hubs.md) — `Hub()`, `HubViewSet`, statuses, `blocked` / `hidden` rules, journeys, nesting, ending
- [Collections](collections.md) — `Collection`, `CollectionViewSet`, add / change / remove
- [Journey store](journey-store.md) — `SessionJourneyStore`, `store.data`, the `JourneyStore` / `CollectionStore` protocols

## From outside

- [Observers](observers.md) — `WizardObserver` events
- [Driver](driver.md) — `RunDriver`: fill a run without a browser
- [Agent](agent.md) — `gandalf.contrib.agent`: drive a wizard with a language model
- [Testing](testing.md) — the `wizard_driver` fixture, `WizardRun`, session seeders
