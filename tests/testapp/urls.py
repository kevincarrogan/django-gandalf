from django.urls import path

from tests.testapp import views


urlpatterns = [
    path("wizard/", views.WizardView.as_view(), name="wizard"),
]
