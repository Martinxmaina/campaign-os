"""Queue scheduling services for the Content Calendar (F-2.3)."""

from datetime import datetime, timedelta

from django.utils import timezone

from .models import PostingSlot, QueueEntry


def _next_slot_datetimes(social_account, after_dt, count=30):
    """Compute the next `count` PostingSlot datetimes for a social account.

    Starting from `after_dt`, walks forward through the week to find
    upcoming slot times based on the account's PostingSlot configuration.
    """
    slots = (
        PostingSlot.objects.filter(social_account=social_account, is_active=True)
        .order_by("day_of_week", "time")
    )
    if not slots.exists():
        return []

    slot_list = list(slots)
    results = []
    current_date = after_dt.date()

    # Walk up to 60 days forward to find enough slots
    for day_offset in range(60):
        check_date = current_date + timedelta(days=day_offset)
        weekday = check_date.weekday()  # 0=Monday

        for slot in slot_list:
            if slot.day_of_week != weekday:
                continue

            slot_dt = datetime.combine(check_date, slot.time)
            if after_dt.tzinfo:
                slot_dt = slot_dt.replace(tzinfo=after_dt.tzinfo)

            if slot_dt <= after_dt:
                continue

            results.append(slot_dt)
            if len(results) >= count:
                return results

    return results


def assign_queue_slots(queue):
    """Recalculate assigned_slot_datetime for all entries in a queue.

    Iterates entries in position order and assigns each to the next
    available PostingSlot datetime for the queue's social account.
    """
    entries = queue.entries.select_related("post").order_by("position")
    if not entries.exists():
        return

    now = timezone.now()
    slot_times = _next_slot_datetimes(queue.social_account, now, count=len(entries) + 10)

    for idx, entry in enumerate(entries):
        if idx < len(slot_times):
            entry.assigned_slot_datetime = slot_times[idx]
            entry.post.scheduled_at = slot_times[idx]
            if entry.post.status == "draft":
                entry.post.status = "scheduled"
            entry.post.save(update_fields=["scheduled_at", "status", "updated_at"])
        else:
            entry.assigned_slot_datetime = None
        entry.save(update_fields=["assigned_slot_datetime"])


def add_to_queue(post, queue):
    """Add a post to the end of a queue and recalculate slot assignments."""
    from django.db.models import Max

    max_pos = queue.entries.aggregate(max_pos=Max("position"))["max_pos"]
    position = (max_pos or 0) + 1

    QueueEntry.objects.update_or_create(
        queue=queue,
        post=post,
        defaults={"position": position},
    )

    assign_queue_slots(queue)


def reorder_queue(queue, ordered_entry_ids):
    """Reorder queue entries by a list of entry IDs and recalculate slots."""
    for idx, entry_id in enumerate(ordered_entry_ids):
        QueueEntry.objects.filter(id=entry_id, queue=queue).update(position=idx)

    assign_queue_slots(queue)
