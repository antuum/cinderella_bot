"""
Store and manage user feedback (suggestions, comments, improvement ideas).
Saves to data/feedback.json and optionally forwards to admin.
"""

import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
FEEDBACK_PATH = DATA_DIR / "feedback.json"
LEGACY_PATH = DATA_DIR / "suggestions.json"


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_feedback() -> dict:
    """Load feedback data. Migrates from legacy suggestions.json if present."""
    if FEEDBACK_PATH.exists():
        try:
            with open(FEEDBACK_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    # One-time migration from legacy suggestions.json
    if LEGACY_PATH.exists():
        try:
            with open(LEGACY_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if "suggestions" in data:
                data["feedback"] = data.pop("suggestions", [])
            if "_next_id" not in data:
                data["_next_id"] = max((r.get("id", 0) for r in data.get("feedback", [])), default=0) + 1
            _ensure_dir()
            with open(FEEDBACK_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
        except (json.JSONDecodeError, IOError):
            pass
    return {"feedback": [], "_next_id": 1}


def _save_feedback(data: dict):
    _ensure_dir()
    with open(FEEDBACK_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_feedback(
    text: str,
    user_id: int,
    username: str = "",
    first_name: str = "",
    chat_id: int = None,
    source: str = "command",
) -> dict:
    """Store feedback (suggestion, comment, or general feedback). Returns the saved record."""
    data = _load_feedback()
    fid = data.get("_next_id", 1)
    data["_next_id"] = fid + 1
    record = {
        "id": fid,
        "text": str(text).strip()[:2000],
        "user_id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "chat_id": chat_id,
        "source": source,
        "created_at": datetime.utcnow().isoformat(),
    }
    data.setdefault("feedback", []).append(record)
    _save_feedback(data)
    return record
