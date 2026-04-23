from django.urls import path

from tests.testapp import views


urlpatterns = [
    path("wizard/", views.WizardStepViewSet.as_view(), name="wizard"),
]
