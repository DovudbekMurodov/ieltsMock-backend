from django.contrib import admin

from apps.common.caching import bump_content_version

from .models import VocabularySection, VocabularyWord
from .publishing import publish_section


class VocabularyWordInline(admin.TabularInline):
    model = VocabularyWord
    extra = 0
    fields = ("order", "headword", "pos", "definition", "example")


@admin.register(VocabularySection)
class VocabularySectionAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "order", "status", "word_count")
    list_filter = ("status",)
    prepopulated_fields = {"slug": ("title",)}
    inlines = [VocabularyWordInline]
    actions = ["publish"]

    @admin.action(description="Publish — rebuild the public payload")
    def publish(self, request, queryset):
        for section in queryset:
            publish_section(section)
        bump_content_version()
        self.message_user(request, f"Published {queryset.count()} section(s).")

    @admin.display(description="Words")
    def word_count(self, obj):
        return obj.words.count()


@admin.register(VocabularyWord)
class VocabularyWordAdmin(admin.ModelAdmin):
    list_display = ("headword", "pos", "section", "definition")
    list_filter = ("pos", "section")
    search_fields = ("headword", "definition", "example")
