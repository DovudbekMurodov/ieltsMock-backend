"""Public v1 API routes."""

from django.urls import include, path

from apps.analytics import views as analytics_views
from apps.content import views as content_views
from apps.speaking import session_views as speaking_sessions
from apps.speaking import views as speaking_views
from apps.vocabulary import review_views as srs_views
from apps.vocabulary import views as vocabulary_views
from apps.writing import submission_views as writing_submissions
from apps.writing import views as writing_views

app_name = "api"

urlpatterns = [
    path("auth/", include("config.auth_urls")),
    path("attempts/", include("config.attempt_urls")),
    path("events/", analytics_views.record_event, name="event-record"),
    path("tests/", content_views.test_list, name="test-list"),
    path("tests/<slug:slug>/", content_views.test_detail, name="test-detail"),
    path("writing/", writing_views.task_list, name="writing-list"),
    path("writing/submissions/", writing_submissions.start, name="writing-start"),
    path("writing/submissions/mine/", writing_submissions.mine, name="writing-mine"),
    path("writing/submissions/<int:pk>/", writing_submissions.save, name="writing-save"),
    path(
        "writing/submissions/<int:pk>/submit/",
        writing_submissions.submit,
        name="writing-submit",
    ),
    path(
        "writing/submissions/<int:pk>/model-answer/",
        writing_submissions.model_answer,
        name="writing-model-answer",
    ),
    path("writing/<slug:slug>/", writing_views.task_detail, name="writing-detail"),
    path("speaking/", speaking_views.topic_list, name="speaking-list"),
    path("speaking/sessions/", speaking_sessions.start, name="speaking-session-start"),
    path("speaking/sessions/mine/", speaking_sessions.mine, name="speaking-session-mine"),
    path(
        "speaking/sessions/<int:pk>/", speaking_sessions.update, name="speaking-session-update"
    ),
    path("speaking/<slug:slug>/", speaking_views.topic_detail, name="speaking-detail"),
    path("vocabulary/", vocabulary_views.section_list, name="vocabulary-list"),
    path("vocabulary/srs/due/", srs_views.due_queue, name="srs-due"),
    path("vocabulary/srs/rate/", srs_views.rate, name="srs-rate"),
    path("vocabulary/srs/import/", srs_views.import_state, name="srs-import"),
    path("vocabulary/<slug:slug>/", vocabulary_views.section_detail, name="vocabulary-detail"),
]
