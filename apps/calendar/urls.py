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
]
