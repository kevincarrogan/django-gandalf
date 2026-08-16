"""Sign every visitor in as the same demo user.

The durable storage this demo uses scopes runs to their owner — that is
gandalf's whole authorisation story for a run, and it is the reason the
agent and the browser can be trusted with the same run id. A demo has no
sign-up flow, so everyone is the same person; the scoping is real, the
identity is a stand-in.
"""

from django.contrib.auth import get_user_model, login

DEMO_USERNAME = "demo"


def demo_login_middleware(get_response):
    def middleware(request):
        if not request.user.is_authenticated:
            user_model = get_user_model()
            user, _ = user_model.objects.get_or_create(username=DEMO_USERNAME)
            login(
                request,
                user,
                backend="django.contrib.auth.backends.ModelBackend",
            )
        return get_response(request)

    return middleware
