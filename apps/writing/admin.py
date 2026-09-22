from django.contrib import admin

from .models import WritingModelAnswer, WritingTask


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
