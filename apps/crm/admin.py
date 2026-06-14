from django.contrib import admin

from apps.crm.models import Activity, Contact, Organization, OutreachThread, Task


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "tier", "created_at")
    list_filter = ("type", "tier")
    search_fields = ("name",)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("full_name", "org", "role", "seniority", "email")
    list_filter = ("seniority",)
    search_fields = ("full_name", "email")
    raw_id_fields = ("org",)


@admin.register(OutreachThread)
class OutreachThreadAdmin(admin.ModelAdmin):
    list_display = ("org", "primary_contact", "stage", "owner", "quintile", "traffic_light", "score")
    list_filter = ("stage", "traffic_light", "track")
    search_fields = ("org__name", "agent_thread_id", "dossier_id")
    raw_id_fields = ("org", "primary_contact", "owner", "backstop")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("thread", "activity_type", "actor_type", "actor", "agent_name", "created_at")
    list_filter = ("activity_type", "actor_type")
    raw_id_fields = ("thread", "actor")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("type", "thread", "owner", "status", "due", "created_at")
    list_filter = ("status", "type")
    raw_id_fields = ("thread", "owner")
