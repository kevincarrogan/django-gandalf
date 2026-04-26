from django.urls import path

from . import views


urlpatterns = [
    path("wizard/", views.SingleStepWizardViewSet.as_view(), name="single-step-wizard"),
    path("linear-wizard/", views.LinearWizardViewSet.as_view(), name="linear-wizard"),
    path(
        "other-linear-wizard/",
        views.OtherLinearWizardViewSet.as_view(),
        name="other-linear-wizard",
    ),
]
