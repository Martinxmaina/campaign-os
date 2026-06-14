"""ModelForms for the CRM CRUD surface (Organizations + Contacts).

Plain Django ModelForms — the canonical CRM lives in Django, so these write
straight to ``apps.crm`` models with no agent-service round-trip. Widget classes
match the BrightBean form styling used across the credentials/console surfaces.
"""
from __future__ import annotations

from django import forms

from apps.crm.models import Contact, Organization

_INPUT = "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-stone-500 focus:outline-none focus:ring-1 focus:ring-stone-500"
_SELECT = _INPUT
_TEXTAREA = _INPUT + " font-normal"


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "type", "tier", "website", "linkedin_url", "wiki_slug", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT}),
            "type": forms.Select(attrs={"class": _SELECT}),
            "tier": forms.Select(attrs={"class": _SELECT}),
            "website": forms.URLInput(attrs={"class": _INPUT}),
            "linkedin_url": forms.URLInput(attrs={"class": _INPUT}),
            "wiki_slug": forms.TextInput(attrs={"class": _INPUT}),
            "notes": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 3}),
        }


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = [
            "org", "full_name", "role", "seniority", "email",
            "linkedin_url", "phone", "warmth_source",
        ]
        widgets = {
            "org": forms.Select(attrs={"class": _SELECT}),
            "full_name": forms.TextInput(attrs={"class": _INPUT}),
            "role": forms.TextInput(attrs={"class": _INPUT}),
            "seniority": forms.Select(attrs={"class": _SELECT}),
            "email": forms.EmailInput(attrs={"class": _INPUT}),
            "linkedin_url": forms.URLInput(attrs={"class": _INPUT}),
            "phone": forms.TextInput(attrs={"class": _INPUT}),
            "warmth_source": forms.TextInput(attrs={"class": _INPUT}),
        }
