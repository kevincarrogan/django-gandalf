"""The hybrid demo's URLconf: a chat endpoint, a wizard, and a collection.

`HybridQuoteViewSet.urls()` publishes the ordinary gandalf patterns — the
start URL, the bare run URL, and a URL per step. Those step URLs are what
the agent hands the person, and what the person's browser then walks
through as an ordinary Django form.

The fleet is mounted *beside* the quote rather than under it, and the item
wizard beside the collection: a collection page and the wizard behind its
rows both publish a start URL, so nesting them makes one silently swallow
the other's door.
"""

from django.urls import include, path

from examples.copilotkit import views
from examples.copilotkit.wizards import HybridQuoteViewSet
from examples.insurance import VehicleCollectionView, VehicleItemViewSet

urlpatterns = [
    path("", views.index, name="index"),
    path("agent/", views.agent_endpoint, name="agent"),
    path("quote/", include(HybridQuoteViewSet.urls())),
    path("vehicles/", include(VehicleCollectionView.urls())),
    path("vehicle/<uuid:item>/", include(VehicleItemViewSet.urls())),
]
