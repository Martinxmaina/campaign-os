from django.urls import path

from . import views

app_name = "joseph"

urlpatterns = [
    path("", views.home, name="home"),
    # Notification bell poll — {count, items[]} from the unread notifications
    # feed; polled by the home/PWA bell every ~30s. JSON, gated, agent-down safe.
    path("notifications.json", views.notifications_json, name="notifications-json"),
    # Dossier brief card — L0 editorial card + L1/L2 HTMX tier toggle + refresh.
    # thread_id is the agent-service thread id (a string), not a Django pk.
    path("brief/<str:thread_id>/", views.brief, name="brief"),
    path("brief/<str:thread_id>/refresh/", views.brief_refresh, name="brief-refresh"),
    # Deal-flow kanban — threads grouped into stage columns; cards link to the
    # thread drawer (/joseph/thread/<id>/).
    path("pipeline/", views.pipeline, name="pipeline"),
    # Briefs index — the bottom-nav "Brief" destination: threads to pick from,
    # each linking to its L0 brief card (a thread-less /joseph/brief/ 404s).
    path("briefs/", views.briefs, name="briefs"),
    # Thread drawer — full operational view of one deal thread: header (org +
    # stage + score) + actions + six HTMX tabs (?tab=brief|timeline|intelligence
    # |tasks|deck|sequence). thread_id is the agent-service thread id (a string).
    path("thread/<str:thread_id>/", views.thread_drawer, name="thread"),
    path("thread/<str:thread_id>/escalate/", views.thread_escalate, name="thread-escalate"),
    # Knowledge wiki browser — search + entity_type chips; cards link to detail.
    path("knowledge/", views.knowledge, name="knowledge"),
    # Page detail — title + L0/L1/L2 tier toggle (HTMX) + outgoing links + revisions.
    # slug is the agent-service wiki page slug (a string), not a Django pk.
    path("knowledge/<str:slug>/", views.knowledge_detail, name="knowledge-detail"),
    # Personal content queue — Joseph's own/assigned Posts, newest publish-date
    # first; flagged posts show gate findings + an audited override. "Draft new"
    # links to the composer with voice_user=joseph.
    path("content/", views.content_queue, name="content"),
    # post_id is a composer Post UUID (a Django pk).
    path("content/<uuid:post_id>/override/", views.content_override, name="content-override"),
    path("voice/", views.voice_editor, name="voice"),
    path("voice/save/", views.voice_save, name="voice-save"),
    # proposal_id is a UUID string in agent-service (VoiceProposal.id); str (not int)
    # so the real apply/dismiss links reverse and route to the backend correctly.
    path("voice/proposals/<str:proposal_id>/apply/", views.voice_apply_proposal, name="voice-apply-proposal"),
    path("voice/proposals/<str:proposal_id>/dismiss/", views.voice_dismiss_proposal, name="voice-dismiss-proposal"),
]
