"""Views for the Content Calendar (F-2.3)."""

import calendar as cal_mod
import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.composer.models import Post
from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

from .models import PostingSlot


def _get_workspace(request, workspace_id):
    """Resolve workspace and enforce membership check."""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    has_membership = WorkspaceMembership.objects.filter(
        user=request.user,
        workspace=workspace,
    ).exists()
    if not has_membership:
        raise PermissionDenied("You are not a member of this workspace.")
    return workspace


def _parse_date(date_str, default=None):
    """Parse a YYYY-MM-DD date string."""
    if date_str:
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass
    return default or date.today()


def _get_filtered_posts(workspace, request):
    """Apply calendar filters from query params."""
    qs = (
        Post.objects.for_workspace(workspace.id)
        .select_related("author")
        .prefetch_related("platform_posts__social_account", "media_attachments__media_asset")
    )

    # Status filter
    statuses = request.GET.getlist("status")
    if statuses:
        qs = qs.filter(status__in=statuses)

    # Platform filter
    platforms = request.GET.getlist("platform")
    if platforms:
        qs = qs.filter(platform_posts__social_account__platform__in=platforms).distinct()

    # Author filter
    authors = request.GET.getlist("author")
    if authors:
        qs = qs.filter(author_id__in=authors)

    # Date range
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    if start_date:
        qs = qs.filter(scheduled_at__date__gte=_parse_date(start_date))
    if end_date:
        qs = qs.filter(scheduled_at__date__lte=_parse_date(end_date))

    return qs


@login_required
def calendar_view(request, workspace_id):
    """Main calendar page — renders the appropriate view (month/week/day/list)."""
    workspace = _get_workspace(request, workspace_id)
    view_type = request.GET.get("view", "month")
    target_date = _parse_date(request.GET.get("date"))

    # Connected accounts for filter UI
    social_accounts = SocialAccount.objects.for_workspace(workspace.id).filter(
        status=SocialAccount.Status.CONNECTED,
    ).order_by("platform")

    # Authors for filter
    from django.contrib.auth import get_user_model
    user_model = get_user_model()
    authors = user_model.objects.filter(
        authored_posts__workspace=workspace,
    ).distinct().values("id", "name", "email")

    # Active filters
    active_filters = {
        "statuses": request.GET.getlist("status"),
        "platforms": request.GET.getlist("platform"),
        "authors": request.GET.getlist("author"),
    }

    context = {
        "workspace": workspace,
        "view_type": view_type,
        "target_date": target_date,
        "social_accounts": social_accounts,
        "authors": authors,
        "active_filters": active_filters,
        "status_choices": Post.Status.choices,
    }

    if request.htmx:
        # HTMX request — return just the calendar grid partial
        return _render_calendar_partial(request, workspace, view_type, target_date, context)

    return render(request, "calendar/calendar.html", context)


def _render_calendar_partial(request, workspace, view_type, target_date, context):
    """Render the appropriate calendar partial based on view type."""
    if view_type == "month":
        return _month_view(request, workspace, target_date, context)
    elif view_type == "week":
        return _week_view(request, workspace, target_date, context)
    elif view_type == "day":
        return _day_view(request, workspace, target_date, context)
    elif view_type == "list":
        return _list_view(request, workspace, target_date, context)
    return _month_view(request, workspace, target_date, context)


def _month_view(request, workspace, target_date, context):
    """Render month view calendar grid."""
    year, month = target_date.year, target_date.month
    cal = cal_mod.Calendar(firstweekday=0)  # Monday first
    weeks = cal.monthdatescalendar(year, month)

    # Get all posts for this month range
    first_day = weeks[0][0]
    last_day = weeks[-1][6]
    posts = _get_filtered_posts(workspace, request).filter(
        scheduled_at__date__gte=first_day,
        scheduled_at__date__lte=last_day,
    ).order_by("scheduled_at")

    # Also include drafts without scheduled_at for the current month
    drafts = _get_filtered_posts(workspace, request).filter(
        status="draft",
        scheduled_at__isnull=True,
    ).order_by("-updated_at")[:10]

    # Group posts by date
    posts_by_date = defaultdict(list)
    for post in posts:
        if post.scheduled_at:
            posts_by_date[post.scheduled_at.date()].append(post)

    # Build weeks data
    calendar_weeks = []
    for week in weeks:
        week_data = []
        for day in week:
            day_posts = posts_by_date.get(day, [])
            week_data.append({
                "date": day,
                "is_current_month": day.month == month,
                "is_today": day == date.today(),
                "posts": day_posts[:3],
                "total_posts": len(day_posts),
                "overflow": max(0, len(day_posts) - 3),
            })
        calendar_weeks.append(week_data)

    # Navigation
    prev_month = (date(year, month, 1) - timedelta(days=1)).replace(day=1)
    next_month = (date(year, month, 28) + timedelta(days=4)).replace(day=1)

    context.update({
        "calendar_weeks": calendar_weeks,
        "month_name": date(year, month, 1).strftime("%B %Y"),
        "prev_month": prev_month.isoformat(),
        "next_month": next_month.isoformat(),
        "unscheduled_drafts": drafts,
        "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    })

    template = "calendar/partials/month_grid.html" if request.htmx else "calendar/calendar.html"
    return render(request, template, context)


def _week_view(request, workspace, target_date, context):
    """Render week view with hourly rows."""
    # Find Monday of the target week
    monday = target_date - timedelta(days=target_date.weekday())
    week_days = [monday + timedelta(days=i) for i in range(7)]

    posts = _get_filtered_posts(workspace, request).filter(
        scheduled_at__date__gte=week_days[0],
        scheduled_at__date__lte=week_days[6],
    ).order_by("scheduled_at")

    # Group posts by (date, hour)
    posts_by_slot = defaultdict(list)
    for post in posts:
        if post.scheduled_at:
            local_dt = post.scheduled_at
            key = (local_dt.date(), local_dt.hour)
            posts_by_slot[key].append(post)

    hours = list(range(6, 23))  # 6 AM to 10 PM

    context.update({
        "week_days": week_days,
        "hours": hours,
        "posts_by_slot": dict(posts_by_slot),
        "prev_week": (monday - timedelta(weeks=1)).isoformat(),
        "next_week": (monday + timedelta(weeks=1)).isoformat(),
        "week_label": f"{week_days[0].strftime('%b %d')} – {week_days[6].strftime('%b %d, %Y')}",
    })

    template = "calendar/partials/week_grid.html" if request.htmx else "calendar/calendar.html"
    return render(request, template, context)


def _day_view(request, workspace, target_date, context):
    """Render day view with detailed hour timeline."""
    posts = _get_filtered_posts(workspace, request).filter(
        scheduled_at__date=target_date,
    ).order_by("scheduled_at")

    posts_by_hour = defaultdict(list)
    for post in posts:
        if post.scheduled_at:
            posts_by_hour[post.scheduled_at.hour].append(post)

    hours = list(range(0, 24))

    context.update({
        "posts_by_hour": dict(posts_by_hour),
        "hours": hours,
        "prev_day": (target_date - timedelta(days=1)).isoformat(),
        "next_day": (target_date + timedelta(days=1)).isoformat(),
        "day_label": target_date.strftime("%A, %B %d, %Y"),
    })

    template = "calendar/partials/day_grid.html" if request.htmx else "calendar/calendar.html"
    return render(request, template, context)


def _list_view(request, workspace, target_date, context):
    """Render list/table view of posts."""
    posts = _get_filtered_posts(workspace, request).order_by("-scheduled_at", "-created_at")[:200]

    context.update({
        "posts": posts,
    })

    template = "calendar/partials/list_view.html" if request.htmx else "calendar/calendar.html"
    return render(request, template, context)


@login_required
@require_POST
def reschedule_post(request, workspace_id):
    """HTMX endpoint for drag-and-drop rescheduling."""
    workspace = _get_workspace(request, workspace_id)
    post_id = request.POST.get("post_id")
    new_datetime_str = request.POST.get("new_datetime")

    if not post_id or not new_datetime_str:
        return JsonResponse({"error": "post_id and new_datetime required"}, status=400)

    post = get_object_or_404(Post, id=post_id, workspace=workspace)

    # Check permissions — only editable statuses can be rescheduled
    if post.status not in ("draft", "approved", "scheduled"):
        return JsonResponse({"error": "Post cannot be rescheduled in its current status."}, status=400)

    # Check RBAC
    membership = request.workspace_membership
    perms = membership.effective_permissions if membership else {}
    is_own_post = post.author_id == request.user.id
    can_edit = (is_own_post and perms.get("edit_own_posts")) or perms.get("edit_others_posts")
    if not can_edit:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        import zoneinfo
        ws_tz = workspace.effective_timezone or "UTC"
        tz = zoneinfo.ZoneInfo(ws_tz)
        new_dt = datetime.fromisoformat(new_datetime_str)
        if new_dt.tzinfo is None:
            new_dt = new_dt.replace(tzinfo=tz)
        post.scheduled_at = new_dt
        if post.status == "draft":
            post.status = "scheduled"
        post.save()
    except (ValueError, TypeError) as e:
        return JsonResponse({"error": f"Invalid datetime: {e}"}, status=400)

    return HttpResponse(
        status=204,
        headers={"HX-Trigger": json.dumps({"postRescheduled": {"postId": str(post.id)}})},
    )


@login_required
def posting_slots(request, workspace_id):
    """Manage posting slots for a workspace's social accounts."""
    workspace = _get_workspace(request, workspace_id)
    accounts = SocialAccount.objects.for_workspace(workspace.id).filter(
        status=SocialAccount.Status.CONNECTED,
    )

    slots = PostingSlot.objects.filter(
        social_account__in=accounts,
    ).select_related("social_account").order_by("social_account", "day_of_week", "time")

    # Group by account
    slots_by_account = defaultdict(list)
    for slot in slots:
        slots_by_account[slot.social_account_id].append(slot)

    context = {
        "workspace": workspace,
        "accounts": accounts,
        "slots_by_account": dict(slots_by_account),
        "day_choices": PostingSlot.DayOfWeek.choices,
    }
    return render(request, "calendar/posting_slots.html", context)


@login_required
@require_POST
def save_posting_slot(request, workspace_id):
    """Create or update a posting slot."""
    workspace = _get_workspace(request, workspace_id)
    account_id = request.POST.get("social_account_id")
    day = request.POST.get("day_of_week")
    time_str = request.POST.get("time")

    if not all([account_id, day, time_str]):
        return JsonResponse({"error": "All fields required."}, status=400)

    account = get_object_or_404(
        SocialAccount, id=account_id, workspace=workspace,
    )

    from datetime import time
    try:
        slot_time = time.fromisoformat(time_str)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid time format."}, status=400)

    slot, created = PostingSlot.objects.get_or_create(
        social_account=account,
        day_of_week=int(day),
        time=slot_time,
        defaults={"is_active": True},
    )

    if request.htmx:
        return HttpResponse(status=204, headers={"HX-Trigger": "slotsUpdated"})
    return JsonResponse({"id": str(slot.id), "created": created})


@login_required
@require_POST
def delete_posting_slot(request, workspace_id, slot_id):
    """Delete a posting slot."""
    workspace = _get_workspace(request, workspace_id)
    slot = get_object_or_404(PostingSlot, id=slot_id)
    # Verify the slot belongs to this workspace
    if slot.social_account.workspace_id != workspace.id:
        return JsonResponse({"error": "Not found."}, status=404)
    slot.delete()

    if request.htmx:
        return HttpResponse(status=204, headers={"HX-Trigger": "slotsUpdated"})
    return JsonResponse({"deleted": True})
