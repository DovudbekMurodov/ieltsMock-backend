from django.contrib import admin

from .models import WritingFeedback, WritingModelAnswer, WritingSubmission, WritingTask


class WritingModelAnswerInline(admin.StackedInline):
    model = WritingModelAnswer
    extra = 0
    fields = ("order", "band", "body")


@admin.register(WritingTask)
class WritingTaskAdmin(admin.ModelAdmin):
    list_display = ("slug", "task_number", "type", "target_words", "status")
    list_filter = ("task_number", "type", "status")
    search_fields = ("slug", "prompt")
    prepopulated_fields = {"slug": ("prompt",)}
    inlines = [WritingModelAnswerInline]


@admin.register(WritingSubmission)
class WritingSubmissionAdmin(admin.ModelAdmin):
    list_display = ("task", "who", "status", "word_count", "submitted_at")
    list_filter = ("status", "task__type")
    search_fields = ("user__email", "task__slug")
    date_hierarchy = "created_at"
    readonly_fields = ("token", "word_count", "submitted_at")

    @admin.display(description="Who")
    def who(self, obj):
        return obj.user.email if obj.user else f"guest {str(obj.guest_id)[:8]}"


@admin.register(WritingFeedback)
class WritingFeedbackAdmin(admin.ModelAdmin):
    list_display = ("submission", "overall", "grader", "created_at")
    readonly_fields = ("overall",)
