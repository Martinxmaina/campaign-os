from django.contrib import admin

from apps.outreach.models import Mailbox, MailboxSend, SuppressionEntry


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
