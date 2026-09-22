"""Server-rendered SVG charts.

No chart library: an HTMX-swapped <canvas> needs its library re-initialised
after every swap, which is a steady source of blank charts. SVG rendered by the
server swaps correctly by definition, themes with the coral palette for free
and prints.
"""

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

CORAL = "#F0524A"
CORAL_LIGHT = "#FECDCA"
GRID = "#E5E7EB"


def _points(values, width, height, pad=2):
    if not values:
        return []
    top = max(values) or 1
    span = max(len(values) - 1, 1)
    return [
        (
            pad + index * (width - 2 * pad) / span,
            height - pad - (value / top) * (height - 2 * pad),
        )
        for index, value in enumerate(values)
    ]


@register.simple_tag
def sparkline(data, width=160, height=40):
    """A bare trend line. ``data`` is a list of (label, value)."""
    values = [float(v) for _, v in data]
    pts = _points(values, width, height)
    if not pts:
        return mark_safe(
            f'<svg width="{width}" height="{height}" role="img" aria-label="No data"></svg>'
        )

    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    area = f"{path} L{pts[-1][0]:.1f},{height} L{pts[0][0]:.1f},{height} Z"
    return mark_safe(
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Trend over {len(values)} points">'
        f'<path d="{area}" fill="{CORAL}" opacity="0.12"/>'
        f'<path d="{path}" fill="none" stroke="{CORAL}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


@register.simple_tag
def bar_chart(data, height=140, label=""):
    """Vertical bars. ``data`` is a list of (label, value)."""
    if not data:
        return mark_safe('<p class="text-sm text-gray-400">No data yet.</p>')

    top = max(float(v) for _, v in data) or 1
    bars = []
    for name, value in data:
        pct = float(value) / top * 100
        # Both the label and the value are escaped: a category name can come
        # from a test title, which staff type.
        safe_name = escape(str(name))
        safe_value = escape(str(value))
        bars.append(
            '<div class="flex-1 flex flex-col items-center gap-1 min-w-0">'
            f'<div class="w-full flex items-end" style="height:{height}px">'
            f'<div class="w-full rounded-t-md" style="height:{max(pct, 1.5):.1f}%;'
            f'background:{CORAL}" title="{safe_name}: {safe_value}"></div>'
            "</div>"
            '<span class="text-[10px] text-gray-400 truncate w-full text-center">'
            f"{safe_name}</span>"
            '<span class="text-[10px] font-semibold text-gray-600">'
            f"{safe_value}</span>"
            "</div>"
        )
    aria = f' aria-label="{escape(label)}"' if label else ""
    return mark_safe(
        f'<div class="flex items-end gap-2" role="img"{aria}>' + "".join(bars) + "</div>"
    )


@register.simple_tag
def histogram(data, height=120):
    """Same marks as bar_chart, but ordered buckets rather than categories."""
    return bar_chart(data, height=height, label="Distribution")


@register.simple_tag
def donut(value, total=100, size=96, caption=""):
    """A single ratio. Percentages read faster as an arc than as a bar."""
    total = float(total) or 1
    pct = max(0.0, min(1.0, float(value) / total))
    radius = size / 2 - 8
    circumference = 2 * 3.14159 * radius
    filled = circumference * pct
    centre = size / 2

    safe_caption = escape(caption or "ratio")
    track = (
        f'<circle cx="{centre}" cy="{centre}" r="{radius}" fill="none" '
        f'stroke="{CORAL_LIGHT}" stroke-width="8"/>'
    )
    arc = (
        f'<circle cx="{centre}" cy="{centre}" r="{radius}" fill="none" '
        f'stroke="{CORAL}" stroke-width="8" stroke-linecap="round" '
        f'stroke-dasharray="{filled:.1f} {circumference:.1f}" '
        f'transform="rotate(-90 {centre} {centre})"/>'
    )
    caption_text = (
        f'<text x="{centre}" y="{centre + 5}" text-anchor="middle" font-size="18" '
        f'font-weight="800" fill="#111827" '
        f'font-family="Plus Jakarta Sans, Inter, sans-serif">{pct * 100:.0f}%</text>'
    )
    return mark_safe(
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="{safe_caption}: {pct * 100:.0f} percent">'
        f"{track}{arc}{caption_text}</svg>"
    )


@register.simple_tag
def hbar(value, total, color=CORAL):
    """An inline proportion bar for table rows."""
    total = float(total) or 1
    pct = max(0.0, min(100.0, float(value) / total * 100))
    return mark_safe(
        f'<div class="h-1.5 w-full rounded-full" style="background:{GRID}">'
        f'<div class="h-full rounded-full" style="width:{pct:.1f}%;background:{color}"></div></div>'
    )
