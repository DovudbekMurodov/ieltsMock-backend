from django.contrib import admin

from .models import AttemptAnswer, TestAttempt


class AttemptAnswerInline(admin.TabularInline):
    model = AttemptAnswer
    extra = 0
    fields = ("question_number", "question_type", "raw_value", "normalized_value", "is_correct")
    readonly_fields = fields
    can_delete = False


@admin.register(TestAttempt)
class TestAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id", "test", "who", "status", "raw_score", "raw_total", "band", "submitted_at",
    )
    list_filter = ("status", "test__skill", "band_confidence")
    search_fields = ("user__email", "test__slug", "token")
    date_hierarchy = "started_at"
    readonly_fields = ("token", "started_at", "expires_at", "submitted_at", "duration_seconds")
    inlines = [AttemptAnswerInline]

    @admin.display(description="Who")
    def who(self, obj):
        return obj.user.email if obj.user else f"guest {str(obj.guest_id)[:8]}"
