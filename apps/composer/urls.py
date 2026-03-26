from django.urls import path

from . import views

app_name = "composer"

urlpatterns = [
    # Create landing page
    path("create/", views.create_landing, name="create_landing"),
    # Idea CRUD (HTMX endpoints)
    path("ideas/create/", views.idea_create, name="idea_create"),
    path("ideas/<uuid:idea_id>/edit/", views.idea_edit, name="idea_edit"),
    path("ideas/<uuid:idea_id>/delete/", views.idea_delete, name="idea_delete"),
    path("ideas/<uuid:idea_id>/move/", views.idea_move, name="idea_move"),
    path("ideas/board/", views.idea_board, name="idea_board"),
    # Composer page
    path("compose/", views.compose, name="compose"),
    path("compose/<uuid:post_id>/", views.compose, name="compose_edit"),
    # Save actions
    path("compose/save/", views.save_post, name="save_post"),
    path("compose/<uuid:post_id>/save/", views.save_post, name="save_post_edit"),
    # Auto-save
    path("compose/autosave/", views.autosave, name="autosave"),
    path("compose/<uuid:post_id>/autosave/", views.autosave, name="autosave_edit"),
    # Live preview
    path("compose/preview/", views.preview, name="preview"),
    # Media
    path("compose/media-picker/", views.media_picker, name="media_picker"),
    path("compose/<uuid:post_id>/attach-media/", views.attach_media, name="attach_media"),
    path("compose/upload-media/", views.upload_media, name="upload_media"),
    path("compose/<uuid:post_id>/upload-media/", views.upload_media, name="upload_media_post"),
    path("compose/<uuid:post_id>/remove-media/<uuid:media_id>/", views.remove_media, name="remove_media"),
    # Drafts
    path("drafts/", views.drafts_list, name="drafts_list"),
    # Content Categories
    path("categories/", views.category_list, name="category_list"),
    path("categories/create/", views.category_create, name="category_create"),
    path("categories/<uuid:category_id>/edit/", views.category_edit, name="category_edit"),
    path("categories/<uuid:category_id>/delete/", views.category_delete, name="category_delete"),
    # Post Templates
    path("templates/", views.template_list, name="template_list"),
    path("templates/<uuid:template_id>/delete/", views.template_delete, name="template_delete"),
    path("templates/<uuid:template_id>/use/", views.use_template, name="use_template"),
    path("templates/picker/", views.template_picker, name="template_picker"),
    path("compose/<uuid:post_id>/save-as-template/", views.save_as_template, name="save_as_template"),
    # CSV Import
    path("import/csv/", views.csv_upload, name="csv_upload"),
    path("import/csv/preview/", views.csv_preview, name="csv_preview"),
    path("import/csv/confirm/", views.csv_confirm_import, name="csv_confirm_import"),
]
