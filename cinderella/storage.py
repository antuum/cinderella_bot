"""
Per-space JSON storage for Cinderella.
Files: data/spaces/YYYY-MM-DD_HH-MM-SS_{chat_id}_{sanitized_name}.json
Index maps chat_id -> filename. Migrates from legacy on first run.
"""

import json
import random
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from calendar import monthrange

DATA_DIR = Path(__file__).parent.parent / "data"
SPACES_DIR = DATA_DIR / "spaces"
INDEX_PATH = DATA_DIR / "spaces_index.json"
LEGACY_JSON = DATA_DIR / "cinderella.json"
LEGACY_DB = DATA_DIR / "cinderella.db"

MAX_ROOMS = 666
MAX_MEMBERS = 666
MAX_TIMES_PER_MONTH = 28

_DEFAULT_SPACE = {
    "chat_id": 0,
    "title": "",
    "added_at": "",
    "bot_introduced": False,
    "silence_until": None,
    "silent_forever": False,
    "last_setup_reminder_week": None,
    "members": [],
    "rooms": [],
    "cleaning_records": [],
    "assignments": [],
    "room_phrase_state": {},
    "seen_in_group": [],
    "settings": {
        "reminder_hour": 9,
        "reminder_minute": 0,
        "weekly_report_day": "sunday",
        "weekly_report_hour": 10,
        "weekly_report_minute": 0,
        "monthly_report_hour": 20,
        "monthly_report_minute": 0,
        "timezone": "Europe/Berlin",
    },
    "_next_member_id": 1,
    "_next_room_id": 1,
    "_next_assignment_id": 1,
}


def _sanitize_filename_part(name: str, max_len: int = 80) -> str:
    """Encode invalid filename chars as _xXXXX (hex). Safe for all filesystems."""
    if not name or not str(name).strip():
        return ""
    result = []
    for c in str(name).strip():
        if re.match(r"[a-zA-Z0-9_-]", c):
            result.append(c)
        elif c == " ":
            result.append("-")
        else:
            result.append(f"_x{ord(c):04x}")
    return "".join(result)[:max_len] or "group"


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SPACES_DIR.mkdir(parents=True, exist_ok=True)


def _new_filename(chat_id: int, title: str, added_at: str = None) -> str:
    """Format: 2026-03-09_14-30-52_{chat_id}_{sanitized_title}.json"""
    if added_at:
        try:
            dt = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
            ts = dt.strftime("%Y-%m-%d_%H-%M-%S")
        except (ValueError, TypeError):
            ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    else:
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    safe_title = _sanitize_filename_part(title or str(chat_id))
    return f"{ts}_{chat_id}_{safe_title}.json"


def _legacy_path(chat_id: int) -> Path:
    return SPACES_DIR / f"{chat_id}.json"


def _path_from_filename(filename: str) -> Path:
    return SPACES_DIR / filename


def _get_space_path(chat_id: int, state: dict = None) -> Optional[Path]:
    """Resolve path: index filename, or legacy {chat_id}.json."""
    index = _load_index()
    for e in index.get("spaces", []):
        if e["chat_id"] == chat_id and e.get("filename"):
            p = _path_from_filename(e["filename"])
            if p.exists():
                return p
            break
    leg = _legacy_path(chat_id)
    if leg.exists():
        return leg
    return None


def _load_space(chat_id: int) -> dict:
    """Load space state for a chat. Creates default if not exists."""
    _ensure_dirs()
    path = _get_space_path(chat_id)
    if path and path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    state = _DEFAULT_SPACE.copy()
    state["chat_id"] = chat_id
    state["added_at"] = datetime.utcnow().isoformat()
    return state


def _save_space(chat_id: int, state: dict):
    _ensure_dirs()
    state["chat_id"] = chat_id
    index = _load_index()
    entry = next((e for e in index.get("spaces", []) if e["chat_id"] == chat_id), None)
    filename = entry.get("filename") if entry else None

    if not filename:
        filename = _new_filename(chat_id, state.get("title", ""), state.get("added_at"))
        legacy = _legacy_path(chat_id)
        if legacy.exists():
            try:
                legacy.unlink()
            except OSError:
                pass

    path = _path_from_filename(filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    _update_index(chat_id, state.get("title", ""), state.get("bot_introduced"), filename)


def _update_index(chat_id: int, title: str = "", bot_introduced: bool = None, filename: str = None):
    """Update spaces index (sorted by added_at)."""
    index = _load_index()
    now = datetime.utcnow().isoformat()
    found = False
    for e in index.get("spaces", []):
        if e["chat_id"] == chat_id:
            if title:
                e["title"] = title
            if bot_introduced is not None:
                e["bot_introduced"] = bot_introduced
            if filename:
                e["filename"] = filename
            e["updated_at"] = now
            found = True
            break
    if not found:
        fn = filename
        index.setdefault("spaces", []).append({
            "chat_id": chat_id,
            "filename": fn,
            "title": title,
            "added_at": now,
            "updated_at": now,
            "bot_introduced": bot_introduced if bot_introduced is not None else False,
        })
    index["spaces"].sort(key=lambda x: x.get("added_at", ""), reverse=True)
    _ensure_dirs()
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _load_index() -> dict:
    if INDEX_PATH.exists():
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"spaces": []}


# --- Migration from legacy ---

def _migrate_legacy():
    """
    Migrate legacy cinderella.json or cinderella.db to per-space format.
    Preserves all data for the existing group.
    """
    _ensure_dirs()
    chat_id = None
    legacy_state = None

    if LEGACY_JSON.exists():
        try:
            with open(LEGACY_JSON, encoding="utf-8") as f:
                legacy_state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    elif LEGACY_DB.exists():
        legacy_state = _migrate_from_db()

    if not legacy_state:
        return

    # Find the group chat to migrate to (prefer one with bot_introduced)
    group_chats = legacy_state.get("group_chats", [])
    for gc in group_chats:
        if gc.get("bot_introduced"):
            chat_id = gc["chat_id"]
            break
    if not chat_id and group_chats:
        chat_id = group_chats[0]["chat_id"]

    if not chat_id:
        print("[!] Legacy data has no group_chats. Cannot migrate.")
        return

    # Build new space from legacy
    state = _DEFAULT_SPACE.copy()
    state["chat_id"] = chat_id
    state["bot_introduced"] = True
    state["added_at"] = datetime.utcnow().isoformat()

    # Map flatmates -> members
    for f in legacy_state.get("flatmates", []):
        state["members"].append({
            "id": f["id"],
            "name": f["name"],
            "telegram_username": f["telegram_username"],
            "telegram_id": f.get("telegram_id"),
            "is_active": f.get("is_active", True),
            "replaced_at": f.get("replaced_at"),
            "replaced_by_id": f.get("replaced_by_id"),
            "starting_offset": f.get("starting_offset", 0),
        })
    state["_next_member_id"] = max((m["id"] for m in state["members"]), default=0) + 1

    state["rooms"] = list(legacy_state.get("rooms", []))
    state["_next_room_id"] = max((r["id"] for r in state["rooms"]), default=0) + 1

    state["cleaning_records"] = list(legacy_state.get("cleaning_records", []))
    state["assignments"] = list(legacy_state.get("assignments", []))
    state["_next_assignment_id"] = max((a["id"] for a in state["assignments"]), default=0) + 1
    state["room_phrase_state"] = dict(legacy_state.get("room_phrase_state", {}))

    config = legacy_state.get("config")
    if config:
        state["settings"].update({
            "reminder_hour": config.get("reminder_hour", 9),
            "reminder_minute": config.get("reminder_minute", 0),
            "weekly_report_day": config.get("weekly_report_day", "sunday"),
            "weekly_report_hour": config.get("weekly_report_hour", 10),
            "weekly_report_minute": config.get("weekly_report_minute", 0),
            "monthly_report_hour": config.get("monthly_report_hour", 20),
            "monthly_report_minute": config.get("monthly_report_minute", 0),
            "timezone": config.get("timezone", "Europe/Berlin"),
        })
    if "timezone" not in state.get("settings", {}):
        state.setdefault("settings", {})["timezone"] = "Europe/Berlin"
    state.setdefault("silence_until", None)
    state.setdefault("silent_forever", False)

    _save_space(chat_id, state)

    # Backup legacy
    if LEGACY_JSON.exists():
        backup = LEGACY_JSON.with_suffix(".json.legacy")
        LEGACY_JSON.rename(backup)
        print(f"[+] Migrated to per-space. Legacy backed up as {backup.name}")

    if LEGACY_DB.exists():
        backup = LEGACY_DB.with_suffix(".db.migrated")
        LEGACY_DB.rename(backup)
        print(f"[+] Legacy DB backed up as {backup.name}")


def _migrate_from_db() -> dict:
    """Migrate from SQLite to legacy dict format (then _migrate_legacy does the rest)."""
    import sqlite3
    state = {
        "flatmates": [],
        "rooms": [],
        "cleaning_records": [],
        "assignments": [],
        "group_chats": [],
        "room_phrase_state": {},
        "config": None,
    }
    conn = sqlite3.connect(LEGACY_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT config_json FROM config WHERE id = 1").fetchone()
        if row:
            state["config"] = json.loads(row["config_json"])

        cols = [d[1] for d in conn.execute("PRAGMA table_info(flatmates)").fetchall()]
        for r in conn.execute("SELECT * FROM flatmates").fetchall():
            row = dict(zip(cols, r))
            state["flatmates"].append({
                "id": row["id"], "name": row["name"], "telegram_username": row["telegram_username"],
                "telegram_id": row.get("telegram_id"), "is_active": bool(row.get("is_active", 1)),
                "replaced_at": row.get("replaced_at"), "replaced_by_id": row.get("replaced_by_id"),
                "starting_offset": row.get("starting_offset", 0),
            })

        for r in conn.execute("SELECT * FROM rooms").fetchall():
            state["rooms"].append({"id": r["id"], "name": r["name"], "times_per_month": r["times_per_month"]})

        for r in conn.execute("SELECT * FROM cleaning_records").fetchall():
            state["cleaning_records"].append({
                "room_id": r["room_id"], "flatmate_id": r["flatmate_id"],
                "cleaned_at": r["cleaned_at"] or datetime.utcnow().isoformat(),
                "was_assigned": bool(r["was_assigned"]),
            })

        for r in conn.execute("SELECT * FROM assignments").fetchall():
            state["assignments"].append({
                "id": r["id"], "room_id": r["room_id"], "flatmate_id": r["flatmate_id"],
                "due_date": r["due_date"], "status": r["status"] or "pending",
                "reminder_count": r["reminder_count"] or 0, "remind_on": r["remind_on"],
            })

        for r in conn.execute("SELECT * FROM group_chats").fetchall():
            state["group_chats"].append({"chat_id": r["chat_id"], "bot_introduced": bool(r["bot_introduced"])})

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
    return state


def _run_migration_if_needed():
    """Run migration once if legacy data exists."""
    if LEGACY_JSON.exists() or LEGACY_DB.exists():
        _migrate_legacy()


# --- API (chat_id as first param for all space-scoped functions) ---

def ensure_db_dir():
    _ensure_dirs()


def get_connection():
    return None


def init_db():
    _run_migration_if_needed()


def get_or_create_space(chat_id: int, title: str = "") -> dict:
    """Get or create space for chat. Updates title if provided."""
    _run_migration_if_needed()
    state = _load_space(chat_id)
    if title and state.get("title") != title:
        state["title"] = title
        _save_space(chat_id, state)
    return {"chat_id": chat_id, "bot_introduced": state["bot_introduced"]}


def set_bot_introduced(chat_id: int):
    state = _load_space(chat_id)
    state["bot_introduced"] = True
    _save_space(chat_id, state)


def get_space_settings(chat_id: int) -> dict:
    """Get settings dict for space (used like config)."""
    state = _load_space(chat_id)
    return state.get("settings", _DEFAULT_SPACE["settings"].copy())


def save_space_settings(chat_id: int, settings: dict):
    state = _load_space(chat_id)
    state["settings"] = {**_DEFAULT_SPACE["settings"], **settings}
    _save_space(chat_id, state)


def space_has_setup(chat_id: int) -> bool:
    """True if space has at least one room and one member."""
    state = _load_space(chat_id)
    return bool(state.get("rooms")) and bool([m for m in state.get("members", []) if m.get("is_active", True)])


def get_active_flatmates(chat_id: int):
    state = _load_space(chat_id)
    return [
        {"id": f["id"], "name": f["name"], "telegram_username": f["telegram_username"], "telegram_id": f.get("telegram_id")}
        for f in state.get("members", []) if f.get("is_active", True)
    ]


def get_rooms(chat_id: int):
    state = _load_space(chat_id)
    return [
        {"id": r["id"], "name": r["name"], "times_per_month": r["times_per_month"], "cleaning_types": r.get("cleaning_types", [])}
        for r in state.get("rooms", [])
    ]


def add_room(chat_id: int, name: str, times_per_month: int) -> dict:
    state = _load_space(chat_id)
    if len(state.get("rooms", [])) >= MAX_ROOMS:
        raise ValueError(f"Maximum {MAX_ROOMS} rooms allowed.")
    tpm = max(1, min(MAX_TIMES_PER_MONTH, int(times_per_month)))
    rid = state["_next_room_id"]
    state["_next_room_id"] += 1
    room = {"id": rid, "name": name.strip(), "times_per_month": tpm, "cleaning_types": []}
    state.setdefault("rooms", []).append(room)
    state["silent_forever"] = False
    state["silence_until"] = None
    _save_space(chat_id, state)
    return room


def update_room_times(chat_id: int, room_id: int, times_per_month: int):
    """Set times per month (max 28). Raises ValueError if > 28."""
    tpm = int(times_per_month)
    if tpm > MAX_TIMES_PER_MONTH:
        raise ValueError(
            f"It's impossible to have more reminders than there are days in a month. "
            f"Maximum is {MAX_TIMES_PER_MONTH}."
        )
    tpm = max(1, min(MAX_TIMES_PER_MONTH, tpm))
    state = _load_space(chat_id)
    for r in state.get("rooms", []):
        if r["id"] == room_id:
            r["times_per_month"] = tpm
            break
    _save_space(chat_id, state)


def update_room_cleaning_types(chat_id: int, room_id: int, cleaning_types: list):
    """Set cleaning types for room. List of strings (from presets or custom)."""
    state = _load_space(chat_id)
    for r in state.get("rooms", []):
        if r["id"] == room_id:
            r["cleaning_types"] = [t.strip() for t in cleaning_types if t and str(t).strip()]
            break
    _save_space(chat_id, state)


def remove_room(chat_id: int, room_id: int) -> bool:
    state = _load_space(chat_id)
    state["rooms"] = [r for r in state.get("rooms", []) if r["id"] != room_id]
    state["room_phrase_state"] = {k: v for k, v in state.get("room_phrase_state", {}).items() if int(k) != room_id}
    _save_space(chat_id, state)
    return True


def add_member(chat_id: int, name: str, telegram_username: str, starting_offset: int = 0, telegram_id: int = None) -> dict:
    state = _load_space(chat_id)
    active_count = sum(1 for m in state.get("members", []) if m.get("is_active", True))
    if active_count >= MAX_MEMBERS:
        raise ValueError(f"Maximum {MAX_MEMBERS} members allowed.")
    uname = telegram_username.lstrip("@").strip().lower()
    for m in state.get("members", []):
        if m.get("telegram_username", "").lower() == uname and m.get("is_active", True):
            return m  # Already exists
    mid = state["_next_member_id"]
    state["_next_member_id"] += 1
    member = {"id": mid, "name": name.strip(), "telegram_username": uname, "telegram_id": telegram_id,
              "is_active": True, "replaced_at": None, "replaced_by_id": None, "starting_offset": starting_offset}
    state.setdefault("members", []).append(member)
    _save_space(chat_id, state)
    return member


def space_has_members(chat_id: int) -> bool:
    """True if space has at least one active member."""
    state = _load_space(chat_id)
    return bool([m for m in state.get("members", []) if m.get("is_active", True)])


def sync_members_from_group_users(chat_id: int, users: list) -> int:
    """
    Seed members from group participants (e.g. chat administrators).
    Only runs when space has zero members. Each user: {username, first_name, user_id}.
    Skips users without username (cannot be tagged). Returns count added.
    """
    if space_has_members(chat_id):
        return 0
    added = 0
    for u in users:
        uname = (u.get("username") or "").strip().lower()
        if not uname:
            continue
        first_name = (u.get("first_name") or "").strip()
        name = first_name or uname
        try:
            add_member(chat_id, name, uname, starting_offset=0, telegram_id=u.get("user_id"))
            added += 1
        except ValueError:
            pass
    return added


def remove_member(chat_id: int, username: str) -> bool:
    """Mark member as inactive (left space)."""
    state = _load_space(chat_id)
    uname = username.lstrip("@").strip().lower()
    for m in state.get("members", []):
        if m.get("telegram_username", "").lower() == uname and m.get("is_active", True):
            m["is_active"] = False
            m["replaced_at"] = datetime.utcnow().isoformat()
            _save_space(chat_id, state)
            return True
    return False


def replace_flatmate(chat_id: int, old_username: str, new_name: str, new_username: str):
    state = _load_space(chat_id)
    uname = old_username.lstrip("@").strip().lower()
    old = next((m for m in state.get("members", []) if m.get("telegram_username", "").lower() == uname and m.get("is_active", True)), None)
    if not old:
        return False
    active = [m for m in state["members"] if m.get("is_active", True) and m["id"] != old["id"]]
    counts = {}
    for m in active:
        c = sum(1 for r in state.get("cleaning_records", []) if r["flatmate_id"] == m["id"])
        counts[m["id"]] = c
    starting_offset = min(counts.values(), default=0)
    mid = state["_next_member_id"]
    state["_next_member_id"] += 1
    state["members"].append({
        "id": mid, "name": new_name.strip(), "telegram_username": new_username.lstrip("@").strip().lower(),
        "telegram_id": None, "is_active": True, "replaced_at": None, "replaced_by_id": None, "starting_offset": starting_offset,
    })
    for m in state["members"]:
        if m["id"] == old["id"]:
            m["is_active"] = False
            m["replaced_at"] = datetime.utcnow().isoformat()
            m["replaced_by_id"] = mid
            break
    reshuffle_phrase_orders(chat_id)
    _save_space(chat_id, state)
    return True


def reshuffle_phrase_orders(chat_id: int):
    state = _load_space(chat_id)
    order = list(range(33))
    for r in state.get("rooms", []):
        rid = str(r["id"])
        shuffled = order.copy()
        random.shuffle(shuffled)
        state.setdefault("room_phrase_state", {})[rid] = {"phrase_index": 0, "phrase_order": shuffled}
    _save_space(chat_id, state)


def get_and_advance_phrase(chat_id: int, room_id: int, num_phrases: int = 33) -> int:
    state = _load_space(chat_id)
    rid = str(room_id)
    if rid not in state.get("room_phrase_state", {}):
        order = list(range(num_phrases))
        random.shuffle(order)
        state.setdefault("room_phrase_state", {})[rid] = {"phrase_index": 0, "phrase_order": order}
    ps = state["room_phrase_state"][rid]
    order = ps["phrase_order"]
    idx = ps["phrase_index"]
    phrase_idx = order[idx % num_phrases]
    ps["phrase_index"] = (idx + 1) % num_phrases
    _save_space(chat_id, state)
    return phrase_idx


def sync_flatmates_from_config(chat_id: int, config: dict):
    for fm in config.get("flatmates", []):
        add_member(chat_id, fm["name"], fm["telegram_username"])


def sync_rooms_from_config(chat_id: int, config: dict):
    """Add or update rooms from config. Updates times_per_month if name matches."""
    state = _load_space(chat_id)
    for room in config.get("rooms", []):
        name = room["name"].strip()
        tpm = max(1, min(MAX_TIMES_PER_MONTH, int(room.get("times_per_month", 1))))
        existing = next((r for r in state.get("rooms", []) if r["name"].lower() == name.lower()), None)
        if existing:
            existing["times_per_month"] = tpm
        elif len(state.get("rooms", [])) < MAX_ROOMS:
            rid = state["_next_room_id"]
            state["_next_room_id"] += 1
            state.setdefault("rooms", []).append({"id": rid, "name": name, "times_per_month": tpm})
    _save_space(chat_id, state)


def load_config(chat_id: int) -> Optional[dict]:
    """Load config as dict (rooms, flatmates, settings) for compatibility."""
    state = _load_space(chat_id)
    settings = state.get("settings", {})
    return {
        "rooms": [{"name": r["name"], "times_per_month": r["times_per_month"]} for r in state.get("rooms", [])],
        "flatmates": [{"name": m["name"], "telegram_username": m["telegram_username"]} for m in state.get("members", []) if m.get("is_active", True)],
        **settings,
    }


def save_config(chat_id: int, config: dict):
    if config.get("rooms"):
        state = _load_space(chat_id)
        state["rooms"] = []
        state["_next_room_id"] = 1
        for r in config["rooms"]:
            add_room(chat_id, r["name"], r["times_per_month"])
    if config.get("flatmates"):
        for fm in config["flatmates"]:
            add_member(chat_id, fm["name"], fm["telegram_username"])
    save_space_settings(chat_id, {k: v for k, v in config.items() if k in _DEFAULT_SPACE["settings"]})


def set_flatmate_telegram_id(chat_id: int, username: str, telegram_id: int):
    state = _load_space(chat_id)
    uname = username.lstrip("@").strip().lower()
    for m in state.get("members", []):
        if m.get("telegram_username", "").lower() == uname and m.get("is_active", True):
            m["telegram_id"] = telegram_id
            _save_space(chat_id, state)
            break


def get_monthly_stats(chat_id: int, year: int, month: int) -> list:
    _, last_day = monthrange(year, month)
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    state = _load_space(chat_id)
    room_by_id = {r["id"]: r["name"] for r in state.get("rooms", [])}
    member_by_id = {m["id"]: {"name": m["name"], "username": m["telegram_username"]} for m in state.get("members", [])}
    by_person = {}
    for rec in state.get("cleaning_records", []):
        dt = rec.get("cleaned_at", "")[:10]
        if not (start <= dt <= end):
            continue
        fid = rec["flatmate_id"]
        rid = rec["room_id"]
        rname = room_by_id.get(rid, "?")
        member = member_by_id.get(fid)
        if not member:
            continue
        if fid not in by_person:
            by_person[fid] = {"name": member["name"], "username": member["username"], "total": 0, "rooms": {}}
        by_person[fid]["total"] += 1
        by_person[fid]["rooms"][rname] = by_person[fid]["rooms"].get(rname, 0) + 1
    result = [{"name": v["name"], "username": v["username"], "total": v["total"], "rooms": v["rooms"]} for v in by_person.values()]
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


def get_cleaning_count_per_flatmate(chat_id: int):
    state = _load_space(chat_id)
    counts = {}
    for rec in state.get("cleaning_records", []):
        fid = rec["flatmate_id"]
        counts[fid] = counts.get(fid, 0) + 1
    return counts


def get_effective_cleaning_count_per_flatmate(chat_id: int):
    state = _load_space(chat_id)
    counts = {}
    for m in state.get("members", []):
        if not m.get("is_active", True):
            continue
        fid = m["id"]
        c = sum(1 for r in state.get("cleaning_records", []) if r["flatmate_id"] == fid)
        counts[fid] = c + (m.get("starting_offset") or 0)
    return counts


def get_room_cleaning_count_for_week(chat_id: int, room_id: int, start_date: str, end_date: str) -> int:
    """Count cleaning records for this room in the date range."""
    state = _load_space(chat_id)
    count = 0
    for rec in state.get("cleaning_records", []):
        if rec.get("room_id") != room_id:
            continue
        dt = rec.get("cleaned_at", "")[:10]
        if start_date <= dt <= end_date:
            count += 1
    return count


def get_room_weekly_quota(chat_id: int, room_id: int) -> int:
    """Max cleanings per week for this room (from times_per_month)."""
    room = next((r for r in get_rooms(chat_id) if r["id"] == room_id), None)
    if not room:
        return 1
    tpm = max(1, room.get("times_per_month", 1))
    return max(1, tpm // 4)


def get_last_cleaning_for_room_this_week(chat_id: int, room_id: int, flatmate_id: int, start_date: str, end_date: str):
    """Most recent cleaning record for this room by this flatmate in the week, or None."""
    state = _load_space(chat_id)
    candidates = []
    for rec in state.get("cleaning_records", []):
        if rec.get("room_id") != room_id or rec.get("flatmate_id") != flatmate_id:
            continue
        dt = rec.get("cleaned_at", "")[:10]
        if start_date <= dt <= end_date:
            candidates.append(rec)
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.get("cleaned_at", ""))


def can_record_room_cleaning(chat_id: int, room_id: int) -> tuple:
    """
    Check if room can accept another cleaning this week. Returns (True, None) or (False, "reason").
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    days_since_sunday = (now.weekday() + 1) % 7
    start_dt = now - timedelta(days=days_since_sunday)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = (start_dt + timedelta(days=6)).strftime("%Y-%m-%d")
    count = get_room_cleaning_count_for_week(chat_id, room_id, start_str, end_str)
    quota = get_room_weekly_quota(chat_id, room_id)
    if count >= quota:
        room = next((r for r in get_rooms(chat_id) if r["id"] == room_id), None)
        name = room["name"] if room else "This room"
        return False, f"{name} is already cleaned {quota} time{'s' if quota > 1 else ''} this week. Wait for next week."
    return True, None


def update_cleaning_record_types(chat_id: int, room_id: int, flatmate_id: int, new_types_done: list):
    """Update the most recent cleaning record for this room by this flatmate this week. No new points."""
    from datetime import datetime, timedelta
    now = datetime.now()
    days_since_sunday = (now.weekday() + 1) % 7
    start_dt = now - timedelta(days=days_since_sunday)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = (start_dt + timedelta(days=6)).strftime("%Y-%m-%d")
    last = get_last_cleaning_for_room_this_week(chat_id, room_id, flatmate_id, start_str, end_str)
    if not last:
        return False
    state = _load_space(chat_id)
    cleaned_at = last.get("cleaned_at")
    for rec in state.get("cleaning_records", []):
        if (rec.get("room_id") == room_id and rec.get("flatmate_id") == flatmate_id
                and rec.get("cleaned_at") == cleaned_at):
            rec["cleaning_types_done"] = list(new_types_done)
            _save_space(chat_id, state)
            return True
    return False


def _apply_soften_reminder_escalation(state: dict, flatmate_id: int) -> None:
    """Reset harsh tone for this flatmate's other pending tasks after they log a cleaning.
    Does not touch last_reminder_at or remind_on (same-day dedup + postpones stay correct)."""
    for a in state.get("assignments", []):
        if a.get("status") != "pending" or a.get("flatmate_id") != flatmate_id:
            continue
        if a.get("reminder_count", 0):
            a["reminder_count"] = 0


def _apply_auto_complete_assignments_for_cleaning(
    state: dict, room_id: int, cleaned_at_iso: str,
) -> set:
    """Close every pending assignment for this room with due_date on/before cleaning day — any assignee.
    If someone else cleaned, the room is done; rotation uses points, so lingering rows for others were wrong."""
    day = (cleaned_at_iso or "")[:10]
    if len(day) < 10:
        day = datetime.utcnow().strftime("%Y-%m-%d")
    closed_flatmates = set()
    for a in state.get("assignments", []):
        if a.get("status") != "pending":
            continue
        if a.get("room_id") != room_id:
            continue
        due = a.get("due_date") or ""
        if due and due <= day:
            a["status"] = "done"
            fid = a.get("flatmate_id")
            if fid is not None:
                closed_flatmates.add(fid)
    return closed_flatmates


def record_cleaning(chat_id: int, room_id: int, flatmate_id: int, was_assigned: bool = True, cleaning_types_done: list = None):
    ok, reason = can_record_room_cleaning(chat_id, room_id)
    if not ok:
        raise ValueError(reason)
    state = _load_space(chat_id)
    rec = {
        "room_id": room_id, "flatmate_id": flatmate_id,
        "cleaned_at": datetime.utcnow().isoformat(),
        "was_assigned": was_assigned,
    }
    if cleaning_types_done is not None:
        rec["cleaning_types_done"] = list(cleaning_types_done)
    state.setdefault("cleaning_records", []).append(rec)
    closed_for_room = _apply_auto_complete_assignments_for_cleaning(state, room_id, rec["cleaned_at"])
    for fid in closed_for_room | {flatmate_id}:
        if fid is not None:
            _apply_soften_reminder_escalation(state, fid)
    _save_space(chat_id, state)


def get_pending_assignments_for_date(chat_id: int, date_str: str):
    state = _load_space(chat_id)
    room_by_id = {r["id"]: r for r in state.get("rooms", [])}
    member_by_id = {m["id"]: m for m in state.get("members", [])}
    result = []
    for a in state.get("assignments", []):
        if a.get("status") != "pending":
            continue
        remind_on = a.get("remind_on")
        due = a.get("due_date")
        effective_remind = remind_on if remind_on is not None else due
        if not effective_remind or effective_remind > date_str:
            continue
        # Skip if already reminded today (avoids double-send on job retry)
        if a.get("last_reminder_at", "").startswith(date_str):
            continue
        room = room_by_id.get(a["room_id"], {})
        m = member_by_id.get(a["flatmate_id"], {})
        result.append({
            "id": a["id"], "room_id": a["room_id"], "flatmate_id": a["flatmate_id"],
            "reminder_count": a.get("reminder_count", 0),
            "room_name": room.get("name", "?"), "flatmate_name": m.get("name", "?"),
            "telegram_username": m.get("telegram_username", "?"),
        })
    return result


def set_remind_on(chat_id: int, assignment_id: int, date_str: str):
    state = _load_space(chat_id)
    for a in state.get("assignments", []):
        if a["id"] == assignment_id:
            a["remind_on"] = date_str
            break
    _save_space(chat_id, state)


def has_assignments_for_week(chat_id: int, start_date: str, end_date: str) -> bool:
    state = _load_space(chat_id)
    return any(start_date <= a.get("due_date", "") <= end_date for a in state.get("assignments", []))


def get_pending_assignments_raw_for_week(chat_id: int, start_date: str, end_date: str):
    """Return list of {room_id, flatmate_id} for pending assignments in range."""
    state = _load_space(chat_id)
    return [
        {"room_id": a["room_id"], "flatmate_id": a["flatmate_id"]}
        for a in state.get("assignments", [])
        if a.get("status") == "pending" and start_date <= a.get("due_date", "") <= end_date
    ]


def get_assignments_for_week(chat_id: int, start_date: str, end_date: str):
    state = _load_space(chat_id)
    room_by_id = {r["id"]: r for r in state.get("rooms", [])}
    member_by_id = {m["id"]: m for m in state.get("members", [])}
    result = []
    for a in state.get("assignments", []):
        if a.get("status") != "pending" or not (start_date <= a.get("due_date", "") <= end_date):
            continue
        room = room_by_id.get(a["room_id"], {})
        m = member_by_id.get(a["flatmate_id"], {})
        result.append({
            "id": a["id"], "due_date": a["due_date"], "room_name": room.get("name", "?"),
            "flatmate_name": m.get("name", "?"), "telegram_username": m.get("telegram_username", "?"),
        })
    result.sort(key=lambda x: (x["due_date"], x["room_name"]))
    return result


def clear_pending_assignments_for_week(chat_id: int, start_date: str, end_date: str) -> int:
    """Remove pending assignments in date range. Returns count removed."""
    state = _load_space(chat_id)
    before = len(state.get("assignments", []))
    state["assignments"] = [
        a for a in state.get("assignments", [])
        if a.get("status") != "pending" or not (start_date <= a.get("due_date", "") <= end_date)
    ]
    removed = before - len(state["assignments"])
    if removed:
        _save_space(chat_id, state)
    return removed


def create_assignment(chat_id: int, room_id: int, flatmate_id: int, due_date: str):
    state = _load_space(chat_id)
    aid = state["_next_assignment_id"]
    state["_next_assignment_id"] += 1
    state.setdefault("assignments", []).append({
        "id": aid, "room_id": room_id, "flatmate_id": flatmate_id, "due_date": due_date,
        "status": "pending", "reminder_count": 0, "remind_on": None,
    })
    _save_space(chat_id, state)


def update_assignment_status(chat_id: int, assignment_id: int, status: str):
    state = _load_space(chat_id)
    flatmate_id = None
    for a in state.get("assignments", []):
        if a["id"] == assignment_id:
            flatmate_id = a.get("flatmate_id")
            a["status"] = status
            break
    if status == "done" and flatmate_id is not None:
        _apply_soften_reminder_escalation(state, flatmate_id)
    _save_space(chat_id, state)


def increment_reminder_count(chat_id: int, assignment_id: int):
    state = _load_space(chat_id)
    for a in state.get("assignments", []):
        if a["id"] == assignment_id:
            a["reminder_count"] = a.get("reminder_count", 0) + 1
            a["last_reminder_at"] = datetime.utcnow().isoformat()
            break
    _save_space(chat_id, state)


def get_assignment_by_id(chat_id: int, assignment_id: int) -> Optional[dict]:
    state = _load_space(chat_id)
    room_by_id = {r["id"]: r for r in state.get("rooms", [])}
    member_by_id = {m["id"]: m for m in state.get("members", [])}
    for a in state.get("assignments", []):
        if a["id"] == assignment_id:
            room = room_by_id.get(a["room_id"], {})
            m = member_by_id.get(a["flatmate_id"], {})
            return {**a, "room_name": room.get("name", "?"), "flatmate_name": m.get("name", "?"), "telegram_username": m.get("telegram_username", "?")}
    return None


def get_flatmate_by_username(chat_id: int, username: str) -> Optional[dict]:
    state = _load_space(chat_id)
    uname = username.lstrip("@").strip().lower()
    for m in state.get("members", []):
        if m.get("telegram_username", "").lower() == uname and m.get("is_active", True):
            return dict(m)
    return None


def get_flatmate_with_fewest_cleanings_excluding(chat_id: int, exclude_ids: list) -> Optional[dict]:
    counts = get_effective_cleaning_count_per_flatmate(chat_id)
    active = [f for f in get_active_flatmates(chat_id) if f["id"] not in (exclude_ids or [])]
    if not active:
        active = get_active_flatmates(chat_id)
    if not active:
        return None
    best = min(active, key=lambda f: counts.get(f["id"], 0))
    return best


def get_chat_ids_with_bot_introduced():
    index = _load_index()
    return [e["chat_id"] for e in index.get("spaces", []) if e.get("bot_introduced")]


def space_has_zero_rooms(chat_id: int) -> bool:
    state = _load_space(chat_id)
    return not state.get("rooms")


def is_setup_reminder_silenced(chat_id: int) -> bool:
    state = _load_space(chat_id)
    if state.get("silent_forever"):
        return True
    until = state.get("silence_until")
    if not until:
        return False
    try:
        from datetime import date
        d = date.fromisoformat(str(until)[:10])
        return d >= datetime.utcnow().date()
    except (ValueError, TypeError):
        return False


def set_silence(chat_id: int, until_date: str = None, forever: bool = False):
    """Silence setup reminder. until_date: YYYY-MM-DD or None. forever: never remind until room added."""
    state = _load_space(chat_id)
    state["silence_until"] = until_date
    state["silent_forever"] = bool(forever)
    _save_space(chat_id, state)


def mark_setup_reminder_sent(chat_id: int, week_str: str):
    state = _load_space(chat_id)
    state["last_setup_reminder_week"] = week_str
    _save_space(chat_id, state)


def get_spaces_for_setup_reminder():
    """Spaces with 0 rooms, bot_introduced, not silenced, where it's Sunday 10am in their timezone."""
    from zoneinfo import ZoneInfo
    index = _load_index()
    now_utc = datetime.utcnow()
    result = []
    for e in index.get("spaces", []):
        if not e.get("bot_introduced"):
            continue
        chat_id = e["chat_id"]
        state = _load_space(chat_id)
        if state.get("rooms"):
            continue
        if state.get("silent_forever"):
            continue
        until = state.get("silence_until")
        if until:
            try:
                from datetime import date
                d = date.fromisoformat(str(until)[:10])
                if d >= now_utc.date():
                    continue
            except (ValueError, TypeError):
                pass
        tz_name = state.get("settings", {}).get("timezone", "Europe/Berlin")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Europe/Berlin")
        local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
        if local.weekday() != 6 or local.hour != 10:
            continue
        week_str = local.strftime("%Y-W%W")
        if state.get("last_setup_reminder_week") == week_str:
            continue
        result.append(chat_id)
    return result


def add_seen_in_group(chat_id: int, user_id: int, username: str, first_name: str):
    """Track user seen in group for 'Add member' suggestions. Keeps last 50."""
    state = _load_space(chat_id)
    seen = state.get("seen_in_group", [])
    seen = [s for s in seen if s.get("user_id") != user_id]
    seen.insert(0, {"user_id": user_id, "username": (username or "").lower(), "first_name": (first_name or "")[:50]})
    state["seen_in_group"] = seen[:50]
    _save_space(chat_id, state)


def get_seen_in_group(chat_id: int):
    """Users recently seen in group, excluding current members."""
    state = _load_space(chat_id)
    members_usernames = {m.get("telegram_username", "").lower() for m in state.get("members", []) if m.get("is_active", True)}
    result = []
    for s in state.get("seen_in_group", []):
        uname = (s.get("username") or "").lower()
        if uname and uname not in members_usernames:
            result.append(s)
    return result[:20]


def get_room_by_name(chat_id: int, name: str):
    state = _load_space(chat_id)
    lower = name.strip().lower()
    for r in state.get("rooms", []):
        if r["name"].lower() == lower:
            return r
    return None


def get_pending_assignment_for_room_in_week(chat_id: int, room_id: int, start_date: str, end_date: str):
    state = _load_space(chat_id)
    for a in state.get("assignments", []):
        if a["room_id"] == room_id and a.get("status") == "pending" and start_date <= a.get("due_date", "") <= end_date:
            return a
    return None


def get_full_cleaning_history(chat_id: int):
    state = _load_space(chat_id)
    room_by_id = {r["id"]: r["name"] for r in state.get("rooms", [])}
    member_by_id = {m["id"]: {"name": m["name"], "username": m["telegram_username"]} for m in state.get("members", [])}
    records = []
    for rec in state.get("cleaning_records", []):
        records.append({
            "date": rec.get("cleaned_at", "")[:10],
            "room_name": room_by_id.get(rec["room_id"], "?"),
            "flatmate_name": member_by_id.get(rec["flatmate_id"], {}).get("name", "?"),
            "flatmate_username": member_by_id.get(rec["flatmate_id"], {}).get("username", "?"),
            "cleaned_at": rec.get("cleaned_at", ""),
            "cleaning_types_done": rec.get("cleaning_types_done", []),
        })
    records.sort(key=lambda r: r["cleaned_at"], reverse=True)
    return records


# Compatibility alias
def get_or_create_group_chat(chat_id: int) -> dict:
    return get_or_create_space(chat_id)
