"""Settings for the hybrid demo: `just hybrid-demo`.

The test app's settings plus the three things a demo needs — a file-backed
database (the agent's runs have to outlive the request that made them),
this package's templates and URLconf, and signed-cookie sessions so the
browser stays logged in as the demo user across a restart.
"""

from pathlib import Path

from tests.settings import *  # noqa: F403

BASE_DIR = Path(__file__).resolve().parent

DEBUG = True

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ".gandalf-hybrid.sqlite3",
    }
}

ROOT_URLCONF = "examples.copilotkit.urls"

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "examples.copilotkit.middleware.demo_login_middleware",
]

# The chat is served by Vite in development and proxies to this app, so
# form posts arrive with the dev server's origin.
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8100",
    "http://127.0.0.1:8100",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [BASE_DIR / "templates"],
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    }
]
