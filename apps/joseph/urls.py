from django.urls import path

from . import views

app_name = "joseph"

urlpatterns = [
    path("voice/", views.voice_editor, name="voice"),
    path("voice/save/", views.voice_save, name="voice-save"),
    # proposal_id is a UUID string in agent-service (VoiceProposal.id); str (not int)
    # so the real apply/dismiss links reverse and route to the backend correctly.
    path("voice/proposals/<str:proposal_id>/apply/", views.voice_apply_proposal, name="voice-apply-proposal"),
    path("voice/proposals/<str:proposal_id>/dismiss/", views.voice_dismiss_proposal, name="voice-dismiss-proposal"),
]
