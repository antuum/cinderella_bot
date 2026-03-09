"""
Telegram bot handlers for Cinderella.
"""

import json
import random
from pathlib import Path
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
)

import cinderella.database as db
import cinderella.messages as msg
import cinderella.scheduler as sched

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


def _load_config_file() -> dict:
    """Load config.json (used only for migration seeding or legacy import)."""
    for p in (CONFIG_PATH, PROJECT_ROOT / "config.example.json"):
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _main_menu_keyboard(chat_id: int = None):
    """Main quick-actions menu. chat_id used for consistency (not in callback)."""
    rows = [
        [InlineKeyboardButton("Schedule", callback_data="show_schedule"),
         InlineKeyboardButton("Stats", callback_data="show_stats")],
        [InlineKeyboardButton("Cleaned", callback_data="cleaned"),
         InlineKeyboardButton("History", callback_data="show_history")],
        [InlineKeyboardButton("Help", callback_data="show_help"),
         InlineKeyboardButton("Settings", callback_data="show_settings")],
    ]
    return InlineKeyboardMarkup(rows)


def _settings_keyboard(chat_id: int = None):
    """Settings menu: Create space or Edit (when already has setup)."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⚙ Settings", callback_data="show_settings")]])


def _settings_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Back", callback_data="show_settings")]])


def _track_seen_in_group(chat_id: int, user) -> None:
    """Track user for 'Add member' suggestions. No-op if not in group."""
    if not user or not chat_id or chat_id >= 0:
        return
    username = (user.username or "").strip()
    first_name = (user.first_name or "").strip()
    if user.id and (username or first_name):
        try:
            db.add_seen_in_group(chat_id, user.id, username, first_name)
        except Exception:
            pass


def _keyboard_setup_reminder_silent():
    """0-rooms: 'Make silent' options + Settings to add rooms."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Silent 2 weeks", callback_data="s_silence:2w"),
         InlineKeyboardButton("Silent 1 month", callback_data="s_silence:1m")],
        [InlineKeyboardButton("Silent 1 year", callback_data="s_silence:1y"),
         InlineKeyboardButton("Silent forever", callback_data="s_silence:forever")],
        [InlineKeyboardButton("⚙ Settings (add rooms)", callback_data="show_settings")],
    ])


async def _handle_show_settings(query, chat_id: int):
    """Show Create space (when empty) or Edit (when has setup)."""
    has_setup = db.space_has_setup(chat_id)
    if has_setup:
        text = "[>] **Settings** — Edit rooms and members."
        keyboard = [
            [InlineKeyboardButton("Edit rooms & members", callback_data="settings_edit")],
            [InlineKeyboardButton("← Menu", callback_data="show_menu")],
        ]
    else:
        text = "[>] **Create your shared space**\n\nAdd rooms, set cleaning frequency, and add members."
        keyboard = [
            [InlineKeyboardButton("Create space", callback_data="settings_create")],
            [InlineKeyboardButton("← Menu", callback_data="show_menu")],
        ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_settings_create(query, chat_id: int):
    """Step 1: Add room. Quick add or Custom."""
    text = "[>] **Add a room** — Choose or add custom (use /room Name for custom names)."
    rooms = db.get_rooms(chat_id)
    quick = ["Kitchen", "Bathroom", "Living room", "Hall"]
    keyboard = []
    row = []
    for name in quick:
        # Skip if already exists (case-insensitive)
        if not any(r["name"].lower() == name.lower() for r in rooms):
            row.append(InlineKeyboardButton(name, callback_data=f"s_add:{name}"))
        if len(row) >= 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Custom name (/room Name)", callback_data="s_add:custom")])
    keyboard.append([InlineKeyboardButton("← Back", callback_data="show_settings")])
    if not rooms:
        keyboard.append([InlineKeyboardButton("Skip (add later)", callback_data="s_create_done")])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_settings_add_room(query, chat_id: int, data: str):
    """Add room from quick-add or after custom. Then ask for times."""
    try:
        name = data.split(":", 1)[1]
    except IndexError:
        await query.answer("Error")
        return
    if name == "custom":
        await query.edit_message_text(
            "Use /room <Name> to add a room with a custom name.\nExample: /room Pantry",
            reply_markup=_settings_back_keyboard(),
        )
        return
    try:
        room = db.add_room(chat_id, name, 4)
    except ValueError as e:
        await query.answer(str(e))
        return
    text = f"[>] Added **{msg.escape_md(room['name'])}**. Set times per month:"
    keyboard = [
        [InlineKeyboardButton("1", callback_data=f"s_t:{room['id']}:1"),
         InlineKeyboardButton("2", callback_data=f"s_t:{room['id']}:2"),
         InlineKeyboardButton("3", callback_data=f"s_t:{room['id']}:3")],
        [InlineKeyboardButton("4", callback_data=f"s_t:{room['id']}:4"),
         InlineKeyboardButton("5", callback_data=f"s_t:{room['id']}:5"),
         InlineKeyboardButton("6", callback_data=f"s_t:{room['id']}:6")],
        [InlineKeyboardButton("7–28", callback_data=f"s_t_custom:{room['id']}")],
        [InlineKeyboardButton("← Back", callback_data="settings_create")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_settings_room_times(query, chat_id: int, data: str):
    """Show times selector for room (from settings_edit)."""
    try:
        room_id = int(data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer("Error")
        return
    room = next((r for r in db.get_rooms(chat_id) if r["id"] == room_id), None)
    if not room:
        await query.answer("Room not found")
        return
    text = f"[>] **{msg.escape_md(room['name'])}** — times per month:"
    keyboard = [
        [InlineKeyboardButton("1", callback_data=f"s_t:{room_id}:1"),
         InlineKeyboardButton("2", callback_data=f"s_t:{room_id}:2"),
         InlineKeyboardButton("3", callback_data=f"s_t:{room_id}:3")],
        [InlineKeyboardButton("4", callback_data=f"s_t:{room_id}:4"),
         InlineKeyboardButton("5", callback_data=f"s_t:{room_id}:5"),
         InlineKeyboardButton("6", callback_data=f"s_t:{room_id}:6")],
        [InlineKeyboardButton("7–28", callback_data=f"s_t_custom:{room_id}")],
        [InlineKeyboardButton("Remove room", callback_data=f"s_rm:{room_id}")],
        [InlineKeyboardButton("← Back", callback_data="settings_edit")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_settings_set_times(query, chat_id: int, data: str):
    """Set room times. s_t:room_id:n or s_t_custom:room_id."""
    parts = data.split(":")
    if len(parts) < 2:
        await query.answer("Error")
        return
    try:
        room_id = int(parts[1])
    except ValueError:
        await query.answer("Error")
        return
    if data.startswith("s_t_custom:"):
        text = "Select times per month (7–28):"
        keyboard = []
        row = []
        for n in range(7, 29):
            row.append(InlineKeyboardButton(str(n), callback_data=f"s_t:{room_id}:{n}"))
            if len(row) >= 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("← Back", callback_data=f"settings_room_times:{room_id}")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if len(parts) < 3:
        return
    try:
        tpm = int(parts[2])
    except ValueError:
        await query.answer("Invalid number")
        return
    try:
        db.update_room_times(chat_id, room_id, tpm)
    except ValueError as e:
        await query.answer(msg.TIMES_PER_MONTH_ERROR)
        return
    room = next((r for r in db.get_rooms(chat_id) if r["id"] == room_id), None)
    name = room["name"] if room else "Room"
    await query.answer(f"Set to {tpm} times/month")
    await _handle_settings_edit(query, chat_id)


# Fallback: 33 entries (one per GMT offset), extended descriptions. Override via config.json "timezones". No Moscow.
_DEFAULT_TIMEZONES = [
    ("GMT-12 Baker I., Howland I., UTC-12", "Etc/GMT+12"),
    ("GMT-11 Pago Pago, Niue, Midway", "Pacific/Pago_Pago"),
    ("GMT-10 Honolulu, Tahiti, Rarotonga", "Pacific/Honolulu"),
    ("GMT-9 Anchorage, Juneau, Nome", "America/Anchorage"),
    ("GMT-8 Los Angeles, Vancouver, Tijuana", "America/Los_Angeles"),
    ("GMT-7 Denver, Phoenix, Calgary", "America/Denver"),
    ("GMT-6 Chicago, Mexico City, Winnipeg", "America/Chicago"),
    ("GMT-5 New York, Toronto, Lima", "America/New_York"),
    ("GMT-4 Caracas, Santiago, La Paz", "America/Caracas"),
    ("GMT-3 São Paulo, Buenos Aires, Montevideo", "America/Sao_Paulo"),
    ("GMT-2 Noronha, South Georgia, Fernando de Noronha", "America/Noronha"),
    ("GMT-1 Azores, Cape Verde, Atlantic", "Atlantic/Azores"),
    ("GMT+0 London, Dublin, Accra", "Europe/London"),
    ("GMT+1 Berlin, Paris, Rome", "Europe/Berlin"),
    ("GMT+2 Cairo, Athens, Helsinki", "Africa/Cairo"),
    ("GMT+3 Istanbul, Nairobi, Baghdad", "Europe/Istanbul"),
    ("GMT+3:30 Tehran, Isfahan, Mashhad", "Asia/Tehran"),
    ("GMT+4 Dubai, Baku, Tbilisi", "Asia/Dubai"),
    ("GMT+4:30 Kabul, Herat, Afghanistan", "Asia/Kabul"),
    ("GMT+5 Karachi, Tashkent, Lahore", "Asia/Karachi"),
    ("GMT+5:30 Kolkata, Colombo, Mumbai", "Asia/Kolkata"),
    ("GMT+6 Dhaka, Almaty, Thimphu", "Asia/Dhaka"),
    ("GMT+6:30 Yangon, Cocos, Mandalay", "Asia/Yangon"),
    ("GMT+7 Bangkok, Jakarta, Hanoi", "Asia/Bangkok"),
    ("GMT+8 Singapore, Hong Kong, Perth", "Asia/Singapore"),
    ("GMT+9 Tokyo, Seoul, Sapporo", "Asia/Tokyo"),
    ("GMT+9:30 Adelaide, Darwin, Alice Springs", "Australia/Adelaide"),
    ("GMT+10 Sydney, Brisbane, Guam", "Australia/Sydney"),
    ("GMT+10:30 Lord Howe, Adelaide (DST), Broken Hill", "Australia/Lord_Howe"),
    ("GMT+11 Solomon Is., Noumea, Ponape", "Pacific/Guadalcanal"),
    ("GMT+12 Auckland, Fiji, Suva", "Pacific/Auckland"),
    ("GMT+13 Apia, Tonga, Phoenix Is.", "Pacific/Apia"),
    ("GMT+14 Kiritimati, Line Islands, Christmas I.", "Pacific/Kiritimati"),
]


async def _handle_settings_edit(query, chat_id: int):
    """Edit: list rooms (tap to set times), list members (tap to remove/replace)."""
    rooms = db.get_rooms(chat_id)
    members = db.get_active_flatmates(chat_id)
    settings = db.get_space_settings(chat_id)
    tz = settings.get("timezone", "Europe/Berlin")
    lines = [f"[>] **Edit shared space**\n_Timezone: {tz}_\n"]
    keyboard = []
    if rooms:
        lines.append("**Rooms** (tap to set cleaning frequency):")
        for r in rooms:
            keyboard.append([InlineKeyboardButton(f"{r['name']} ({r['times_per_month']}×/mo)", callback_data=f"settings_room_times:{r['id']}")])
    if members:
        lines.append("\n**Members** (tap to remove or replace):")
        for m in members:
            keyboard.append([InlineKeyboardButton(f"{m['name']} (@{m['telegram_username']})", callback_data=f"settings_member:{m['id']}")])
    keyboard.append([InlineKeyboardButton("Add room", callback_data="settings_create")])
    row_add = [InlineKeyboardButton("Add me", callback_data="settings_add_me")]
    seen = db.get_seen_in_group(chat_id)
    if seen:
        row_add.append(InlineKeyboardButton("Add from group", callback_data="s_add_from_group"))
    keyboard.append(row_add)
    keyboard.append([InlineKeyboardButton("Set timezone", callback_data="s_tz_show")])
    keyboard.append([InlineKeyboardButton("← Back", callback_data="show_settings")])
    text = "\n".join(lines) if lines else "No rooms or members yet."
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_settings_edit_members(query, chat_id: int, data: str):
    pass  # Handled by settings_edit


async def _handle_settings_member(query, chat_id: int, data: str):
    """Member options: remove or replace."""
    try:
        member_id = int(data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer("Error")
        return
    members = db.get_active_flatmates(chat_id)
    m = next((x for x in members if x["id"] == member_id), None)
    if not m:
        await query.answer("Member not found")
        return
    text = f"[>] **{msg.escape_md(m['name'])}** (@{m['telegram_username']})\n\nRemove from rotation or replace with someone else?"
    keyboard = [
        [InlineKeyboardButton("Remove", callback_data=f"s_mem_rm:{member_id}"),
         InlineKeyboardButton("Replace", callback_data=f"s_mem_rp:{member_id}")],
        [InlineKeyboardButton("← Back", callback_data="settings_edit")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_settings_add_me(query, chat_id: int):
    """Add the clicker as member."""
    user = query.from_user
    if not user:
        await query.answer("Cannot add you.")
        return
    username = (user.username or "").lstrip("@")
    if not username:
        await query.edit_message_text(
            "You need a Telegram username to be added. Set one in Telegram Settings → Username.",
            reply_markup=_settings_back_keyboard(),
        )
        return
    name = (user.first_name or "").strip() or username
    try:
        db.add_member(chat_id, name, username)
    except ValueError as e:
        await query.answer(str(e))
        return
    await query.answer("Added!")
    await _handle_settings_edit(query, chat_id)


def _menu_back_keyboard():
    """Single row: back to menu."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Menu", callback_data="show_menu")]])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "group" and update.effective_chat.type != "supergroup":
        await update.message.reply_text(
            "[>] I'm Cinderella. Add me to a group chat to manage your shared space's cleaning schedule. "
            "I only work in groups. Use /help to see commands."
        )
        return
    chat_id = update.effective_chat.id
    _track_seen_in_group(chat_id, update.effective_user)
    title = (update.effective_chat.title or "").strip()
    gc = db.get_or_create_space(chat_id, title)
    if gc["bot_introduced"]:
        if db.space_has_setup(chat_id):
            await update.message.reply_text(
                msg.MENU_TEXT,
                parse_mode="Markdown",
                reply_markup=_main_menu_keyboard(chat_id),
            )
            return
        # Bot introduced but no setup yet — show settings prompt
        await update.message.reply_text(
            msg.SETTINGS_FIRST_MESSAGE,
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(chat_id),
        )
        return
    db.set_bot_introduced(chat_id)
    config = _load_config_file()
    if config:
        db.sync_flatmates_from_config(chat_id, config)
        db.sync_rooms_from_config(chat_id, config)
    flatmates = db.get_active_flatmates(chat_id)
    counts = db.get_cleaning_count_per_flatmate(chat_id)
    if db.space_has_zero_rooms(chat_id):
        await update.message.reply_text(
            msg.SETUP_REMINDER_MESSAGE,
            parse_mode="Markdown",
            reply_markup=_keyboard_setup_reminder_silent(),
        )
    elif db.space_has_setup(chat_id):
        intro = msg.build_intro_message(flatmates, counts)
        await update.message.reply_text(
            intro,
            parse_mode="Markdown",
            reply_markup=_main_menu_keyboard(chat_id),
        )
    else:
        await update.message.reply_text(
            msg.SETTINGS_FIRST_MESSAGE,
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(chat_id),
        )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu with inline buttons. Pin this message for quick access."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Add me to a group chat first. Use /help.")
        return
    chat_id = update.effective_chat.id
    _track_seen_in_group(chat_id, update.effective_user)
    if db.space_has_zero_rooms(chat_id):
        await update.message.reply_text(
            msg.SETUP_REMINDER_MESSAGE,
            parse_mode="Markdown",
            reply_markup=_keyboard_setup_reminder_silent(),
        )
        return
    if not db.space_has_setup(chat_id):
        await update.message.reply_text(
            msg.SETTINGS_FIRST_MESSAGE,
            parse_mode="Markdown",
            reply_markup=_settings_keyboard(chat_id),
        )
        return
    await update.message.reply_text(
        msg.MENU_TEXT,
        parse_mode="Markdown",
        reply_markup=_main_menu_keyboard(chat_id),
    )


async def cmd_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Replace a member (someone moved out).
    Usage: /replace @old_username NewName @new_username
    Example: /replace @alice_old Alice @alice_new
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /replace @old_username NewName @new_username\n"
            "Example: /replace @alice_old Alice @alice_new"
        )
        return
    old_user = args[0].lstrip("@")
    new_name = args[1]
    new_user = args[2].lstrip("@")
    if db.replace_flatmate(chat_id, old_user, new_name, new_user):
        await update.message.reply_text(
            f"[OK] Replaced @{old_user} with {new_name} (@{new_user}). "
            "The previous member stays in history."
        )
        flatmates = db.get_active_flatmates(chat_id)
        counts = db.get_cleaning_count_per_flatmate(chat_id)
        tags = " ".join(f"@{msg.escape_md(f['telegram_username'])}" for f in flatmates)
        lines = [f"[ROSTER] **Updated.** {tags}\n---", "[STATS] **Current counters**\n"]
        for f in flatmates:
            c = counts.get(f["id"], 0)
            lines.append(f"  [>] {msg.escape_md(f['name'])} (@{msg.escape_md(f['telegram_username'])}): {c} cleanings")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Could not find @{old_user} in the member list.")


async def cmd_cleaned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Log proactive cleaning: I cleaned a room without being reminded.
    Usage: /cleaned Kitchen  or  /cleaned Bathroom
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        rooms = [r["name"] for r in db.get_rooms(chat_id)]
        await update.message.reply_text(
            f"Usage: /cleaned <room>\n"
            f"Example: /cleaned Kitchen\n"
            f"Rooms: {', '.join(rooms) if rooms else '—'}"
        )
        return
    room_name = " ".join(args).strip()
    room = db.get_room_by_name(chat_id, room_name)
    if not room:
        rooms = [r["name"] for r in db.get_rooms(chat_id)]
        await update.message.reply_text(
            f"Room '{room_name}' not found. Rooms: {', '.join(rooms) if rooms else '—'}"
        )
        return
    username = (update.effective_user.username or "").lstrip("@") if update.effective_user else ""
    flatmate = db.get_flatmate_by_username(chat_id, username)
    if not flatmate:
        await update.message.reply_text(msg.CLEANED_NOT_MEMBER, reply_markup=_menu_back_keyboard())
        return

    start, end = sched.get_week_range(datetime.now())
    assignment = db.get_pending_assignment_for_room_in_week(chat_id, room["id"], start, end)
    if assignment:
        db.update_assignment_status(chat_id, assignment["id"], "done")
    db.record_cleaning(chat_id, room["id"], flatmate["id"], was_assigned=False)
    counts = db.get_cleaning_count_per_flatmate(chat_id)
    points = counts.get(flatmate["id"], 0)

    msg_text = msg.PROACTIVE_CLEANED_RESPONSE.format(
        username=msg.escape_md(username),
        room=msg.escape_md(room["name"]),
        points=points,
    )
    await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=_menu_back_keyboard())


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show cleaning stats per member."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    flatmates = db.get_active_flatmates(chat_id)
    counts = db.get_cleaning_count_per_flatmate(chat_id)
    if not flatmates:
        await update.message.reply_text("No members yet. Set up your space via Settings.")
        return
    lines = ["[STATS] **Cleaning stats**\n---\n"]
    for f in flatmates:
        c = counts.get(f["id"], 0)
        lines.append(f"  [>] {msg.escape_md(f['name'])} (@{msg.escape_md(f['telegram_username'])}): {c} cleanings")
    keyboard = [[InlineKeyboardButton("History", callback_data="show_history"), InlineKeyboardButton("Menu", callback_data="show_menu")]]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all commands with short descriptions."""
    await update.message.reply_text(
        msg.HELP_TEXT.strip(),
        parse_mode="Markdown",
        reply_markup=_menu_back_keyboard(),
    )


async def cmd_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add a room with custom name.
    Usage: /room Name  or  /room "Living Room"
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /room <Name>\nExample: /room Pantry"
        )
        return
    name = " ".join(args).strip()
    if not name or len(name) > 100:
        await update.message.reply_text("Room name must be 1–100 characters.")
        return
    existing = db.get_room_by_name(chat_id, name)
    if existing:
        await update.message.reply_text(f"Room '{name}' already exists.")
        return
    try:
        room = db.add_room(chat_id, name, 4)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    await update.message.reply_text(
        f"[OK] Added **{msg.escape_md(room['name'])}** (4×/month). Change via Settings → Edit.",
        parse_mode="Markdown",
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add a member to the shared space.
    Usage: /add @username Name  or  /add @username
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /add @username Name\nExample: /add @alice Alice"
        )
        return
    username = args[0].lstrip("@").strip()
    if not username or not username.replace("_", "").isalnum():
        await update.message.reply_text("Invalid username. Use @username format.")
        return
    name = args[1] if len(args) > 1 else username
    name = name.strip()
    if not name or len(name) > 50:
        name = username
    existing = db.get_flatmate_by_username(chat_id, username)
    if existing:
        await update.message.reply_text(f"@{msg.escape_md(username)} is already in the member list.", parse_mode="Markdown")
        return
    try:
        db.add_member(chat_id, name, username)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    await update.message.reply_text(f"[OK] Added {msg.escape_md(name)} (@{msg.escape_md(username)}).", parse_mode="Markdown")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full cleaning history with total points per person."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    flatmates = db.get_active_flatmates(chat_id)
    counts = db.get_cleaning_count_per_flatmate(chat_id)
    history = db.get_full_cleaning_history(chat_id)
    if not flatmates and not history:
        await update.message.reply_text("No history yet.")
        return
    stats_lines = []
    for f in flatmates:
        c = counts.get(f["id"], 0)
        stats_lines.append(f"  [>] {msg.escape_md(f['name'])} (@{msg.escape_md(f['telegram_username'])}): {c} cleanings\n")
    history_lines = [msg.format_history_line(r) for r in history]
    text = msg.format_history(stats_lines, history_lines)
    keyboard = [[InlineKeyboardButton("← Stats", callback_data="show_stats"), InlineKeyboardButton("Menu", callback_data="show_menu")]]
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show this week's schedule."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your shared space's group chat.")
        return
    chat_id = update.effective_chat.id
    if not db.space_has_setup(chat_id):
        await update.message.reply_text(msg.SETTINGS_FIRST_MESSAGE, reply_markup=_settings_keyboard(chat_id))
        return
    sched.ensure_assignments_exist(chat_id)
    start, end = sched.get_week_range(datetime.now())
    assignments = db.get_assignments_for_week(chat_id, start, end)
    text = msg.WEEKLY_HEADER.format(
        start=msg.format_date_display(start),
        end=msg.format_date_display(end),
    )
    if not assignments:
        text += msg.WEEKLY_EMPTY
    else:
        for a in assignments:
            text += msg.WEEKLY_LINE.format(
                date=msg.format_date_display(a["due_date"]),
                room=msg.escape_md(a["room_name"]),
                username=msg.escape_md(a["telegram_username"]),
            )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_menu_back_keyboard())


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data:
        return

    chat_id = query.message.chat_id if query.message else None
    if chat_id is None:
        return
    _track_seen_in_group(chat_id, query.from_user)

    # Settings flow (handled first)
    if data == "show_settings":
        await _handle_show_settings(query, chat_id)
        return

    if data == "settings_create":
        await _handle_settings_create(query, chat_id)
        return

    if data == "settings_edit":
        await _handle_settings_edit(query, chat_id)
        return

    if data.startswith("s_add:"):
        await _handle_settings_add_room(query, chat_id, data)
        return

    if data.startswith("settings_room_times:"):
        await _handle_settings_room_times(query, chat_id, data)
        return

    if data.startswith("s_t:") or data.startswith("s_t_custom:"):
        await _handle_settings_set_times(query, chat_id, data)
        return

    if data.startswith("s_rm:"):
        try:
            room_id = int(data.split(":")[1])
            db.remove_room(chat_id, room_id)
            await query.answer("Room removed")
            await _handle_settings_edit(query, chat_id)
        except (ValueError, IndexError):
            await query.answer("Error")
        return

    if data.startswith("settings_member:"):
        await _handle_settings_member(query, chat_id, data)
        return

    if data.startswith("s_mem_rm:"):
        try:
            member_id = int(data.split(":")[1])
            members = db.get_active_flatmates(chat_id)
            m = next((x for x in members if x["id"] == member_id), None)
            if m:
                db.remove_member(chat_id, m["telegram_username"])
                await query.answer("Member removed")
            await _handle_settings_edit(query, chat_id)
        except (ValueError, IndexError):
            await query.answer("Error")
        return

    if data.startswith("s_mem_rp:"):
        await query.edit_message_text(
            "Use /replace @old_username NewName @new_username to replace a member.",
            reply_markup=_settings_back_keyboard(),
        )
        return

    if data == "settings_add_me":
        await _handle_settings_add_me(query, chat_id)
        return

    if data == "s_add_from_group":
        seen = db.get_seen_in_group(chat_id)
        if not seen:
            await query.edit_message_text("No one from the group has interacted yet.", reply_markup=_settings_back_keyboard())
            return
        text = "[>] **Add member** — tap to add:"
        keyboard = []
        for s in seen[:15]:
            label = f"{(s.get('first_name') or '').strip() or s.get('username', '?')}"
            if s.get("username"):
                label += f" @{s['username']}"
            cb = f"s_add_seen:{s.get('username', '')}"[:64]
            if cb.endswith(":"):
                continue
            keyboard.append([InlineKeyboardButton(label, callback_data=cb)])
        keyboard.append([InlineKeyboardButton("← Back", callback_data="settings_edit")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("s_add_seen:"):
        username = data.split(":", 1)[1].strip()
        if not username:
            await query.answer("Invalid")
            return
        name = username
        for s in db.get_seen_in_group(chat_id):
            if (s.get("username") or "").lower() == username.lower():
                name = (s.get("first_name") or username).strip() or username
                break
        try:
            db.add_member(chat_id, name, username)
            await query.answer("Added!")
        except ValueError as e:
            await query.answer(str(e))
            return
        await _handle_settings_edit(query, chat_id)
        return

    if data == "s_tz_show":
        text = "[>] **Set timezone** (Sunday 10:00 = setup reminder)\n\n" + msg.TIMEZONE_DEFAULT_NOTICE
        timezones = _load_config_file().get("timezones", _DEFAULT_TIMEZONES)
        keyboard = [[InlineKeyboardButton(label, callback_data=f"s_tz:{tz}")] for label, tz in timezones]
        keyboard.append([InlineKeyboardButton("← Back", callback_data="settings_edit")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("s_tz:"):
        tz = data.split(":", 1)[1].strip()
        db.save_space_settings(chat_id, {"timezone": tz})
        await query.answer(f"Timezone set to {tz}")
        await _handle_settings_edit(query, chat_id)
        return

    if data == "s_create_done":
        await _handle_settings_edit(query, chat_id)
        return

    if data.startswith("s_silence:"):
        duration = data.split(":", 1)[1]
        now = datetime.now()
        if duration == "forever":
            db.set_silence(chat_id, forever=True)
            await query.answer("Silenced until you add a room.")
        elif duration == "2w":
            until = (now + timedelta(days=14)).strftime("%Y-%m-%d")
            db.set_silence(chat_id, until_date=until)
            await query.answer("Silenced for 2 weeks.")
        elif duration == "1m":
            until = (now + timedelta(days=30)).strftime("%Y-%m-%d")
            db.set_silence(chat_id, until_date=until)
            await query.answer("Silenced for 1 month.")
        elif duration == "1y":
            until = (now + timedelta(days=365)).strftime("%Y-%m-%d")
            db.set_silence(chat_id, until_date=until)
            await query.answer("Silenced for 1 year.")
        else:
            await query.answer("Unknown option")
            return
        await query.edit_message_text("[>] Setup reminders silenced. Add a room via Settings to start.", reply_markup=_settings_keyboard(chat_id))
        return

    if data == "show_menu":
        if db.space_has_zero_rooms(chat_id):
            await query.edit_message_text(
                msg.SETUP_REMINDER_MESSAGE,
                parse_mode="Markdown",
                reply_markup=_keyboard_setup_reminder_silent(),
            )
            return
        if not db.space_has_setup(chat_id):
            await query.edit_message_text(
                msg.SETTINGS_FIRST_MESSAGE,
                parse_mode="Markdown",
                reply_markup=_settings_keyboard(chat_id),
            )
            return
        await query.edit_message_text(
            msg.MENU_TEXT,
            parse_mode="Markdown",
            reply_markup=_main_menu_keyboard(chat_id),
        )
        return

    if data == "show_schedule":
        if db.space_has_zero_rooms(chat_id):
            await query.edit_message_text(msg.SETUP_REMINDER_MESSAGE, reply_markup=_keyboard_setup_reminder_silent())
            return
        if not db.space_has_setup(chat_id):
            await query.edit_message_text(msg.SETTINGS_FIRST_MESSAGE, reply_markup=_settings_keyboard(chat_id))
            return
        sched.ensure_assignments_exist(chat_id)
        start, end = sched.get_week_range(datetime.now())
        assignments = db.get_assignments_for_week(chat_id, start, end)
        text = msg.WEEKLY_HEADER.format(
            start=msg.format_date_display(start),
            end=msg.format_date_display(end),
        )
        if not assignments:
            text += msg.WEEKLY_EMPTY
        else:
            for a in assignments:
                text += msg.WEEKLY_LINE.format(
                    date=msg.format_date_display(a["due_date"]),
                    room=msg.escape_md(a["room_name"]),
                    username=msg.escape_md(a["telegram_username"]),
                )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_menu_back_keyboard())
        return

    if data == "show_help":
        await query.edit_message_text(
            msg.HELP_TEXT.strip(),
            parse_mode="Markdown",
            reply_markup=_menu_back_keyboard(),
        )
        return

    if data == "cleaned":
        if db.space_has_zero_rooms(chat_id):
            await query.edit_message_text(msg.SETUP_REMINDER_MESSAGE, reply_markup=_keyboard_setup_reminder_silent())
            return
        rooms = db.get_rooms(chat_id)
        if not rooms:
            await query.edit_message_text(msg.CLEANED_CHOOSE_ROOM + "\n\nNo rooms yet. Add them via Settings.", reply_markup=_menu_back_keyboard())
            return
        keyboard = []
        row = []
        for r in rooms:
            row.append(InlineKeyboardButton(r["name"], callback_data=f"cleaned:{r['id']}"))
            if len(row) >= 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("← Menu", callback_data="show_menu")])
        await query.edit_message_text(
            msg.CLEANED_CHOOSE_ROOM,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("cleaned:"):
        try:
            room_id = int(data.split(":")[1])
        except (ValueError, IndexError):
            await query.answer("Error")
            return
        room = next((r for r in db.get_rooms(chat_id) if r["id"] == room_id), None)
        if not room:
            await query.answer("Room not found")
            return
        username = (query.from_user.username or "").lstrip("@") if query.from_user else ""
        flatmate = db.get_flatmate_by_username(chat_id, username)
        if not flatmate:
            await query.edit_message_text(msg.CLEANED_NOT_MEMBER, reply_markup=_menu_back_keyboard())
            return
        start, end = sched.get_week_range(datetime.now())
        assignment = db.get_pending_assignment_for_room_in_week(chat_id, room_id, start, end)
        if assignment:
            db.update_assignment_status(chat_id, assignment["id"], "done")
        db.record_cleaning(chat_id, room_id, flatmate["id"], was_assigned=False)
        counts = db.get_cleaning_count_per_flatmate(chat_id)
        points = counts.get(flatmate["id"], 0)
        text = msg.PROACTIVE_CLEANED_RESPONSE.format(
            username=msg.escape_md(username),
            room=msg.escape_md(room["name"]),
            points=points,
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_menu_back_keyboard())
        return

    if data == "show_history":
        if db.space_has_zero_rooms(chat_id):
            await query.edit_message_text(msg.SETUP_REMINDER_MESSAGE, reply_markup=_keyboard_setup_reminder_silent())
            return
        flatmates = db.get_active_flatmates(chat_id)
        counts = db.get_cleaning_count_per_flatmate(chat_id)
        history = db.get_full_cleaning_history(chat_id)
        if not flatmates and not history:
            await query.edit_message_text("No history yet.", reply_markup=_menu_back_keyboard())
        else:
            stats_lines = []
            for f in flatmates:
                c = counts.get(f["id"], 0)
                stats_lines.append(f"  [>] {msg.escape_md(f['name'])} (@{msg.escape_md(f['telegram_username'])}): {c} cleanings\n")
            history_lines = [msg.format_history_line(r) for r in history]
            text = msg.format_history(stats_lines, history_lines)
            keyboard = [[InlineKeyboardButton("← Stats", callback_data="show_stats"), InlineKeyboardButton("Menu", callback_data="show_menu")]]
            await query.edit_message_text(
                text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        return

    if data == "show_stats":
        if db.space_has_zero_rooms(chat_id):
            await query.edit_message_text(msg.SETUP_REMINDER_MESSAGE, reply_markup=_keyboard_setup_reminder_silent())
            return
        flatmates = db.get_active_flatmates(chat_id)
        counts = db.get_cleaning_count_per_flatmate(chat_id)
        if not flatmates:
            await query.edit_message_text("No members yet. Set up via Settings.", reply_markup=_menu_back_keyboard())
        else:
            lines = ["[STATS] **Cleaning stats**\n---\n"]
            for f in flatmates:
                c = counts.get(f["id"], 0)
                lines.append(f"  [>] {msg.escape_md(f['name'])} (@{msg.escape_md(f['telegram_username'])}): {c} cleanings")
            keyboard = [[InlineKeyboardButton("History", callback_data="show_history"), InlineKeyboardButton("Menu", callback_data="show_menu")]]
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        return

    if ":" not in data:
        await query.edit_message_text("Unknown action. Use /menu.", reply_markup=_menu_back_keyboard())
        return
    action, assignment_id_str = data.split(":", 1)
    try:
        assignment_id = int(assignment_id_str)
    except ValueError:
        return

    assignment = db.get_assignment_by_id(chat_id, assignment_id)
    if not assignment:
        await query.edit_message_text("Assignment not found. Use /menu.", reply_markup=_menu_back_keyboard())
        return
    if assignment["status"] != "pending":
        await query.edit_message_text("This task was already handled.")
        return

    # Who clicked?
    clicker_id = query.from_user.id if query.from_user else None
    clicker_username = (query.from_user.username or "").lstrip("@") if query.from_user else ""
    assigned_username = assignment["telegram_username"]
    room_name = assignment["room_name"]
    room_id = assignment["room_id"]
    due_date = assignment["due_date"]

    if action == "done":
        clicker = db.get_flatmate_by_username(chat_id, clicker_username)
        was_assigned = clicker and clicker["id"] == assignment["flatmate_id"]

        if clicker:
            db.record_cleaning(chat_id, room_id, clicker["id"], was_assigned=was_assigned)
        else:
            db.record_cleaning(chat_id, room_id, assignment["flatmate_id"], was_assigned=True)

        db.update_assignment_status(chat_id, assignment_id, "done")

        # Message
        if clicker and not was_assigned:
            done_msg = random.choice(msg.DONE_BY_OTHER_MESSAGES).format(
                username=msg.escape_md(clicker_username),
                room=msg.escape_md(room_name),
                next_person="?",  # TODO: could compute next
                next_room="?",
            )
        else:
            done_msg = random.choice(msg.DONE_MESSAGES).format(
                username=msg.escape_md(assigned_username),
                room=msg.escape_md(room_name),
                next_person="?",
                next_room="?",
            )
        await query.edit_message_text(done_msg, parse_mode="Markdown")

    elif action == "not_today":
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        db.set_remind_on(chat_id, assignment_id, tomorrow)
        if context.job_queue:
            context.job_queue.run_once(
                _reminder_job,
                when=datetime.now() + timedelta(days=1),
                data={"assignment_id": assignment_id, "chat_id": chat_id},
            )
        reply = msg.NOT_TODAY_REPLY.format(username=msg.escape_md(assigned_username))
        await query.edit_message_text(reply, parse_mode="Markdown")

    elif action == "three_days":
        in_three = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        db.set_remind_on(chat_id, assignment_id, in_three)
        if context.job_queue:
            context.job_queue.run_once(
                _reminder_job,
                when=datetime.now() + timedelta(days=3),
                data={"assignment_id": assignment_id, "chat_id": chat_id},
            )
        reply = msg.THREE_DAYS_REPLY.format(username=msg.escape_md(assigned_username))
        await query.edit_message_text(reply, parse_mode="Markdown")

    elif action == "skip_week":
        db.update_assignment_status(chat_id, assignment_id, "skipped")
        exclude = [assignment["flatmate_id"]]
        next_person = db.get_flatmate_with_fewest_cleanings_excluding(chat_id, exclude)
        if next_person:
            db.create_assignment(chat_id, room_id, next_person["id"], due_date)
            reply = msg.SKIP_REASSIGN.format(
                username=msg.escape_md(assigned_username),
                new_username=msg.escape_md(next_person["telegram_username"]),
                room=msg.escape_md(room_name),
            )
            await query.edit_message_text(reply, parse_mode="Markdown")
        else:
            reply = msg.SKIP_WEEK_REPLY.format(username=msg.escape_md(assigned_username), room=msg.escape_md(room_name))
            await query.edit_message_text(reply, parse_mode="Markdown")

    else:
        await query.edit_message_text("Unknown action. Use /menu.", reply_markup=_menu_back_keyboard())


async def _reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Job callback for deferred reminders."""
    job = context.job
    assignment_id = job.data.get("assignment_id")
    chat_id = job.data.get("chat_id")
    if assignment_id and chat_id:
        await send_reminder(context, chat_id, assignment_id)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, assignment_id: int):
    """Send reminder for an assignment (used by job_queue)."""
    assignment = db.get_assignment_by_id(chat_id, assignment_id)
    if not assignment or assignment["status"] != "pending":
        return
    reminder_count = assignment["reminder_count"]
    phrase_idx = db.get_and_advance_phrase(chat_id, assignment["room_id"])
    text = msg.get_reminder_text(
        assignment["room_name"],
        assignment["telegram_username"],
        reminder_count,
        phrase_idx,
    )
    keyboard = [
        [
            InlineKeyboardButton("Not today", callback_data=f"not_today:{assignment_id}"),
            InlineKeyboardButton("3 more days", callback_data=f"three_days:{assignment_id}"),
        ],
        [
            InlineKeyboardButton("Skip the week", callback_data=f"skip_week:{assignment_id}"),
            InlineKeyboardButton("Done [OK]", callback_data=f"done:{assignment_id}"),
        ],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    db.increment_reminder_count(chat_id, assignment_id)


def _job_reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    assignment_id = job.data.get("assignment_id")
    chat_id = job.data.get("chat_id", job.chat_id)
    if assignment_id and chat_id:
        import asyncio
        asyncio.create_task(send_reminder(context, chat_id, assignment_id))


async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Called daily by job_queue. Send reminders for today's assignments (per space)."""
    today = datetime.now().strftime("%Y-%m-%d")
    chat_ids = db.get_chat_ids_with_bot_introduced()

    for chat_id in chat_ids:
        if db.space_has_zero_rooms(chat_id):
            continue
        sched.ensure_assignments_exist(chat_id)
        assignments = db.get_pending_assignments_for_date(chat_id, today)
        for a in assignments:
            phrase_idx = db.get_and_advance_phrase(chat_id, a["room_id"])
            text = msg.get_reminder_text(
                a["room_name"],
                a["telegram_username"],
                a["reminder_count"],
                phrase_idx,
            )
            keyboard = [
                [
                    InlineKeyboardButton("Not today", callback_data=f"not_today:{a['id']}"),
                    InlineKeyboardButton("3 more days", callback_data=f"three_days:{a['id']}"),
                ],
                [
                    InlineKeyboardButton("Skip the week", callback_data=f"skip_week:{a['id']}"),
                    InlineKeyboardButton("Done [OK]", callback_data=f"done:{a['id']}"),
                ],
            ]
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception:
                pass
            db.increment_reminder_count(chat_id, a["id"])


async def send_setup_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Weekly (Sunday 10am local): remind spaces with 0 rooms to set up. Per-space timezone."""
    chat_ids = db.get_spaces_for_setup_reminder()
    from datetime import date
    week_str = date.today().strftime("%Y-W%W")
    for chat_id in chat_ids:
        text = msg.SETUP_REMINDER_MESSAGE
        keyboard = _keyboard_setup_reminder_silent()
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            db.mark_setup_reminder_sent(chat_id, week_str)
        except Exception:
            pass


async def send_monthly_stats(context: ContextTypes.DEFAULT_TYPE):
    """Send monthly stats at end of month (runs daily, checks if last day) — per space."""
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    if tomorrow.month == today.month:
        return
    year, month = today.year, today.month
    chat_ids = db.get_chat_ids_with_bot_introduced()

    for chat_id in chat_ids:
        if db.space_has_zero_rooms(chat_id):
            continue
        stats = db.get_monthly_stats(chat_id, year, month)
        text = msg.format_monthly_stats(year, month, stats)
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception:
            pass


async def send_weekly_schedule(context: ContextTypes.DEFAULT_TYPE):
    """Send weekly schedule to all groups (Sunday) — per space."""
    chat_ids = db.get_chat_ids_with_bot_introduced()
    start, end = sched.get_week_range(datetime.now())

    for chat_id in chat_ids:
        if db.space_has_zero_rooms(chat_id):
            continue
        sched.ensure_assignments_exist(chat_id)
        assignments = db.get_assignments_for_week(chat_id, start, end)
        text = msg.WEEKLY_HEADER.format(
            start=msg.format_date_display(start),
            end=msg.format_date_display(end),
        )
        if not assignments:
            text += msg.WEEKLY_EMPTY
        else:
            for a in assignments:
                text += msg.WEEKLY_LINE.format(
                    date=msg.format_date_display(a["due_date"]),
                    room=msg.escape_md(a["room_name"]),
                    username=msg.escape_md(a["telegram_username"]),
                )
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception:
            pass


async def on_bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When bot is added to a group, introduce itself."""
    if update.my_chat_member:
        cm = update.my_chat_member
        if cm.new_chat_member.status in ("member", "administrator"):
            chat_id = update.effective_chat.id
            title = (update.effective_chat.title or "").strip()
            gc = db.get_or_create_space(chat_id, title)
            if not gc["bot_introduced"]:
                db.set_bot_introduced(chat_id)
                config = _load_config_file()
                if config:
                    db.sync_flatmates_from_config(chat_id, config)
                    db.sync_rooms_from_config(chat_id, config)
                if db.space_has_setup(chat_id):
                    flatmates = db.get_active_flatmates(chat_id)
                    counts = db.get_cleaning_count_per_flatmate(chat_id)
                    intro = msg.build_intro_message(flatmates, counts)
                    await context.bot.send_message(chat_id=chat_id, text=intro, parse_mode="Markdown", reply_markup=_main_menu_keyboard(chat_id))
                elif db.space_has_zero_rooms(chat_id):
                    await context.bot.send_message(chat_id=chat_id, text=msg.SETUP_REMINDER_MESSAGE, parse_mode="Markdown", reply_markup=_keyboard_setup_reminder_silent())
                else:
                    await context.bot.send_message(chat_id=chat_id, text=msg.SETTINGS_FIRST_MESSAGE, parse_mode="Markdown", reply_markup=_settings_keyboard(chat_id))


async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When bot is added via 'Add members'."""
    for u in update.message.new_chat_members:
        if u.is_bot and u.id == context.bot.id:
            chat_id = update.effective_chat.id
            title = (update.effective_chat.title or "").strip()
            gc = db.get_or_create_space(chat_id, title)
            if not gc["bot_introduced"]:
                db.set_bot_introduced(chat_id)
                config = _load_config_file()
                if config:
                    db.sync_flatmates_from_config(chat_id, config)
                    db.sync_rooms_from_config(chat_id, config)
                if db.space_has_setup(chat_id):
                    flatmates = db.get_active_flatmates(chat_id)
                    counts = db.get_cleaning_count_per_flatmate(chat_id)
                    intro = msg.build_intro_message(flatmates, counts)
                    await context.bot.send_message(chat_id=chat_id, text=intro, parse_mode="Markdown", reply_markup=_main_menu_keyboard(chat_id))
                elif db.space_has_zero_rooms(chat_id):
                    await context.bot.send_message(chat_id=chat_id, text=msg.SETUP_REMINDER_MESSAGE, parse_mode="Markdown", reply_markup=_keyboard_setup_reminder_silent())
                else:
                    await context.bot.send_message(chat_id=chat_id, text=msg.SETTINGS_FIRST_MESSAGE, parse_mode="Markdown", reply_markup=_settings_keyboard(chat_id))
            break


def build_application(token: str) -> Application:
    db.init_db()
    for chat_id in db.get_chat_ids_with_bot_introduced():
        if not db.space_has_zero_rooms(chat_id):
            sched.ensure_assignments_exist(chat_id)

    config = _load_config_file()
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("replace", cmd_replace))
    app.add_handler(CommandHandler("room", cmd_room))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("cleaned", cmd_cleaned))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(ChatMemberHandler(on_bot_added_to_group, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))

    # Daily reminders; weekly schedule on Sunday. Use defaults (per-space settings used at runtime)
    reminder_h = config.get("reminder_hour", 9)
    reminder_m = config.get("reminder_minute", 0)
    report_h = config.get("weekly_report_hour", 10)
    report_m = config.get("weekly_report_minute", 0)
    monthly_h = config.get("monthly_report_hour", 20)
    monthly_m = config.get("monthly_report_minute", 0)
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(send_daily_reminders, time=datetime.now().replace(hour=reminder_h, minute=reminder_m).time())
        job_queue.run_daily(
            send_weekly_schedule,
            time=datetime.now().replace(hour=report_h, minute=report_m).time(),
            days=(6,),  # 0=Mon, 6=Sun
        )
        job_queue.run_daily(send_monthly_stats, time=datetime.now().replace(hour=monthly_h, minute=monthly_m).time())
        job_queue.run_repeating(send_setup_reminders, interval=3600, first=60)  # Every hour for timezone-aware setup reminders

    return app
