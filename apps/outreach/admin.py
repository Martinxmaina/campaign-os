from django.contrib import admin

from apps.outreach.models import (
    Mailbox,
    MailboxSend,
    Sequence,
    SequenceStep,
    SequenceTemplate,
    SuppressionEntry,
)


@admin.register(Mailbox)
class MailboxAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "status", "daily_cap", "ramp_started_at", "created_at")
    list_filter = ("status",)
    search_fields = ("email", "user__email")
    raw_id_fields = ("user", "google_integration")


@admin.register(MailboxSend)
class MailboxSendAdmin(admin.ModelAdmin):
    list_display = ("mailbox", "date", "count")
    list_filter = ("date",)
    search_fields = ("mailbox__email",)
    raw_id_fields = ("mailbox",)


@admin.register(SuppressionEntry)
class SuppressionEntryAdmin(admin.ModelAdmin):
    list_display = ("email", "reason", "created_at")
    list_filter = ("reason",)
    search_fields = ("email",)


@admin.register(SequenceTemplate)
class SequenceTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "template", "status", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("thread", "template")


@admin.register(SequenceStep)
class SequenceStepAdmin(admin.ModelAdmin):
    list_display = ("sequence", "position", "kind", "status", "scheduled_for")
    list_filter = ("kind", "status")
    raw_id_fields = ("sequence",)
