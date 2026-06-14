"""CRM CRUD views — Organizations + Contacts (list / detail / create / edit).

The canonical CRM lives in Django (``apps/crm``), so these views are pure Django
querysets — agent-service is NEVER called from this surface (the Joseph pipeline
still talks to agent-service for dossiers; the org/contact book does not).

Every view is gated by ``_can_manage_crm`` (staff or an owner/admin/campaign_owner
workspace role), reused from the import wizard (Task 6). Templates extend
``base.html`` (BrightBean skin) and match the credentials/console list styling.
CSP-safe: no inline ``onclick``/``onsubmit`` — plain anchors + ``hx-*`` + Alpine.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from apps.crm.forms import ContactForm, OrganizationForm
from apps.crm.models import Contact, Organization
from apps.crm.views_import import _can_manage_crm


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------


@login_required
def org_list(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    q = (request.GET.get("q") or "").strip()
    tier = (request.GET.get("tier") or "").strip()
    type_ = (request.GET.get("type") or "").strip()

    orgs = Organization.objects.annotate(contact_count=Count("contacts", distinct=True),
                                          thread_count=Count("threads", distinct=True))
    if q:
        orgs = orgs.filter(name__icontains=q)
    if tier:
        orgs = orgs.filter(tier=tier)
    if type_:
        orgs = orgs.filter(type=type_)
    orgs = orgs.order_by("name")

    return render(
        request,
        "crm/org_list.html",
        {
            "orgs": orgs,
            "q": q,
            "tier": tier,
            "type": type_,
            "tier_choices": Organization.Tier.choices,
            "type_choices": Organization.Type.choices,
        },
    )


@login_required
def org_new(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    if request.method == "POST":
        form = OrganizationForm(request.POST)
        if form.is_valid():
            org = form.save()
            return redirect("crm:org-detail", org_id=org.id)
    else:
        form = OrganizationForm()
    return render(request, "crm/org_form.html", {"form": form, "is_new": True})


@login_required
def org_detail(request, org_id):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    org = get_object_or_404(Organization, id=org_id)
    contacts = org.contacts.order_by("full_name")
    threads = org.threads.select_related("primary_contact", "owner").order_by("-updated_at")
    return render(
        request,
        "crm/org_detail.html",
        {"org": org, "contacts": contacts, "threads": threads},
    )


@login_required
def org_edit(request, org_id):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    org = get_object_or_404(Organization, id=org_id)
    if request.method == "POST":
        form = OrganizationForm(request.POST, instance=org)
        if form.is_valid():
            form.save()
            return redirect("crm:org-detail", org_id=org.id)
    else:
        form = OrganizationForm(instance=org)
    return render(request, "crm/org_form.html", {"form": form, "org": org, "is_new": False})


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@login_required
def contact_list(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    q = (request.GET.get("q") or "").strip()
    org_id = (request.GET.get("org") or "").strip()
    seniority = (request.GET.get("seniority") or "").strip()

    contacts = Contact.objects.select_related("org")
    if q:
        contacts = contacts.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    if org_id:
        contacts = contacts.filter(org_id=org_id)
    if seniority:
        contacts = contacts.filter(seniority=seniority)
    contacts = contacts.order_by("full_name")

    return render(
        request,
        "crm/contact_list.html",
        {
            "contacts": contacts,
            "q": q,
            "org": org_id,
            "seniority": seniority,
            "orgs": Organization.objects.order_by("name"),
            "seniority_choices": Contact.Seniority.choices,
        },
    )


@login_required
def contact_new(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save()
            return redirect("crm:contact-detail", contact_id=contact.id)
    else:
        form = ContactForm(initial={"org": request.GET.get("org") or None})
    return render(request, "crm/contact_form.html", {"form": form, "is_new": True})


@login_required
def contact_detail(request, contact_id):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    contact = get_object_or_404(Contact.objects.select_related("org"), id=contact_id)
    threads = contact.threads.select_related("org", "owner").order_by("-updated_at")
    return render(
        request,
        "crm/contact_detail.html",
        {"contact": contact, "threads": threads},
    )


@login_required
def contact_edit(request, contact_id):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    contact = get_object_or_404(Contact, id=contact_id)
    if request.method == "POST":
        form = ContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            return redirect("crm:contact-detail", contact_id=contact.id)
    else:
        form = ContactForm(instance=contact)
    return render(
        request, "crm/contact_form.html", {"form": form, "contact": contact, "is_new": False}
    )
