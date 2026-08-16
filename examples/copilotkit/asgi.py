"""ASGI entry point for the hybrid demo.

The AG-UI endpoint streams, so the demo is served by an ASGI server rather
than `runserver`: `uvicorn examples.copilotkit.asgi:application`.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "examples.copilotkit.settings")

application = get_asgi_application()
