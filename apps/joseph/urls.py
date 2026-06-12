from django.urls import path

from . import views

app_name = "joseph"

urlpatterns = [
    path("voice/", views.voice_editor, name="voice"),
    path("voice/save/", views.voice_save, name="voice-save"),
    path("voice/proposals/<int:proposal_id>/apply/", views.voice_apply_proposal, name="voice-apply-proposal"),
    path("voice/proposals/<int:proposal_id>/dismiss/", views.voice_dismiss_proposal, name="voice-dismiss-proposal"),
]
