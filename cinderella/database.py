"""
SQLite database for cleaning history, assignments, and flatmate data.
All data is stored in a single file within the project for portability.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# Default DB path relative to project root
DB_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DB_DIR / "cinderella.db"


def ensure_db_dir():
    DB_DIR.mkdir(parents=True, exist_ok=True)


def get_connection():
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                config_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS flatmates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                telegram_username TEXT NOT NULL UNIQUE,
                telegram_id INTEGER,
                is_active INTEGER DEFAULT 1,
                replaced_at TIMESTAMP,
                replaced_by_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                times_per_month INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cleaning_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                flatmate_id INTEGER NOT NULL,
                cleaned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                was_assigned INTEGER DEFAULT 1,
                FOREIGN KEY (room_id) REFERENCES rooms(id),
                FOREIGN KEY (flatmate_id) REFERENCES flatmates(id)
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                flatmate_id INTEGER NOT NULL,
                due_date DATE NOT NULL,
                status TEXT DEFAULT 'pending',
                reminder_count INTEGER DEFAULT 0,
                remind_on DATE,
                last_reminder_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms(id),
                FOREIGN KEY (flatmate_id) REFERENCES flatmates(id)
            );

            CREATE TABLE IF NOT EXISTS group_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                bot_introduced INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS room_phrase_state (
                room_id INTEGER PRIMARY KEY,
                phrase_index INTEGER DEFAULT 0,
                phrase_order TEXT NOT NULL,
                FOREIGN KEY (room_id) REFERENCES rooms(id)
            );

            CREATE INDEX IF NOT EXISTS idx_assignments_due ON assignments(due_date);
            CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
        """)
        conn.commit()
        # Migration: add remind_on if not exists (for existing DBs)
        try:
            conn.execute("ALTER TABLE assignments ADD COLUMN remind_on DATE")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_assignments_remind_on ON assignments(remind_on)")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE flatmates ADD COLUMN starting_offset INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_cleaning_flatmate ON cleaning_records(flatmate_id);
            CREATE INDEX IF NOT EXISTS idx_cleaning_room ON cleaning_records(room_id);
        """)
        conn.commit()
    finally:
        conn.close()


def save_config(config: dict):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO config (id, config_json, updated_at) VALUES (1, ?, ?)",
            (json.dumps(config, ensure_ascii=False), datetime.utcnow().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def load_config() -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT config_json FROM config WHERE id = 1").fetchone()
        return json.loads(row["config_json"]) if row else None
    finally:
        conn.close()


def sync_flatmates_from_config(config: dict):
    """Sync flatmates from config. Add new ones, update names. Replaced (inactive) stay in DB."""
    conn = get_connection()
    try:
        existing = {r["telegram_username"]: r for r in conn.execute(
            "SELECT id, name, telegram_username FROM flatmates"
        ).fetchall()}

        for fm in config.get("flatmates", []):
            uname = fm["telegram_username"].lstrip("@")
            name = fm["name"]
            if uname in existing:
                # Update name if changed
                conn.execute(
                    "UPDATE flatmates SET name = ? WHERE telegram_username = ?",
                    (name, uname)
                )
            else:
                conn.execute(
                    "INSERT INTO flatmates (name, telegram_username) VALUES (?, ?)",
                    (name, uname)
                )
        conn.commit()
    finally:
        conn.close()


def replace_flatmate(old_username: str, new_name: str, new_username: str):
    """Replace a flatmate (e.g. someone moved out). Old stays in history. New person gets starting_offset = min(others) so they enter rotation immediately. Reshuffles phrase order."""
    conn = get_connection()
    try:
        old = conn.execute(
            "SELECT id FROM flatmates WHERE telegram_username = ? AND is_active = 1",
            (old_username.lstrip("@"),)
        ).fetchone()
        if not old:
            return False
        # Min real count among other active flatmates (excluding the one leaving)
        min_row = conn.execute("""
            SELECT COALESCE(MIN(cnt), 0) as min_cnt FROM (
                SELECT f.id, COUNT(c.id) as cnt
                FROM flatmates f
                LEFT JOIN cleaning_records c ON c.flatmate_id = f.id
                WHERE f.is_active = 1 AND f.id != ?
                GROUP BY f.id
            )
        """, (old["id"],)).fetchone()
        starting_offset = int(min_row["min_cnt"]) if min_row else 0
        cursor = conn.execute(
            "INSERT INTO flatmates (name, telegram_username, starting_offset) VALUES (?, ?, ?)",
            (new_name, new_username.lstrip("@"), starting_offset)
        )
        new_id = cursor.lastrowid
        conn.execute(
            "UPDATE flatmates SET is_active = 0, replaced_at = ?, replaced_by_id = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), new_id, old["id"])
        )
        conn.commit()
        reshuffle_phrase_orders()
        return True
    finally:
        conn.close()


def reshuffle_phrase_orders():
    """Shuffle phrase order for all rooms. Called when a flatmate is replaced."""
    import random
    conn = get_connection()
    try:
        rooms = conn.execute("SELECT id FROM rooms").fetchall()
        order = list(range(33))
        for r in rooms:
            shuffled = order.copy()
            random.shuffle(shuffled)
            conn.execute(
                """INSERT INTO room_phrase_state (room_id, phrase_index, phrase_order) VALUES (?, 0, ?)
                   ON CONFLICT(room_id) DO UPDATE SET phrase_index = 0, phrase_order = excluded.phrase_order""",
                (r["id"], json.dumps(shuffled))
            )
        conn.commit()
    finally:
        conn.close()


def get_and_advance_phrase(room_id: int, num_phrases: int = 33) -> int:
    """
    Get current phrase index for room, advance for next time. Returns 0-32.
    Creates state if missing (with shuffled order).
    """
    import random
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT phrase_index, phrase_order FROM room_phrase_state WHERE room_id = ?",
            (room_id,)
        ).fetchone()
        if not row:
            order = list(range(num_phrases))
            random.shuffle(order)
            conn.execute(
                "INSERT INTO room_phrase_state (room_id, phrase_index, phrase_order) VALUES (?, 0, ?)",
                (room_id, json.dumps(order))
            )
            conn.commit()
            return 0
        idx = row["phrase_index"]
        order = json.loads(row["phrase_order"])
        phrase_idx = order[idx % num_phrases]
        next_idx = (idx + 1) % num_phrases
        conn.execute(
            "UPDATE room_phrase_state SET phrase_index = ? WHERE room_id = ?",
            (next_idx, room_id)
        )
        conn.commit()
        return phrase_idx
    finally:
        conn.close()


def set_flatmate_telegram_id(username: str, telegram_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE flatmates SET telegram_id = ? WHERE telegram_username = ? AND is_active = 1",
            (telegram_id, username.lstrip("@"))
        )
        conn.commit()
    finally:
        conn.close()


def sync_rooms_from_config(config: dict):
    conn = get_connection()
    try:
        for room in config.get("rooms", []):
            conn.execute(
                """INSERT INTO rooms (name, times_per_month) VALUES (?, ?)
                   ON CONFLICT(name) DO UPDATE SET times_per_month = excluded.times_per_month""",
                (room["name"], room["times_per_month"])
            )
        conn.commit()
    finally:
        conn.close()


def get_active_flatmates():
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, name, telegram_username, telegram_id FROM flatmates WHERE is_active = 1"
        ).fetchall()]
    finally:
        conn.close()


def get_rooms():
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT id, name, times_per_month FROM rooms").fetchall()]
    finally:
        conn.close()


def get_monthly_stats(year: int, month: int) -> list:
    """
    Returns list of dicts: flatmate_name, telegram_username, total, room_breakdown.
    Sorted by total cleanings (most active first).
    """
    conn = get_connection()
    try:
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start = f"{year:04d}-{month:02d}-01"
        end = f"{year:04d}-{month:02d}-{last_day:02d}"

        rows = conn.execute("""
            SELECT f.id, f.name, f.telegram_username, r.name as room_name, COUNT(*) as cnt
            FROM cleaning_records c
            JOIN flatmates f ON c.flatmate_id = f.id
            JOIN rooms r ON c.room_id = r.id
            WHERE date(c.cleaned_at) BETWEEN ? AND ?
            GROUP BY f.id, f.name, f.telegram_username, r.id, r.name
        """, (start, end)).fetchall()

        # Aggregate by flatmate: {id: {name, username, total, rooms: {room: cnt}}}
        by_person = {}
        for r in rows:
            fid, name, username, room_name, cnt = r["id"], r["name"], r["telegram_username"], r["room_name"], r["cnt"]
            if fid not in by_person:
                by_person[fid] = {"name": name, "username": username, "total": 0, "rooms": {}}
            by_person[fid]["total"] += cnt
            by_person[fid]["rooms"][room_name] = cnt

        result = [
            {"name": v["name"], "username": v["username"], "total": v["total"], "rooms": v["rooms"]}
            for v in by_person.values()
        ]
        result.sort(key=lambda x: x["total"], reverse=True)
        return result
    finally:
        conn.close()


def get_cleaning_count_per_flatmate():
    """Returns {flatmate_id: total_cleanings} — real count only. Used for /stats."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT flatmate_id, COUNT(*) as cnt
            FROM cleaning_records
            GROUP BY flatmate_id
        """).fetchall()
        return {r["flatmate_id"]: r["cnt"] for r in rows}
    finally:
        conn.close()


def get_effective_cleaning_count_per_flatmate():
    """Returns {flatmate_id: effective_count} for fairness. Effective = real + starting_offset. New flatmates enter rotation immediately."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT f.id, COUNT(c.id) + COALESCE(f.starting_offset, 0) as effective
            FROM flatmates f
            LEFT JOIN cleaning_records c ON c.flatmate_id = f.id
            WHERE f.is_active = 1
            GROUP BY f.id
        """).fetchall()
        return {r["id"]: r["effective"] for r in rows}
    finally:
        conn.close()


def record_cleaning(room_id: int, flatmate_id: int, was_assigned: bool = True):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO cleaning_records (room_id, flatmate_id, was_assigned) VALUES (?, ?, ?)",
            (room_id, flatmate_id, 1 if was_assigned else 0)
        )
        conn.commit()
    finally:
        conn.close()


def get_or_create_group_chat(chat_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM group_chats WHERE chat_id = ?", (chat_id,)).fetchone()
        if row:
            return dict(row)
        conn.execute("INSERT INTO group_chats (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM group_chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def set_bot_introduced(chat_id: int):
    conn = get_connection()
    try:
        conn.execute("UPDATE group_chats SET bot_introduced = 1 WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()


def get_pending_assignments_for_date(date_str: str):
    """
    Get assignments that need a reminder on date_str.
    Includes: (remind_on = date) OR (remind_on IS NULL AND due_date = date)
    """
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT a.id, a.room_id, a.flatmate_id, a.reminder_count, r.name as room_name,
                   f.name as flatmate_name, f.telegram_username
            FROM assignments a
            JOIN rooms r ON a.room_id = r.id
            JOIN flatmates f ON a.flatmate_id = f.id
            WHERE a.status = 'pending'
              AND ((a.remind_on = ?) OR (a.remind_on IS NULL AND a.due_date = ?))
        """, (date_str, date_str)).fetchall()]
    finally:
        conn.close()


def set_remind_on(assignment_id: int, date_str: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE assignments SET remind_on = ? WHERE id = ?", (date_str, assignment_id))
        conn.commit()
    finally:
        conn.close()


def has_assignments_for_week(start_date: str, end_date: str) -> bool:
    """Check if any assignments exist for this week (planned or not)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM assignments WHERE due_date BETWEEN ? AND ? LIMIT 1",
            (start_date, end_date)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_assignments_for_week(start_date: str, end_date: str):
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""
            SELECT a.id, a.due_date, r.name as room_name, f.name as flatmate_name, f.telegram_username
            FROM assignments a
            JOIN rooms r ON a.room_id = r.id
            JOIN flatmates f ON a.flatmate_id = f.id
            WHERE a.due_date BETWEEN ? AND ? AND a.status = 'pending'
            ORDER BY a.due_date, r.name
        """, (start_date, end_date)).fetchall()]
    finally:
        conn.close()


def create_assignment(room_id: int, flatmate_id: int, due_date: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO assignments (room_id, flatmate_id, due_date) VALUES (?, ?, ?)",
            (room_id, flatmate_id, due_date)
        )
        conn.commit()
    finally:
        conn.close()


def update_assignment_status(assignment_id: int, status: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE assignments SET status = ? WHERE id = ?", (status, assignment_id))
        conn.commit()
    finally:
        conn.close()


def increment_reminder_count(assignment_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE assignments SET reminder_count = reminder_count + 1, last_reminder_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), assignment_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_assignment_by_id(assignment_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT a.*, r.name as room_name, f.name as flatmate_name, f.telegram_username, f.id as flatmate_id
            FROM assignments a
            JOIN rooms r ON a.room_id = r.id
            JOIN flatmates f ON a.flatmate_id = f.id
            WHERE a.id = ?
        """, (assignment_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_flatmate_by_username(username: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM flatmates WHERE telegram_username = ? AND is_active = 1",
            (username.lstrip("@"),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_flatmate_with_fewest_cleanings_excluding(exclude_ids: list) -> Optional[dict]:
    """Get active flatmate with fewest effective cleanings, excluding given IDs. Uses effective count (real + starting_offset)."""
    conn = get_connection()
    try:
        exclude = ",".join("?" * len(exclude_ids)) if exclude_ids else "0"
        params = exclude_ids if exclude_ids else []
        row = conn.execute(f"""
            SELECT f.id, f.name, f.telegram_username,
                   COUNT(c.id) + COALESCE(f.starting_offset, 0) as total_cleanings
            FROM flatmates f
            LEFT JOIN cleaning_records c ON c.flatmate_id = f.id
            WHERE f.is_active = 1 AND f.id NOT IN ({exclude})
            GROUP BY f.id
            ORDER BY total_cleanings ASC
            LIMIT 1
        """, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
