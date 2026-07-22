"""Minimal Django settings for the benchmark harness.

Kept deliberately leaner than `tests.settings`: every component the walk does
not need is a constant added to each measurement. In particular the step
template is served from a locmem loader and renders almost nothing, so
template rendering does not swamp the walk cost we are trying to see.

Note that `benchmarks.journey` does *not* call
`django.test.utils.setup_test_environment()`. That helper swaps in an
instrumented template renderer to populate `response.context`, which is real
per-render overhead we do not want in the numbers.
"""

STEP_TEMPLATE_NAME = "benchmarks/step.html"

# No {% csrf_token %}: the test client does not enforce CSRF by default, and
# the tag costs a token fetch per render.
STEP_TEMPLATE = """<form method="post">{{ form.as_p }}</form>"""

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.sessions",
]

SECRET_KEY = "benchmarks-only"

ALLOWED_HOSTS = ["testserver"]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "OPTIONS": {
            "loaders": [
                (
                    "django.template.loaders.locmem.Loader",
                    {STEP_TEMPLATE_NAME: STEP_TEMPLATE},
                ),
            ],
            "context_processors": [],
        },
    }
]

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

USE_TZ = True

# Set per run by `benchmarks.journey`; there is no static urlconf because
# every benchmark wizard publishes its own.
ROOT_URLCONF = None

# Cache-backed sessions keep the DB out of the measurement entirely.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
