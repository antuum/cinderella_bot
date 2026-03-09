"""
Schedule generation: which room, when, who.
Assigns random weekdays so each person is reminded on a different day
(one reminder per day, except when postponed).
Per-space: all functions take chat_id.
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict
import cinderella.database as db


def _weeks_since_epoch(d: datetime) -> int:
    """Weeks since Unix epoch (simplified)."""
    return int(d.timestamp() / (7 * 24 * 3600))


def _get_room_slots_for_week(chat_id: int, start_sunday: datetime) -> List[Dict]:
    """
    Get (room_id, room_name) slots for the week — which rooms need cleaning.
    """
    slots = []
    rooms = db.get_rooms(chat_id)
    if not rooms:
        return slots

    week_num = _weeks_since_epoch(start_sunday)
    for room in rooms:
        tpm = room["times_per_month"]
        if tpm < 1:
            continue
        weeks_between = max(1, 4 // tpm)
        if week_num % weeks_between != 0:
            continue
        slots_per_week = max(1, tpm // 4)
        for _ in range(slots_per_week):
            slots.append({"room_id": room["id"], "room_name": room["name"]})
    return slots


def _assign_person_to_slot(chat_id: int, slot: dict, exclude_ids: List[int] = None) -> int:
    """Return flatmate_id for this slot (fairness: fewest cleanings)."""
    flatmates = db.get_active_flatmates(chat_id)
    if not flatmates:
        return 0
    exclude_ids = exclude_ids or []
    counts = db.get_effective_cleaning_count_per_flatmate(chat_id)
    available = [f for f in flatmates if f["id"] not in exclude_ids]
    if not available:
        available = flatmates
    best = min(available, key=lambda f: counts.get(f["id"], 0))
    return best["id"]


def _generate_week_assignments(chat_id: int, start_sunday: datetime) -> List[Dict]:
    """
    Generate (room_id, room_name, flatmate_id, due_date) for the week.
    """
    room_slots = _get_room_slots_for_week(chat_id, start_sunday)
    if not room_slots:
        return []

    assignments = []
    for slot in room_slots:
        exclude = [a["flatmate_id"] for a in assignments]
        flatmate_id = _assign_person_to_slot(chat_id, slot, exclude)
        if flatmate_id:
            assignments.append({
                "room_id": slot["room_id"],
                "room_name": slot["room_name"],
                "flatmate_id": flatmate_id,
                "flatmate_name": None,
            })

    num = len(assignments)
    weekdays = list(range(7))
    random.shuffle(weekdays)
    used_days = weekdays[:num] if num <= 7 else (weekdays * ((num // 7) + 1))[:num]

    for i, a in enumerate(assignments):
        day_offset = used_days[i]
        due = start_sunday + timedelta(days=day_offset)
        a["due_date"] = due.strftime("%Y-%m-%d")
        fm = next((f for f in db.get_active_flatmates(chat_id) if f["id"] == a["flatmate_id"]), None)
        if fm:
            a["flatmate_name"] = fm["name"]

    return sorted(assignments, key=lambda x: (x["due_date"], x["room_name"]))


def ensure_assignments_exist(chat_id: int, up_to_days: int = 14):
    """
    Ensure we have assignments for the next `up_to_days` days for this space.
    """
    today = datetime.now().date()
    end = today + timedelta(days=up_to_days)
    today_dt = datetime(today.year, today.month, today.day)
    days_since_sunday = (today_dt.weekday() + 1) % 7
    current = today_dt - timedelta(days=days_since_sunday)

    while current.date() <= end:
        start_str = current.strftime("%Y-%m-%d")
        end_str = (current + timedelta(days=6)).strftime("%Y-%m-%d")

        if db.has_assignments_for_week(chat_id, start_str, end_str):
            current += timedelta(days=7)
            continue

        assignments = _generate_week_assignments(chat_id, current)
        for a in assignments:
            due = datetime.strptime(a["due_date"], "%Y-%m-%d").date()
            if today <= due <= end:
                existing = db.get_pending_assignments_for_date(chat_id, a["due_date"])
                room_ids_due = [x["room_id"] for x in existing]
                if a["room_id"] not in room_ids_due:
                    db.create_assignment(chat_id, a["room_id"], a["flatmate_id"], a["due_date"])

        current += timedelta(days=7)


def get_week_range(d: datetime) -> tuple:
    """Return (start_sunday, end_saturday) for the week containing d."""
    days_since_sunday = (d.weekday() + 1) % 7
    start = d - timedelta(days=days_since_sunday)
    end = start + timedelta(days=6)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
