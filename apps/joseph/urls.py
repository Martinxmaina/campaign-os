from django.urls import path

from . import views

app_name = "joseph"

urlpatterns = [
    path("", views.home, name="home"),
    # Dossier brief card — L0 editorial card + L1/L2 HTMX tier toggle + refresh.
    # thread_id is the agent-service thread id (a string), not a Django pk.
    path("brief/<str:thread_id>/", views.brief, name="brief"),
    path("brief/<str:thread_id>/refresh/", views.brief_refresh, name="brief-refresh"),
    # Deal-flow kanban — threads grouped into stage columns; cards link to the
    # thread drawer (/joseph/thread/<id>/).
    path("pipeline/", views.pipeline, name="pipeline"),
    # Thread drawer — full operational view of one deal thread: header (org +
    # stage + score) + actions + six HTMX tabs (?tab=brief|timeline|intelligence
    # |tasks|deck|sequence). thread_id is the agent-service thread id (a string).
    path("thread/<str:thread_id>/", views.thread_drawer, name="thread"),
    path("thread/<str:thread_id>/escalate/", views.thread_escalate, name="thread-escalate"),
    path("voice/", views.voice_editor, name="voice"),
    path("voice/save/", views.voice_save, name="voice-save"),
    # proposal_id is a UUID string in agent-service (VoiceProposal.id); str (not int)
    # so the real apply/dismiss links reverse and route to the backend correctly.
    path("voice/proposals/<str:proposal_id>/apply/", views.voice_apply_proposal, name="voice-apply-proposal"),
    path("voice/proposals/<str:proposal_id>/dismiss/", views.voice_dismiss_proposal, name="voice-dismiss-proposal"),
]
