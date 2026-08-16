"""Test-suite-wide guards.

The example agents choose their model from the environment, and `just`
loads a `.env` so the live demos can find an API key. Without this, a
developer holding a real key would have the suite construct
provider-backed agents just by importing the demo modules — and a test
that forgot to override the model would quietly spend money. Tests never
call a model for real: they script pydantic-ai's `FunctionModel` or use
its canned `test` model. Pin that here, before anything imports.
"""

import os

os.environ["GANDALF_AGENT_MODEL"] = "test"
