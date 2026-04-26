from django import template

register = template.Library()


@register.inclusion_tag("gandalf/management_form.html", takes_context=True)
def gandalf_management_form(context):
    wizard = context["request"].wizard

    return {
        "form": wizard.get_management_form(),
    }
