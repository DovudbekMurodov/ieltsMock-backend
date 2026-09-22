from django.contrib import admin

from .models import BandScale, BandScaleRow


class BandScaleRowInline(admin.TabularInline):
    model = BandScaleRow
    extra = 0
    fields = ("raw_min", "raw_max", "band")


@admin.register(BandScale)
class BandScaleAdmin(admin.ModelAdmin):
    list_display = ("name", "skill", "raw_total", "is_default", "min_questions_for_confidence")
    list_filter = ("skill", "is_default")
    inlines = [BandScaleRowInline]
