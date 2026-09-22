from django.contrib import admin

from .models import DailyMetric, Event, QuestionStat, TestStat, UserProgress


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "skill", "object_type", "object_id", "occurred_at")
    list_filter = ("name", "skill", "ua_family")
    search_fields = ("name", "user__email")
    date_hierarchy = "occurred_at"
    readonly_fields = [f.name for f in Event._meta.fields]


@admin.register(DailyMetric)
class DailyMetricAdmin(admin.ModelAdmin):
    list_display = ("date", "metric_key", "dimension_key", "value_int", "value_dec")
    list_filter = ("metric_key",)
    date_hierarchy = "date"


@admin.register(TestStat)
class TestStatAdmin(admin.ModelAdmin):
    list_display = ("test", "date", "attempts", "completions", "avg_percent", "avg_band")
    list_filter = ("test__skill",)
    date_hierarchy = "date"


@admin.register(QuestionStat)
class QuestionStatAdmin(admin.ModelAdmin):
    list_display = ("question", "date", "seen", "correct", "accuracy")
    date_hierarchy = "date"


@admin.register(UserProgress)
class UserProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "skill", "attempts", "best_band", "latest_band", "last_active_at")
    list_filter = ("skill",)
