"""
JSON storage for Cinderella. Replaces SQLite for portability and manual editing.
On first run, migrates from cinderella.db if it exists, then uses JSON.
"""

import json
import random
from pathlib import Path
from datetime import datetime
from typing import Optional
from calendar import monthrange

DATA_DIR = Path(__file__).parent.parent / "data"
JSON_PATH = DATA_DIR / "cinderella.json"
DB_PATH = DATA_DIR / "cinderella.db"

_DEFAULT_STATE = {
    "flatmates": [],
    "rooms": [],
    "cleaning_records": [],
    "assignments": [],
    "group_chats": [],
    "room_phrase_state": {},
    "config": None,
    "_next_flatmate_id": 1,
    "_next_room_id": 1,
    "_next_assignment_id": 1,
}

_state = None


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_state():
    global _state
    if _state is not None:
        return _state
    _ensure_dir()
    if JSON_PATH.exists():
        try:
            with open(JSON_PATH, encoding="utf-8") as f:
                _state = json.load(f)
        except (json.JSONDecodeError, IOError):
            _state = _DEFAULT_STATE.copy()
    else:
        _state = _migrate_from_db() if DB_PATH.exists() else _DEFAULT_STATE.copy()
        _save_state()
    return _state


def _save_state():
    _ensure_dir()
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)


def _migrate_from_db() -> dict:
    """Migrate from SQLite to JSON. Backs up DB as .db.migrated."""
    import sqlite3
    print("[>] Migrating from SQLite to JSON storage...")
    state = _DEFAULT_STATE.copy()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Config
        row = conn.execute("SELECT config_json FROM config WHERE id = 1").fetchone()
        if row:
            state["config"] = json.loads(row["config_json"])

        # Flatmates
        cols = [d[1] for d in conn.execute("PRAGMA table_info(flatmates)").fetchall()]
        for r in conn.execute("SELECT * FROM flatmates").fetchall():
            row = dict(zip(cols, r))
            state["flatmates"].append({
                "id": row["id"],
                "name": row["name"],
                "telegram_username": row["telegram_username"],
                "telegram_id": row.get("telegram_id"),
                "is_active": bool(row.get("is_active", 1)),
                "replaced_at": row.get("replaced_at"),
                "replaced_by_id": row.get("replaced_by_id"),
                "starting_offset": row.get("starting_offset") or 0,
            })
        state["_next_flatmate_id"] = max((f["id"] for f in state["flatmates"]), default=0) + 1

        # Rooms
        for r in conn.execute("SELECT * FROM rooms").fetchall():
            state["rooms"].append({
                "id": r["id"],
                "name": r["name"],
                "times_per_month": r["times_per_month"],
            })
        state["_next_room_id"] = max((r["id"] for r in state["rooms"]), default=0) + 1

        # Cleaning records
        for r in conn.execute("SELECT * FROM cleaning_records").fetchall():
            state["cleaning_records"].append({
                "room_id": r["room_id"],
                "flatmate_id": r["flatmate_id"],
                "cleaned_at": r["cleaned_at"] or datetime.utcnow().isoformat(),
                "was_assigned": bool(r["was_assigned"]),
            })

        # Assignments
        for r in conn.execute("SELECT * FROM assignments").fetchall():
            state["assignments"].append({
                "id": r["id"],
                "room_id": r["room_id"],
                "flatmate_id": r["flatmate_id"],
                "due_date": r["due_date"],
                "status": r["status"] or "pending",
                "reminder_count": r["reminder_count"] or 0,
                "remind_on": r["remind_on"],
            })
        state["_next_assignment_id"] = max((a["id"] for a in state["assignments"]), default=0) + 1

        # Group chats
        for r in conn.execute("SELECT * FROM group_chats").fetchall():
            state["group_chats"].append({
                "chat_id": r["chat_id"],
                "bot_introduced": bool(r["bot_introduced"]),
            })

        # Room phrase state
        try:
            for r in conn.execute("SELECT * FROM room_phrase_state").fetchall():
                state["room_phrase_state"][str(r["room_id"])] = {
                    "phrase_index": r["phrase_index"],
                    "phrase_order": json.loads(r["phrase_order"]) if isinstance(r["phrase_order"], str) else r["phrase_order"],
                }
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    # Backup DB
    backup = DB_PATH.with_suffix(".db.migrated")
    DB_PATH.rename(backup)
    print(f"[+] Migration done. Old DB backed up as {backup.name}")
    return state


# --- API (matches database.py interface) ---

def ensure_db_dir():
    _ensure_dir()


def get_connection():
    """No-op for compatibility. JSON storage doesn't use connections."""
    return None


def init_db():
    """Load or create state. Migrate from DB if present."""
    _load_state()


def save_config(config: dict):
    s = _load_state()
    s["config"] = config
    _save_state()


def load_config() -> Optional[dict]:
    s = _load_state()
    return s.get("config")


def sync_flatmates_from_config(config: dict):
    s = _load_state()
    existing = {f["telegram_username"]: f for f in s["flatmates"]}
    for fm in config.get("flatmates", []):
        uname = fm["telegram_username"].lstrip("@")
        name = fm["name"]
        if uname in existing:
            for f in s["flatmates"]:
                if f["telegram_username"] == uname:
                    f["name"] = name
                    break
        else:
            fid = s["_next_flatmate_id"]
            s["_next_flatmate_id"] += 1
            s["flatmates"].append({
                "id": fid, "name": name, "telegram_username": uname,
                "telegram_id": None, "is_active": True, "replaced_at": None,
                "replaced_by_id": None, "starting_offset": 0,
            })
    _save_state()


def replace_flatmate(old_username: str, new_name: str, new_username: str):
    s = _load_state()
    old = next((f for f in s["flatmates"] if f["telegram_username"] == old_username.lstrip("@") and f["is_active"]), None)
    if not old:
        return False
    active = [f for f in s["flatmates"] if f["is_active"] and f["id"] != old["id"]]
    counts = {}
    for f in active:
        c = sum(1 for r in s["cleaning_records"] if r["flatmate_id"] == f["id"])
        counts[f["id"]] = c
    starting_offset = min(counts.values(), default=0)
    fid = s["_next_flatmate_id"]
    s["_next_flatmate_id"] += 1
    s["flatmates"].append({
        "id": fid, "name": new_name, "telegram_username": new_username.lstrip("@"),
        "telegram_id": None, "is_active": True, "replaced_at": None,
        "replaced_by_id": None, "starting_offset": starting_offset,
    })
    for f in s["flatmates"]:
        if f["id"] == old["id"]:
            f["is_active"] = False
            f["replaced_at"] = datetime.utcnow().isoformat()
            f["replaced_by_id"] = fid
            break
    reshuffle_phrase_orders()
    _save_state()
    return True


def reshuffle_phrase_orders():
    s = _load_state()
    order = list(range(33))
    for r in s["rooms"]:
        rid = str(r["id"])
        shuffled = order.copy()
        random.shuffle(shuffled)
        s["room_phrase_state"][rid] = {"phrase_index": 0, "phrase_order": shuffled}
    _save_state()


def get_and_advance_phrase(room_id: int, num_phrases: int = 33) -> int:
    s = _load_state()
    rid = str(room_id)
    if rid not in s["room_phrase_state"]:
        order = list(range(num_phrases))
        random.shuffle(order)
        s["room_phrase_state"][rid] = {"phrase_index": 0, "phrase_order": order}
    ps = s["room_phrase_state"][rid]
    order = ps["phrase_order"]
    idx = ps["phrase_index"]
    phrase_idx = order[idx % num_phrases]
    ps["phrase_index"] = (idx + 1) % num_phrases
    _save_state()
    return phrase_idx


def set_flatmate_telegram_id(username: str, telegram_id: int):
    s = _load_state()
    for f in s["flatmates"]:
        if f["telegram_username"] == username.lstrip("@") and f["is_active"]:
            f["telegram_id"] = telegram_id
            break
    _save_state()


def sync_rooms_from_config(config: dict):
    s = _load_state()
    by_name = {r["name"]: r for r in s["rooms"]}
    for room in config.get("rooms", []):
        name, tpm = room["name"], room["times_per_month"]
        if name in by_name:
            by_name[name]["times_per_month"] = tpm
        else:
            rid = s["_next_room_id"]
            s["_next_room_id"] += 1
            s["rooms"].append({"id": rid, "name": name, "times_per_month": tpm})
    _save_state()


def get_active_flatmates():
    s = _load_state()
    return [{"id": f["id"], "name": f["name"], "telegram_username": f["telegram_username"], "telegram_id": f.get("telegram_id")}
            for f in s["flatmates"] if f["is_active"]]


def get_rooms():
    s = _load_state()
    return [{"id": r["id"], "name": r["name"], "times_per_month": r["times_per_month"]} for r in s["rooms"]]


def get_monthly_stats(year: int, month: int) -> list:
    _, last_day = monthrange(year, month)
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    s = _load_state()
    room_by_id = {r["id"]: r["name"] for r in s["rooms"]}
    flatmate_by_id = {f["id"]: {"name": f["name"], "username": f["telegram_username"]} for f in s["flatmates"]}
    by_person = {}
    for rec in s["cleaning_records"]:
        dt = rec.get("cleaned_at", "")[:10]
        if not (start <= dt <= end):
            continue
        fid = rec["flatmate_id"]
        rid = rec["room_id"]
        rname = room_by_id.get(rid, "?")
        fm = flatmate_by_id.get(fid)
        if not fm:
            continue
        if fid not in by_person:
            by_person[fid] = {"name": fm["name"], "username": fm["username"], "total": 0, "rooms": {}}
        by_person[fid]["total"] += 1
        by_person[fid]["rooms"][rname] = by_person[fid]["rooms"].get(rname, 0) + 1
    result = [{"name": v["name"], "username": v["username"], "total": v["total"], "rooms": v["rooms"]}
              for v in by_person.values()]
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def get_cleaning_count_per_flatmate():
    s = _load_state()
    counts = {}
    for rec in s["cleaning_records"]:
        fid = rec["flatmate_id"]
        counts[fid] = counts.get(fid, 0) + 1
    return counts


def get_effective_cleaning_count_per_flatmate():
    s = _load_state()
    counts = {}
    for f in s["flatmates"]:
        if not f["is_active"]:
            continue
        fid = f["id"]
        c = sum(1 for r in s["cleaning_records"] if r["flatmate_id"] == fid)
        counts[fid] = c + (f.get("starting_offset") or 0)
    return counts


def record_cleaning(room_id: int, flatmate_id: int, was_assigned: bool = True):
    s = _load_state()
    s["cleaning_records"].append({
        "room_id": room_id, "flatmate_id": flatmate_id,
        "cleaned_at": datetime.utcnow().isoformat(),
        "was_assigned": was_assigned,
    })
    _save_state()


def get_or_create_group_chat(chat_id: int) -> dict:
    s = _load_state()
    for gc in s["group_chats"]:
        if gc["chat_id"] == chat_id:
            return {"chat_id": chat_id, "bot_introduced": gc["bot_introduced"]}
    s["group_chats"].append({"chat_id": chat_id, "bot_introduced": False})
    _save_state()
    return {"chat_id": chat_id, "bot_introduced": False}


def set_bot_introduced(chat_id: int):
    s = _load_state()
    for gc in s["group_chats"]:
        if gc["chat_id"] == chat_id:
            gc["bot_introduced"] = True
            break
    _save_state()


def get_pending_assignments_for_date(date_str: str):
    s = _load_state()
    room_by_id = {r["id"]: r for r in s["rooms"]}
    flatmate_by_id = {f["id"]: f for f in s["flatmates"]}
    result = []
    for a in s["assignments"]:
        if a["status"] != "pending":
            continue
        remind_on = a.get("remind_on")
        due = a["due_date"]
        if not ((remind_on == date_str) or (remind_on is None and due == date_str)):
            continue
        room = room_by_id.get(a["room_id"], {})
        fm = flatmate_by_id.get(a["flatmate_id"], {})
        result.append({
            "id": a["id"], "room_id": a["room_id"], "flatmate_id": a["flatmate_id"],
            "reminder_count": a.get("reminder_count", 0),
            "room_name": room.get("name", "?"), "flatmate_name": fm.get("name", "?"),
            "telegram_username": fm.get("telegram_username", "?"),
        })
    return result


def set_remind_on(assignment_id: int, date_str: str):
    s = _load_state()
    for a in s["assignments"]:
        if a["id"] == assignment_id:
            a["remind_on"] = date_str
            break
    _save_state()


def has_assignments_for_week(start_date: str, end_date: str) -> bool:
    s = _load_state()
    return any(start_date <= a["due_date"] <= end_date for a in s["assignments"])


def get_assignments_for_week(start_date: str, end_date: str):
    s = _load_state()
    room_by_id = {r["id"]: r for r in s["rooms"]}
    flatmate_by_id = {f["id"]: f for f in s["flatmates"]}
    result = []
    for a in s["assignments"]:
        if a["status"] != "pending" or not (start_date <= a["due_date"] <= end_date):
            continue
        room = room_by_id.get(a["room_id"], {})
        fm = flatmate_by_id.get(a["flatmate_id"], {})
        result.append({
            "id": a["id"], "due_date": a["due_date"], "room_name": room.get("name", "?"),
            "flatmate_name": fm.get("name", "?"), "telegram_username": fm.get("telegram_username", "?"),
        })
    result.sort(key=lambda x: (x["due_date"], x["room_name"]))
    return result


def create_assignment(room_id: int, flatmate_id: int, due_date: str):
    s = _load_state()
    aid = s["_next_assignment_id"]
    s["_next_assignment_id"] += 1
    s["assignments"].append({
        "id": aid, "room_id": room_id, "flatmate_id": flatmate_id, "due_date": due_date,
        "status": "pending", "reminder_count": 0, "remind_on": None,
    })
    _save_state()


def update_assignment_status(assignment_id: int, status: str):
    s = _load_state()
    for a in s["assignments"]:
        if a["id"] == assignment_id:
            a["status"] = status
            break
    _save_state()


def increment_reminder_count(assignment_id: int):
    s = _load_state()
    for a in s["assignments"]:
        if a["id"] == assignment_id:
            a["reminder_count"] = a.get("reminder_count", 0) + 1
            a["last_reminder_at"] = datetime.utcnow().isoformat()
            break
    _save_state()


def get_assignment_by_id(assignment_id: int) -> Optional[dict]:
    s = _load_state()
    room_by_id = {r["id"]: r for r in s["rooms"]}
    flatmate_by_id = {f["id"]: f for f in s["flatmates"]}
    for a in s["assignments"]:
        if a["id"] == assignment_id:
            room = room_by_id.get(a["room_id"], {})
            fm = flatmate_by_id.get(a["flatmate_id"], {})
            return {
                **a, "room_name": room.get("name", "?"), "flatmate_name": fm.get("name", "?"),
                "telegram_username": fm.get("telegram_username", "?"),
            }
    return None


def get_flatmate_by_username(username: str) -> Optional[dict]:
    s = _load_state()
    uname = username.lstrip("@")
    for f in s["flatmates"]:
        if f["telegram_username"] == uname and f["is_active"]:
            return dict(f)
    return None


def get_flatmate_with_fewest_cleanings_excluding(exclude_ids: list) -> Optional[dict]:
    counts = get_effective_cleaning_count_per_flatmate()
    active = [f for f in get_active_flatmates() if f["id"] not in (exclude_ids or [])]
    if not active:
        active = get_active_flatmates()
    if not active:
        return None
    best = min(active, key=lambda f: counts.get(f["id"], 0))
    return best


def get_chat_ids_with_bot_introduced():
    """Return chat_ids where bot was introduced."""
    s = _load_state()
    return [gc["chat_id"] for gc in s["group_chats"] if gc["bot_introduced"]]


def get_room_by_name(name: str):
    """Get room by name (case-insensitive)."""
    s = _load_state()
    lower = name.strip().lower()
    for r in s["rooms"]:
        if r["name"].lower() == lower:
            return r
    return None


def get_pending_assignment_for_room_in_week(room_id: int, start_date: str, end_date: str):
    """Get pending assignment for room in the given week range, if any."""
    s = _load_state()
    for a in s["assignments"]:
        if a["room_id"] == room_id and a["status"] == "pending" and start_date <= a["due_date"] <= end_date:
            return a
    return None


def get_full_cleaning_history():
    """Return all cleaning records with room names and flatmate names, newest first."""
    s = _load_state()
    room_by_id = {r["id"]: r["name"] for r in s["rooms"]}
    flatmate_by_id = {f["id"]: {"name": f["name"], "username": f["telegram_username"]} for f in s["flatmates"]}
    records = []
    for rec in s["cleaning_records"]:
        dt = rec.get("cleaned_at", "")[:19]
        date_str = dt[:10] if len(dt) >= 10 else "?"
        rname = room_by_id.get(rec["room_id"], "?")
        fm = flatmate_by_id.get(rec["flatmate_id"], {"name": "?", "username": "?"})
        records.append({
            "date": date_str,
            "room_name": rname,
            "flatmate_name": fm["name"],
            "flatmate_username": fm["username"],
            "cleaned_at": rec.get("cleaned_at", ""),
        })
    records.sort(key=lambda r: r["cleaned_at"], reverse=True)
    return records
