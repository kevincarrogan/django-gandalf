DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "tests.testapp",
    "gandalf",
]

SECRET_KEY = "shhhhhhhhhh"

CACHE_BACKEND = "locmem://"

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

SITE_ID = 1

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    }
]

MEDIA_ROOT = "media"
STATIC_ROOT = "static"

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

USE_TZ = True

ROOT_URLCONF = "tests.testapp.urls"

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
