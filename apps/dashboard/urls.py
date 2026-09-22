from django.urls import path

from . import audio_views as av
from . import content_editors as ce
from . import editor, views

app_name = "dashboard"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("", views.overview, name="overview"),

    path("tests/", views.test_list, name="test-list"),
    path("listening/", views.listening_list, name="listening-list"),
    path("tests/new/", editor.test_create, name="test-create"),
    path("tests/<int:pk>/", editor.test_edit, name="test-edit"),
    path("tests/<int:pk>/preview/", editor.test_preview, name="test-preview"),
    path("tests/<int:pk>/publish/", editor.test_publish, name="test-publish"),
    path("tests/<int:pk>/unpublish/", editor.test_unpublish, name="test-unpublish"),

    path("audio/", av.audio_library, name="audio-library"),
    path("audio/upload/", av.audio_upload, name="audio-upload"),
    path("audio/<int:pk>/delete/", av.audio_delete, name="audio-delete"),

    path("writing/", views.writing_list, name="writing-list"),
    path("writing/new/", ce.writing_create, name="writing-create"),
    path("writing/<slug:slug>/", ce.writing_edit, name="writing-edit"),

    path("speaking/", views.speaking_list, name="speaking-list"),
    path("speaking/new/", ce.speaking_create, name="speaking-create"),
    path("speaking/<slug:slug>/", ce.speaking_edit, name="speaking-edit"),

    path("vocabulary/", views.vocabulary_list, name="vocabulary-list"),
    path("vocabulary/new/", ce.vocabulary_create, name="vocabulary-create"),
    path("vocabulary/<slug:slug>/", ce.vocabulary_edit, name="vocabulary-edit"),
    path(
        "vocabulary/<slug:slug>/publish/", ce.vocabulary_publish, name="vocabulary-publish"
    ),

    path("students/", views.user_list, name="user-list"),
    path("students/<int:pk>/", views.user_detail, name="user-detail"),
    path("attempts/", views.attempt_list, name="attempt-list"),
    path("attempts/<int:pk>/", views.attempt_detail, name="attempt-detail"),

    path("band-scales/", views.band_scale_list, name="band-scale-list"),
    path("band-scales/<int:pk>/rows/", views.band_scale_row_update, name="band-scale-rows"),

    # Fragment endpoints live under /hx/ so it is obvious at a glance which
    # URLs return partials rather than pages.
    path("hx/tests/<int:pk>/meta/", editor.test_meta_save, name="hx-test-meta"),
    path("hx/sections/<int:pk>/blocks/bulk/", editor.section_bulk_blocks, name="hx-bulk-blocks"),
    path("hx/blocks/<int:pk>/", editor.block_detail, name="hx-block"),
    path("hx/sections/<int:pk>/groups/", editor.group_create, name="hx-group-create"),
    path("hx/groups/<int:pk>/", editor.group_detail, name="hx-group"),
    path("hx/groups/<int:pk>/questions/", editor.question_create, name="hx-question-create"),
    path("hx/groups/<int:pk>/options/", editor.pool_option_create, name="hx-pool-option-create"),
    path("hx/questions/<int:pk>/", editor.question_detail, name="hx-question"),
    path("hx/questions/<int:pk>/answer/", editor.answer_set, name="hx-answer-set"),
    path("hx/questions/<int:pk>/keys/", editor.answer_key_add, name="hx-key-add"),
    path("hx/keys/<int:pk>/", editor.answer_key_delete, name="hx-key-delete"),
    path("hx/options/<int:pk>/", editor.option_save, name="hx-option"),
    path("hx/options/<int:pk>/delete/", editor.pool_option_delete, name="hx-pool-option-delete"),
    path("hx/reorder/<str:model>/<int:pk>/", editor.reorder, name="hx-reorder"),
    path("hx/sections/<int:pk>/audio/", av.section_audio_attach, name="hx-section-audio"),
    path(
        "hx/sections/<int:pk>/transcript/",
        av.section_transcript_visibility,
        name="hx-section-transcript",
    ),

    path("hx/vocabulary/<slug:slug>/meta/", ce.vocabulary_meta_save, name="hx-vocab-meta"),
    path("hx/vocabulary/<slug:slug>/words/", ce.word_create, name="hx-word-create"),
    path("hx/vocabulary/<slug:slug>/import/", ce.word_bulk_import, name="hx-word-import"),
    path("hx/words/<int:pk>/", ce.word_detail, name="hx-word"),

    path("hx/writing/<slug:slug>/meta/", ce.writing_save, name="hx-writing-meta"),
    path(
        "hx/writing/<slug:slug>/answers/",
        ce.writing_answer_create,
        name="hx-writing-answer-create",
    ),
    path("hx/writing-answers/<int:pk>/", ce.writing_answer_detail, name="hx-writing-answer"),

    path("hx/speaking/<slug:slug>/meta/", ce.speaking_save, name="hx-speaking-meta"),
    path("hx/speaking/<slug:slug>/cue/", ce.speaking_cue_save, name="hx-speaking-cue"),
    path(
        "hx/speaking/<slug:slug>/items/<int:part>/<str:kind>/",
        ce.speaking_item_create,
        name="hx-speaking-item-create",
    ),
    path("hx/speaking-items/<int:pk>/", ce.speaking_item_detail, name="hx-speaking-item"),
]
