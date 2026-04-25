from django.urls import path

from . import views


urlpatterns = [
    path("wizard/", views.SingleStepWizardViewSet.as_view(), name="single-step-wizard"),
]
