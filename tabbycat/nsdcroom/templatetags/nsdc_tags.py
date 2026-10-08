from django import template

from nsdcroom import logic

register = template.Library()


@register.filter
def batchname(room):
    return logic.public_batch_name(room)
