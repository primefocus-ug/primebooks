from django import template

register = template.Library()

@register.filter
def has_perm(user, perm_name):
    return user.has_perm(perm_name)
