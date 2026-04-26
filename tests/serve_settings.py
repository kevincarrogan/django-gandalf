from .settings import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ".gandalf-testapp.sqlite3",
    }
}

DEBUG = True

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
