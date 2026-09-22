from django.contrib import admin

from .models import SpeakingCueCard, SpeakingItem, SpeakingSession, SpeakingTopic


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


@admin.register(SpeakingSession)
class SpeakingSessionAdmin(admin.ModelAdmin):
    list_display = ("topic", "who", "parts_completed", "speak_used_seconds", "completed_at")
    list_filter = ("topic",)
    search_fields = ("user__email", "topic__slug")
    date_hierarchy = "created_at"
    readonly_fields = ("token",)

    @admin.display(description="Who")
    def who(self, obj):
        return obj.user.email if obj.user else f"guest {str(obj.guest_id)[:8]}"
