"""Exceptions a step raises to leave the wizard.

A step's form or form view can decide mid-flow that the user does not belong
in the wizard any more — an email lookup finds an existing account, a chosen
option is handled by another part of the site entirely. Raising one of these
from anywhere the step's form is validated (a plain `Form.clean()`, a
`FormView.form_valid()`) redirects the browser to `to`; the subclass decides
what happens to the run that was left behind.

The redirect is issued only for the submission the user actually made.
Answers already stored replay on every later walk of the run, and a replayed
escape merely marks its step satisfied.
"""


class Escape(Exception):
    """Base class for wizard escapes — catch this to catch any of them.

    Carries the redirect target; the concrete subclasses (`Park`, `Advance`,
    `Obliterate`) decide what becomes of the run. Raising `Escape` itself is
    an error, because it names no disposition.

    `to` and any extra positional/keyword arguments are handed to
    `django.shortcuts.redirect`, so a URL, a named route with arguments, or a
    model with `get_absolute_url()` all work.
    """

    def __init__(self, to, *args, permanent=False, **kwargs):
        self.to = to
        self.redirect_args = args
        self.permanent = permanent
        self.redirect_kwargs = kwargs
        super().__init__(to)


class Park(Escape):
    """Leave, keeping the run parked on this step.

    The submission that escaped is discarded, along with any files it
    uploaded. Coming back to the run shows this step again, unanswered — the
    escape was a detour, and the step never completed.
    """


class Advance(Escape):
    """Leave, keeping the run and this answer.

    The submission is stored and satisfies the step, so returning to the run
    resumes at the next one. The step is done; the user is just being sent
    somewhere else before carrying on.
    """


class Obliterate(Escape):
    """Leave, destroying the run.

    Stored state and uploaded files are both removed, so the run is over —
    an exit rather than a detour. Returning to the wizard starts a new run.
    """
