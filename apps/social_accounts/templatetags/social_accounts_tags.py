from django import template

register = template.Library()


@register.filter
def format_number(value):
    """Format a number with K/M suffixes for compact display."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return value

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)
