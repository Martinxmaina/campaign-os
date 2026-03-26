from django.urls import path

from . import views

app_name = "calendar"

urlpatterns = [
    # Main calendar view
    path("", views.calendar_view, name="calendar"),
    # Drag-and-drop reschedule
    path("reschedule/", views.reschedule_post, name="reschedule"),
    # Posting slots
    path("posting-slots/", views.posting_slots, name="posting_slots"),
    path("posting-slots/save/", views.save_posting_slot, name="save_posting_slot"),
    path("posting-slots/<uuid:slot_id>/delete/", views.delete_posting_slot, name="delete_posting_slot"),
    # Queues
    path("queues/", views.queue_list, name="queue_list"),
    path("queues/create/", views.queue_create, name="queue_create"),
    path("queues/<uuid:queue_id>/", views.queue_detail, name="queue_detail"),
    path("queues/<uuid:queue_id>/delete/", views.queue_delete, name="queue_delete"),
    path("queues/<uuid:queue_id>/reorder/", views.queue_reorder, name="queue_reorder"),
    # Custom Calendar Events
    path("events/create/", views.event_create, name="event_create"),
    path("events/<uuid:event_id>/edit/", views.event_edit, name="event_edit"),
    path("events/<uuid:event_id>/delete/", views.event_delete, name="event_delete"),
]
