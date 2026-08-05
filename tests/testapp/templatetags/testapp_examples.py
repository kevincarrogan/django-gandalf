"""Template access to the example catalogue.

Every wizard page renders a banner naming the example it belongs to. The
page cannot be told which example that is — thirty of them share
`linear_wizard.html`, and a step view has no handle on the viewset that
dispatched it — so it asks the URL instead.
"""

from django import template

from .. import catalogue


register = template.Library()


@register.simple_tag(takes_context=True)
def current_example(context):
    """What the current request is an example of.

    Returns a dict of `entry`, `group`, `step` and `run_id`, all empty
    outside a catalogued wizard (the index page itself, say), so the banner
    can simply not render. Nothing here walks the run: a banner that made
    the page it decorates re-validate every stored answer would put the
    demo site's own furniture into the walk counts these examples exist to
    measure.
    """
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match is None or match.url_name is None:
        return {}
    return {
        "entry": catalogue.entry_for(match.url_name),
        "group": catalogue.group_for(match.url_name),
        "step": match.kwargs.get("gandalf_step"),
        "run_id": match.kwargs.get("run_id"),
    }
