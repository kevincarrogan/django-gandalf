# Testing

`gandalf.testing` — test-client helpers for driving a wizard and reading the
session it writes, and the `wizard_driver` pytest fixture that hands them out.

```python
from gandalf.testing import (
    RunDiscoveryError,
    WizardRun,
    WizardTestDriver,
    seed_item,
    seed_journey_complete,
    seed_journey_data,
    seed_section_run,
    seed_section_stash,
    seed_run,
    seed_stash,
    stored_items,
    stored_journey,
    stored_journey_data,
    stored_section_run,
    stored_section_runs,
    stored_section_stash,
    stored_section_stashes,
    stored_run,
    stored_runs,
    stored_stash,
    stored_stashes,
)
```

Driving a multi-step wizard with the raw Django test client means chasing
the run id through the session and hand-building step URLs. The driver does
that plumbing: it binds a `django.test.Client` to the three URL names a
[`WizardViewSet.urls()`](viewsets.md) publishes (`<url_name>`,
`<url_name>-run`, `<url_name>-step`) and hands out `WizardRun` objects that
make requests and read stored state without the test touching a session key.
The module-level functions read and seed the session stores directly, for
tests that arrange or assert on raw run, stash and journey payloads.

Two limits, both structural:

- **Session-backed only.** Every helper reads the keys
  [`SessionStorage`](storage.md), `SessionStashStore` and
  [`SessionJourneyStore`](journey-store.md) write. A viewset on a custom
  `storage_class` (or store class) keeps nothing there, so `run.state`,
  `run.is_completed`, `stored_stash(...)` and the rest see an empty session.
  Drive such a wizard with the driver's request helpers and assert on your
  own models.
- **Published URL scheme only.** A viewset that overrides `get_wizard_url` /
  `get_step_url` falls outside the driver's contract; drive it with the plain
  test client.

---

## Reference

### The `wizard_driver` fixture

A factory for `WizardTestDriver` bound to
[pytest-django](https://pytest-django.readthedocs.io/)'s `client` fixture:

```python
def test_first_wizard(wizard_driver):
    driver = wizard_driver("readme-first")
    scoped = wizard_driver("readme-fund", fund="arts")
```

`wizard_driver(url_name, **url_kwargs)` returns
`WizardTestDriver(client, url_name, **url_kwargs)`.

It ships in `gandalf.pytest_plugin`, registered through the `pytest11` entry
point (`pyproject.toml`), so installing django-gandalf makes the fixture
available in every project with no `conftest.py` wiring. The plugin is
imported at pytest bootstrap — before Django settings are configured and
before coverage starts — so it imports only pytest at module level and
defers `gandalf.testing` (and with it Django) into the fixture body.

To keep the plugin out of a run entirely: `pytest -p no:gandalf`.

Outside pytest the helpers work from any test that has a client:
`WizardTestDriver(Client(), "readme-first")`.

### `WizardTestDriver(client, url_name, **url_kwargs)`

Drives one wizard, mounted via `WizardViewSet.urls()`, through a Django test
client.

**Parameters**

- `client` — a `django.test.Client`. The driver holds it and reads its
  `session`.
- `url_name` — the viewset's `url_name`; the driver reverses `url_name`,
  `f"{url_name}-run"` and `f"{url_name}-step"`.
- `**url_kwargs` — the mount-prefix kwargs. For a wizard mounted under
  `path("prefix/<slug:org>/", include(...))`, pass `org=...`; they are
  forwarded into every URL reversal.

**Attributes** — `client`, `url_name`, `url_kwargs`.

#### `start_url` *(property)*

The wizard's start URL, `reverse(url_name, kwargs=url_kwargs)`. GETting it
creates a fresh run and redirects to it.

#### `run_url(run_id)`

The bare run URL for `run_id`.

#### `step_url(run_id, step)`

The routed URL for step segment `step` of `run_id` — reversed with
`gandalf_step=step`.

#### `start()`

GET the start URL and return the `WizardRun` it created. The run id is
discovered by diffing the session's run ids around the request, so starting
works however many runs the session already holds.

**Returns** — a `WizardRun`.

**Raises** — `RunDiscoveryError` when the GET did not create exactly one run.

#### `drive(steps)`

`start()` a run, then `post_steps(steps)` on it.

**Parameters**

- `steps` — a list of `(step, data)` pairs, POSTed in order with
  `follow=True`. `data` may be `None`.

**Returns** — `(final_response, run)`. `final_response` is the last followed
response, or `None` for an empty list.

#### `run(run_id)`

Bind an existing run id — one a resurrect view created, a seeded run, or an
id that was never started — without making a request.

**Returns** — a `WizardRun`.

#### `only_run()`

The session's only run, as a `WizardRun`.

**Raises** — `RunDiscoveryError` unless the session holds exactly one run.
Completion tombstones count as runs.

#### `new_run(*known)`

The one run in the session that is not in `known`.

**Parameters**

- `*known` — `WizardRun` instances or run-id strings to ignore.

**Raises** — `RunDiscoveryError` unless exactly one run is new.

### `WizardRun(driver, run_id)`

One run of a driver's wizard: request helpers and stored-state access keyed
by `run_id`. Made by the driver's `start()`, `run()`, `only_run()` and
`new_run()`; constructing one directly is equivalent to `driver.run(run_id)`.

Request helpers default to `follow=False`, matching `django.test.Client`, so
redirect assertions read naturally; pass `follow=True` to land on the
rendered step. `post_steps` always follows, because advancing through the
POST-redirect-GET cycle is its whole point. Every helper returns what the
test client returns — an `HttpResponse` with `context`, `templates` and
`json()`.

**Attributes**

- `driver` — the `WizardTestDriver`.
- `run_id` — the run id, always a `str`.

#### `url` *(property)*

The bare run URL. A GET redirects to the cursor step, or completes the run.

#### `step_url(step)`

This run's routed URL for step segment `step`.

#### `get(follow=False)`

GET the bare run URL.

#### `get_step(step, follow=False)`

GET a step URL — the render, or the edit render of an answered step.

#### `post(data=None, follow=False)`

POST to the bare run URL — the step-less POST the viewset bounces back to
the cursor step.

#### `post_step(step, data=None, follow=False)`

POST `data` to a step URL. Uploads ride along as ordinary `data` values
(`SimpleUploadedFile` and friends); the test client multipart-encodes them
as usual.

#### `post_steps(steps)`

POST each `(step, data)` pair in order with `follow=True`.

**Returns** — the last response, or `None` for an empty list.

#### `data` *(property)*

The raw session entry for this run, from `stored_run(client, run_id)`:

| Run | `data` |
| --- | --- |
| started, nothing answered | `{}` |
| answered | `{"state": [...]}`, plus `"meta"` once metadata is written |
| completed | `{"completed": True}`, plus `"meta"` if the run had any |

Exact-shape assertions — tombstones, `files` entries in state, the metadata
bag — go through this.

**Raises** — `KeyError` for a run the session does not hold.

#### `state` *(property)*

The stored state list, `data.get("state", [])` — empty for a fresh or a
completed run.

#### `is_completed` *(property)*

`data.get("completed", False)` — whether the run has finished and left a
completion tombstone.

#### `seed_state(state)`

Overwrite this run's stored state list with `state` verbatim, keeping the
rest of the entry, and save the session. For arranging session state the
request cycle cannot produce. The run entry must already exist — `start()`
it, or `seed_run()` it first.

### `RunDiscoveryError`

A subclass of `AssertionError`. The session does not identify exactly one
run — none where one was expected, or several where the discovery needed to
be unambiguous. Raised by `start()`, `only_run()` and `new_run()`.

### Run store

The session key `SessionStorage.SESSION_KEY` (`"gandalf_runs"`).

#### `stored_runs(client)`

The session's run mapping, `{run_id: RunData}`, or `{}` before any run
exists. Live runs map to `{"state": [...]}`-shaped entries (an empty dict
before the first answer); completed runs leave `{"completed": True}`
tombstones.

#### `stored_run(client, run_id)`

The raw session entry for `run_id`.

**Raises** — `KeyError` for a run this session does not hold: never started,
obliterated, or lost with an expired session.

#### `seed_run(client, run_id, data)`

Write `data` verbatim as the session entry for `run_id`, creating the run
mapping when the session has never held one, and save the session. For
arranging runs the request cycle cannot produce: legacy state shapes,
tampered entries, or runs addressed by a custom URL scheme.

### Stash store

The session key `SessionStashStore.SESSION_KEY` (`"gandalf_stashes"`) — the
caller-owned payloads of [stashing](stashing.md).

#### `stored_stashes(client)`

The session's stash mapping, `{key: Stash}`, or `{}` before any stash.

#### `stored_stash(client, key)`

The stash payload under `key`.

**Raises** — `KeyError` when absent.

#### `seed_stash(client, key, payload)`

Write `payload` under `key`, creating the stash mapping when the session has
never held one, and save the session. For arranging hand-built or tampered
stashes.

### Journey store

The session key `SessionJourneyStore.SESSION_KEY` (`"gandalf_journeys"`)
holds one record per journey — its section runs, its stashes, its
add-another registries, its data, and the tombstone a submitted journey
leaves. Every helper below takes `journey="default"`: the fixed journey a
task list not mounted under a `<journey>` URL segment uses
(`TaskListViewSet.journey`). For a page mounted
under one, pass the segment's value.

| Record key | Written by | Read with |
| --- | --- | --- |
| `"runs"` | entering a section | `stored_section_run(s)` |
| `"stashes"` | a section finishing | `stored_section_stash(es)` |
| `"data"` | `store.data`, under the `"journey"` bucket | `stored_journey_data` |
| `"collections"` | an add-another page registering an item | `stored_items` |
| `"completed"` | the journey being submitted | `stored_journey(...)["completed"]` |

#### `stored_journey(client, journey="default")`

The whole record for `journey`, or `{}` before anything has been written to
it.

#### `stored_section_runs(client, journey="default")`

The journey's section-to-run mapping, `{key: run_id}`, or `{}` before any
section has been entered.

#### `stored_section_run(client, key, journey="default")`

The run id recorded for section `key`, or `None` when the section is not
being answered. A section's completion is its stash, not its run — read it with
`stored_section_stash`.

#### `seed_section_run(client, key, run_id, journey="default")`

Record `run_id` (stored as `str`) as where section `key` is being answered,
creating the journey's record when the session has never held one, and save
the session. For arranging the states a task list reaches only after several
requests: a section left half-answered, or one pointing at a run the storage
no longer holds.

#### `stored_section_stashes(client, journey="default")`

The journey's stash mapping — one payload per finished section — or `{}`
before any section has finished.

#### `stored_section_stash(client, key, journey="default")`

The stash a finished section left under `key`.

**Raises** — `KeyError` for one that has not finished.

#### `seed_section_stash(client, key, payload, journey="default")`

Record section `key` as finished with `payload`, and save the session. For
arranging a task list with sections already done, or a hand-built or tampered
stash.

#### `stored_journey_data(client, journey="default")`

The journey's decided facts — the raw envelope `store.data` reads, every
bucket — or `{}` before anything was written. The journey's own facts sit
under `"journey"`: `stored_journey_data(client)["journey"]["amount"]`.

#### `seed_journey_data(client, data, journey="default")`

Merge `data` into the journey's own decided facts (the `"journey"` bucket
`store.data` reads), keeping what is already there, and save the session.
For arranging a task list whose sections have already decided something —
an answer that hides or unlocks another section.

#### `seed_journey_complete(client, journey="default")`

Replace the journey's record with the tombstone a submitted journey leaves:
`{"completed": True}`, plus `"data"` when the record held any. Runs,
stashes and add-another registries are dropped. Saves the session.

#### `stored_items(client, key, journey="default")`

The item ids an add-another page lists, in the order the user added them.
`[]` for a list nobody has added to. A row exists from the moment an item is
registered, so this includes items with no answers yet — which is what makes
them distinguishable from items that were never added.

#### `seed_item(client, key, item_id, title=None, journey="default")`

Register an item under add-another list `key` (stored as `str`), optionally with
the `title` a finished one would have cached, and save the session. Creates
the list's record — `{"items": [], "declared_done": False}` — when
there is none. For arranging the states an add-another page reaches only after
several requests.

---

## Usage

The snippets here are the checked-in tests for chapter 1 and its successors —
[`test_readme_examples.py`](../../tests/functional/test_readme_examples.py)
— so they stop passing if this page drifts.

### Driving a whole wizard

```python
from http import HTTPStatus


def test_collects_both_steps_and_finishes_once(wizard_driver):
    response, run = wizard_driver("readme-first").drive(
        [
            ("applicant", {"full_name": "Ada"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"Application received from Ada <ada@example.com>"
    assert run.is_completed
```

### Asserting one step at a time

```python
def test_first_answer_advances_and_stores(wizard_driver):
    run = wizard_driver("readme-first").start()

    response = run.post_step("applicant", {"full_name": "Ada"})

    assert response["Location"] == run.step_url("contact")
    assert run.state == [{"step": {"full_name": "Ada"}}]
```

`post_step` returns the 302 by default. To look at the rendered next step
instead, pass `follow=True` and read `response.context["form"]`; to look at
the edit render of an answered step, `run.get_step("applicant")`.

### A wizard mounted under a prefix

For a viewset included under `readme/funds/<slug:fund>/`, the mount kwarg is
part of every URL the driver reverses:

```python
def test_the_arts_fund_inserts_a_portfolio_step(wizard_driver):
    response, _ = wizard_driver("readme-fund", fund="arts").drive(
        [
            ("applying-as", {"applying_as": "individual"}),
            ("about-you", {"occupation": "Sculptor"}),
            ("portfolio", {"portfolio_url": "https://ada.example.com"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.content == b"Application to the arts fund from ada@example.com"
```

### Uploading a file

```python
from django.core.files.uploadedfile import SimpleUploadedFile


def test_stores_the_governing_document(wizard_driver, isolated_media_root):
    run = wizard_driver("readme-upload").start()
    document = SimpleUploadedFile(
        "constitution.pdf", b"bytes", content_type="application/pdf"
    )

    response = run.post_step("governing-document", {"document": document}, follow=True)

    assert response.status_code == HTTPStatus.OK
```

`isolated_media_root` is the test suite's own fixture pointing `MEDIA_ROOT`
at a temporary directory; use whatever your project does to keep stored
uploads out of the real media root. See [File uploads](file-uploads.md).

### Arranging a part-answered run

`seed_state` writes stored state *verbatim*, so reach for it only when the
state is one no walk would place. Answers the walk can reach are better
placed than written: fill the run with a [`RunDriver`](driver.md) over the
client's own session, and the state is whatever the runtime really
produces.

```python
from gandalf.driver import RunDriver

from tests.testapp.readme.ch01_first_wizard import FirstApplicationViewSet


def test_resumes_at_the_contact_step(wizard_driver, client):
    run = wizard_driver("readme-first").start()

    session = client.session
    driver = RunDriver.resume(FirstApplicationViewSet, run.run_id, session=session)
    driver.prefill({"applicant": {"full_name": "Ada"}})
    session.save()   # nothing saves a session outside the request cycle

    response = run.get()

    assert response["Location"] == run.step_url("contact")
```

`client.session` builds a fresh session object on every access, so hold one
reference, hand it to the driver, and save that same object.

### Testing a task list through the journey store

A task list's rows never walk a wizard; they read the journey record. So a
test that wants a section in a given state can seed the record instead of
driving the section:

```python
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from gandalf.testing import (
    seed_section_run,
    seed_section_stash,
    stored_section_run,
    stored_section_stash,
)


def test_a_section_pointing_at_a_forgotten_run_starts_again(client):
    seed_section_run(client, "contact", "00000000-0000-0000-0000-000000000000")

    response = client.get(reverse("readme-task-list-entry", kwargs={"entry": "contact"}))

    run_id = stored_section_run(client, "contact")
    assert run_id != "00000000-0000-0000-0000-000000000000"
    assertRedirects(
        response,
        reverse("readme-task-list-contact-step", kwargs={"run_id": run_id, "gandalf_step": "name"}),
    )


def test_a_finished_section_reads_as_complete(client):
    seed_section_stash(client, "contact", {"version": 1, "label": "contact", "state": []})

    assertContains(client.get(reverse("readme-task-list")), "Complete")
```

And to drive a section through the page's door, recover the run the door
created with `only_run()`:

```python
def test_lists_sections_and_drives_one_to_complete(client, wizard_driver):
    client.get(reverse("readme-task-list-entry", kwargs={"entry": "contact"}), follow=True)
    run = wizard_driver("readme-task-list-contact").only_run()

    run.post_steps(
        [
            ("name", {"full_name": "Ada"}),
            ("email", {"email": "ada@example.com"}),
            ("review", {}),
        ]
    )

    assert stored_section_stash(client, "contact")["state"][0] == {
        "step": {"full_name": "Ada"}
    }
```

For a page mounted under `apply/<slug:journey>/`, every helper takes the
segment: `seed_journey_data(client, {"amount": 20_000}, journey="app-1")`
reveals a section whose visibility hangs on `amount`, and
`seed_journey_complete(client, journey="app-1")` makes the page read as
submitted.

---

## Troubleshooting

### `fixture 'wizard_driver' not found`

Either pytest-django is not installed (the fixture takes its `client`), or
the plugin has been disabled with `-p no:gandalf`, or django-gandalf is
installed in a way that skipped its entry points (an editable install from
before the `pytest11` entry point was declared, say). Reinstall, or build the
driver by hand: `WizardTestDriver(client, "readme-first")`.

### `RunDiscoveryError: expected the session to hold exactly one run, found 2`

`only_run()` needs an unambiguous session, and completion tombstones count.
After a resurrect or a second `start()`, use `new_run(*known)` with the runs
you already hold, or `run(run_id)` with an id you read from elsewhere
(`stored_section_run(client, key)` for a section of a task list).

### `RunDiscoveryError` from `start()`

The GET of the start URL did not create exactly one run. Usually the start
view redirected somewhere else — a door refusing a blocked section, a
`run_unavailable` hook — or the viewset is on a custom storage that writes
nothing to the session.

### `run.state` is `[]` after a POST that clearly succeeded

Either the run completed on that POST (`run.is_completed` is `True`; the
tombstone keeps `meta` but drops `state`), or the viewset is not
session-backed. For a custom `storage_class`, assert on your own models.

### `KeyError` from `run.data` or `stored_stash`

The session does not hold that entry. A run: never started, obliterated, or
addressed by an id from another session. A stash: the wizard has not
completed yet, or stashes under a different key. Both readers raise rather
than returning a default so a wrong key fails loudly; `stored_runs` and
`stored_stashes` return the whole mapping if you want to look around.

### `NoReverseMatch` when the driver builds a URL

The wizard is mounted under a prefix and the driver was not given its
kwargs: `wizard_driver("readme-fund", fund="arts")`. If the viewset
overrides `get_wizard_url` / `get_step_url`, the published names do not
describe its URLs; drive it with `client.get(...)` and `client.post(...)`.

### A `RunDriver` placed answers but the next request does not see them

`client.session` is a new object on every access, and nothing saves a
session outside the request cycle. Hold one `session = client.session`,
pass it to `RunDriver.resume(..., session=session)`, and call
`session.save()` afterwards.

---

**Learn:** [Chapter 1 — Steps and completion](../learn/01-steps-and-completion.md) · **Related:** [`RunDriver`](driver.md), [`WizardViewSet`](viewsets.md), [Storage](storage.md), [Stashing](stashing.md), [Task lists](tasklists.md), [Journey store](journey-store.md), [Add another](add-another.md)
