"""Optional integrations that ship with gandalf but are not part of it.

Nothing in `gandalf` proper imports anything from here, and nothing here
is installed by default. Each subpackage names an extra:

    pip install django-gandalf[agent]

The core keeps its single dependency on Django, which is the point of the
separation — a wizard library should not make you install an AI SDK to
render a form.
"""
