from django.urls import path

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

    path("writing/", views.writing_list, name="writing-list"),
    path("speaking/", views.speaking_list, name="speaking-list"),
    path("vocabulary/", views.vocabulary_list, name="vocabulary-list"),
    path("vocabulary/<slug:slug>/", views.vocabulary_detail, name="vocabulary-detail"),

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
]
