from django.urls import path

from . import views


urlpatterns = [
    path(
        "wizard/",
        views.SingleStepWizardViewSet.as_view(),
        name="single-step-wizard",
    ),
    path(
        "wizard/<uuid:run_id>/",
        views.SingleStepWizardViewSet.as_view(),
        name="single-step-wizard-run",
    ),
    path(
        "linear-wizard/",
        views.LinearWizardViewSet.as_view(),
        name="linear-wizard",
    ),
    path(
        "linear-wizard/<uuid:run_id>/",
        views.LinearWizardViewSet.as_view(),
        name="linear-wizard-run",
    ),
    path(
        "other-linear-wizard/",
        views.OtherLinearWizardViewSet.as_view(),
        name="other-linear-wizard",
    ),
    path(
        "other-linear-wizard/<uuid:run_id>/",
        views.OtherLinearWizardViewSet.as_view(),
        name="other-linear-wizard-run",
    ),
    path(
        "recreated-linear-wizard/",
        views.RecreatedLinearWizardViewSet.as_view(),
        name="recreated-linear-wizard",
    ),
    path(
        "recreated-linear-wizard/<uuid:run_id>/",
        views.RecreatedLinearWizardViewSet.as_view(),
        name="recreated-linear-wizard-run",
    ),
]
