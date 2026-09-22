from django.contrib import admin

from .models import SpeakingCueCard, SpeakingItem, SpeakingTopic


class SpeakingCueCardInline(admin.StackedInline):
    model = SpeakingCueCard
    extra = 0


class SpeakingItemInline(admin.TabularInline):
    model = SpeakingItem
    extra = 0
    fields = ("part", "kind", "order", "text")


@admin.register(SpeakingTopic)
class SpeakingTopicAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "order", "status")
    list_filter = ("status",)
    prepopulated_fields = {"slug": ("title",)}
    inlines = [SpeakingCueCardInline, SpeakingItemInline]
