from django.contrib import admin

from apps.common.caching import bump_content_version

from .models import AnswerKey, AudioAsset, Block, Option, Question, QuestionGroup, Section, Test
from .publishing import publish_test


class BlockInline(admin.TabularInline):
    model = Block
    extra = 0
    fields = ("order", "label", "text")


class QuestionGroupInline(admin.TabularInline):
    model = QuestionGroup
    extra = 0
    fields = ("order", "type", "options_scope", "match_mode", "instructions")
    show_change_link = True


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    fields = ("order", "title", "audio", "playback_policy", "transcript_visibility")
    show_change_link = True


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0
    fields = ("order", "label", "text", "question")


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ("order", "number", "prompt")
    show_change_link = True


class AnswerKeyInline(admin.TabularInline):
    model = AnswerKey
    extra = 0
    fields = ("order", "option", "value")


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ("title", "skill", "slug", "status", "time_limit_minutes", "question_count")
    list_filter = ("skill", "status", "difficulty")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [SectionInline]
    actions = ["publish"]
    readonly_fields = ("payload_etag", "published_at")

    @admin.action(description="Publish — rebuild the public payload")
    def publish(self, request, queryset):
        for test in queryset:
            publish_test(test)
        bump_content_version()
        self.message_user(request, f"Published {queryset.count()} test(s).")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("title", "test", "order", "audio", "transcript_visibility")
    list_filter = ("test__skill", "transcript_visibility", "playback_policy")
    search_fields = ("title", "test__slug")
    inlines = [BlockInline, QuestionGroupInline]


@admin.register(QuestionGroup)
class QuestionGroupAdmin(admin.ModelAdmin):
    list_display = ("__str__", "type", "options_scope", "match_mode")
    list_filter = ("type", "options_scope")
    inlines = [OptionInline, QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("number", "test", "prompt", "type")
    list_filter = ("test__skill", "group__type")
    search_fields = ("prompt", "test__slug")
    inlines = [AnswerKeyInline]

    @admin.display(description="Type")
    def type(self, obj):
        return obj.group.get_type_display()


@admin.register(AudioAsset)
class AudioAssetAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "duration_seconds", "size_bytes", "created_at")
    search_fields = ("original_filename", "checksum_sha256")
    readonly_fields = ("checksum_sha256", "duration_ms", "size_bytes", "content_type")
