import markdown

from django import template
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter
def render_markdown(value):
    if not value:
        return ""

    rendered_html = markdown.markdown(
        value,
        extensions=[
            "extra",
            "sane_lists",
            "nl2br",
        ],
    )

    return mark_safe(
        rendered_html
    )