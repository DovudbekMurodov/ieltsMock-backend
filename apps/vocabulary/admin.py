from django.contrib import admin

from .models import VocabularySection, VocabularyWord


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

    @admin.display(description="Words")
    def word_count(self, obj):
        return obj.words.count()


@admin.register(VocabularyWord)
class VocabularyWordAdmin(admin.ModelAdmin):
    list_display = ("headword", "pos", "section", "definition")
    list_filter = ("pos", "section")
    search_fields = ("headword", "definition", "example")
