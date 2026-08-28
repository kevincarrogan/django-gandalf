# Appendix A — Testing your wizards

Driving a multi-step wizard with the raw Django test client means chasing the
run id through the session and hand-building step URLs. `gandalf.testing`
does that plumbing for you, and a pytest plugin ships with the package —
installing django-gandalf makes the `wizard_driver` fixture available with no
conftest wiring (it builds on
[pytest-django](https://pytest-django.readthedocs.io/)'s `client` fixture).

`wizard_driver` is a factory: give it your viewset's `url_name` — the driver
reverses the same three names `urls()` published — and drive the whole wizard
in one call. For chapter 1:

```python
def test_chapter_1_collects_both_steps_and_finishes_once(wizard_driver):
    response, run = wizard_driver("readme-first").drive(
        [
            ("applicant", {"full_name": "Ada"}),
            ("contact", {"email": "ada@example.com"}),
        ]
    )

    assert response.status_code == 200
    assert run.is_completed
```

`drive()` starts a run (discovering its id from the session), POSTs each
`(step, data)` pair following redirects, and returns the final response along
with a `WizardRun` — URLs, requests, and stored state, all keyed by the run
id. Step by step, the same run object makes redirect and state assertions
direct:

```python
def test_chapter_1_first_answer_advances_and_stores(wizard_driver):
    run = wizard_driver("readme-first").start()

    response = run.post_step("applicant", {"full_name": "Ada"})

    assert response["Location"] == run.step_url("contact")
    assert run.state == [{"step": {"full_name": "Ada"}}]
```

Request helpers default to `follow=False` like the test client — pass
`follow=True` to land on the rendered next step. The run also exposes
`run.url`, `run.get()`, `run.get_step("name")` (the edit render of an
answered step), `run.data` (the raw session entry — `{"completed": True}`
after `done()` fires), and `run.seed_state([...])`.

- **Mount-prefix kwargs.** A wizard mounted under `readme/funds/<slug:fund>/`
  is driven with `wizard_driver("readme-fund", fund="arts")`.
- **Multiple runs.** `driver.start()` works with any number of existing runs;
  `driver.only_run()` and `driver.new_run(*known)` recover a run you didn't
  start yourself (a resurrected stash, say), raising `RunDiscoveryError` when
  the session is ambiguous.
- **Uploads** ride along as ordinary POST data:
  `run.post_step("governing_document", {"document": SimpleUploadedFile(...)})`.
- **Arranging a part-answered run.** `seed_state` writes stored state
  *verbatim*, so reach for it only when the state is one no walk would place.
  Answers the walk can reach are better placed than written: fill the run
  with a `RunDriver` over the client's own session, and the state is whatever
  the runtime really produces.

  ```python
  from gandalf.driver import RunDriver, fabricate_request

  session = client.session
  driver = RunDriver.resume(
      FirstApplicationViewSet, run.run_id, request=fabricate_request(session=session)
  )
  driver.prefill({"applicant": {"full_name": "Ada"}})
  session.save()   # nothing saves a session outside the request cycle
  ```

- **Session peeking and seeding.** `stored_runs(client)` /
  `stored_run(client, run_id)` / `seed_run(client, run_id, data)` read and
  write raw run entries; `stored_stash(client, key)` / `seed_stash(...)` do
  the same for caller-owned stash payloads (chapter 10); and
  `stored_journey(client)`, `stored_member_run(client, key)` /
  `seed_member_run(...)`, `stored_member_stash(client, key)` /
  `seed_member_stash(...)`, `stored_journey_data(client)` /
  `seed_journey_data(...)` and `seed_journey_complete(client)` do it for a
  journey's record, each taking `journey=` for a hub mounted under one — no
  session keys in your tests. They read the session stores directly, so they
  do not apply to a custom backend; assert against your own models instead.
- **Outside pytest** the helpers work from any test:
  `WizardTestDriver(Client(), "readme-first")`.
- Wizards with a **custom URL scheme** fall outside the driver's contract —
  drive those with the plain test client. To keep the plugin out of a run
  entirely: `pytest -p no:gandalf`.

Gandalf's own functional suite is written with these helpers, and the
snippets above are the checked-in tests for chapter 1 — **Source:**
[`test_readme_examples.py`](../tests/functional/test_readme_examples.py).

---

[← Chapter 15 — Outline, observers and the driver](15-outline-observers-and-the-driver.md) · [README](../README.md) · [Appendix B — Configuration →](appendix-b-configuration.md)
