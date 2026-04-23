from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def gandalf_management_form(context):
    request = context.get("request")
    if request is None:
        return ""

    management_form = getattr(request, "gandalf_management_form", None)
    if management_form is None:
        return ""

    return mark_safe(management_form.as_p())
