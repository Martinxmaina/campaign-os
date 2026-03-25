from django.urls import path

from . import views

app_name = "composer"

urlpatterns = [
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
]
