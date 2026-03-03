"""
Schedule generation: which room, when, who.
Uses times_per_month to compute slots per 4-week cycle.
"""

from datetime import datetime, timedelta
from typing import List, Dict
import cinderella.database as db


def _weeks_since_epoch(d: datetime) -> int:
    """Weeks since Unix epoch (simplified)."""
    return int(d.timestamp() / (7 * 24 * 3600))


def _next_sunday(d: datetime) -> datetime:
    """Get next Sunday from d (or same day if d is Sunday)."""
    wd = d.weekday()
    if wd == 6:
        return d
    return d + timedelta(days=6 - wd)


def generate_slots_for_week(start_sunday: datetime, config: dict) -> List[Dict]:
    """
    Generate (room_id, due_date) slots for the week starting at start_sunday.
    - 4x/month -> 1 slot per week
    - 2x/month -> 1 slot every 2 weeks
    - 1x/month -> 1 slot every 4 weeks
    """
    slots = []
    rooms = db.get_rooms()
    if not rooms:
        return slots

    week_num = _weeks_since_epoch(start_sunday)
    for room in rooms:
        tpm = room["times_per_month"]
        if tpm < 1:
            continue
        # How often does this room get a slot? Every N weeks.
        weeks_between = max(1, 4 // tpm)
        if week_num % weeks_between != 0:
            continue
        slots_per_week = max(1, tpm // 4)
        for i in range(slots_per_week):
            day_offset = (room["id"] + i) % 7
            due = start_sunday + timedelta(days=day_offset)
            slots.append({
                "room_id": room["id"],
                "room_name": room["name"],
                "due_date": due.strftime("%Y-%m-%d"),
            })
    return sorted(slots, key=lambda s: (s["due_date"], s["room_name"]))


def assign_person_to_slot(slot: dict) -> int:
    """Return flatmate_id for this slot (fairness: fewest cleanings)."""
    flatmates = db.get_active_flatmates()
    if not flatmates:
        return 0
    counts = db.get_cleaning_count_per_flatmate()
    # Person with minimum count gets the slot
    best = min(flatmates, key=lambda f: counts.get(f["id"], 0))
    return best["id"]


def ensure_assignments_exist(config: dict, up_to_days: int = 14):
    """
    Ensure we have assignments for the next `up_to_days` days.
    Called on startup and periodically.
    """
    db.sync_flatmates_from_config(config)
    db.sync_rooms_from_config(config)

    today = datetime.now().date()
    end = today + timedelta(days=up_to_days)
    # Start from this week's Sunday
    today_dt = datetime(today.year, today.month, today.day)
    days_since_sunday = (today_dt.weekday() + 1) % 7
    current = today_dt - timedelta(days=days_since_sunday)

    while current.date() <= end:
        slots = generate_slots_for_week(current, config)
        for slot in slots:
            due = datetime.strptime(slot["due_date"], "%Y-%m-%d").date()
            if today <= due <= end:
                # Check if assignment already exists
                existing = db.get_pending_assignments_for_date(slot["due_date"])
                room_ids_due = [a["room_id"] for a in existing]
                if slot["room_id"] not in room_ids_due:
                    flatmate_id = assign_person_to_slot(slot)
                    if flatmate_id:
                        db.create_assignment(slot["room_id"], flatmate_id, slot["due_date"])
        current += timedelta(days=7)


def get_week_range(d: datetime) -> tuple:
    """Return (start_sunday, end_saturday) for the week containing d."""
    days_since_sunday = (d.weekday() + 1) % 7
    start = d - timedelta(days=days_since_sunday)
    end = start + timedelta(days=6)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
