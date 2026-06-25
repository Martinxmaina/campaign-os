from django.urls import path

from . import review_views, views

app_name = "approvals"

urlpatterns = [
    path("approvals/", views.approval_queue, name="queue"),
    path("approvals/<uuid:post_id>/approve/", views.approve, name="approve"),
    path("approvals/<uuid:post_id>/request-changes/", views.request_changes_view, name="request_changes"),
    path("approvals/<uuid:post_id>/reject/", views.reject, name="reject"),
    path("approvals/bulk/", views.bulk_action, name="bulk_action"),
    path("approvals/<uuid:post_id>/comments/", views.add_comment, name="add_comment"),
    path("approvals/<uuid:post_id>/comments/<uuid:comment_id>/edit/", views.edit_comment, name="edit_comment"),
    path("approvals/<uuid:post_id>/comments/<uuid:comment_id>/delete/", views.delete_comment, name="delete_comment"),
    path("approvals/<uuid:post_id>/versions/", views.version_diff, name="version_diff"),
    # Public review routes (approval-by-email, Tasks 5 + 6).
    # The workspace_id segment is provided by the parent URL conf which
    # mounts this urlconf at ``workspace/<uuid:workspace_id>/``.
    # IMPORTANT: publish route must precede the generic review route so
    # ``review/publish/<token>/`` is not captured by ``review/<token>/``.
    path("review/publish/<str:token>/", review_views.publish, name="review_publish"),
    path("review/<str:token>/", review_views.review, name="review"),
]
