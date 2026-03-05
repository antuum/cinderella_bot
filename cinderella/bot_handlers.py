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


def load_config() -> dict:
    """Load config from config.json, fallback to config.example.json."""
    for p in (CONFIG_PATH, PROJECT_ROOT / "config.example.json"):
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _main_menu_keyboard():
    """Main quick-actions menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Schedule", callback_data="show_schedule"),
         InlineKeyboardButton("Stats", callback_data="show_stats")],
        [InlineKeyboardButton("Cleaned", callback_data="cleaned"),
         InlineKeyboardButton("History", callback_data="show_history")],
        [InlineKeyboardButton("Help", callback_data="show_help")],
    ])


def _menu_back_keyboard():
    """Single row: back to menu."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Menu", callback_data="show_menu")]])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "group" and update.effective_chat.type != "supergroup":
        await update.message.reply_text(
            "[>] I'm Cinderella. Add me to a group chat to manage your flat's cleaning schedule. "
            "I only work in groups. Use /help to see commands."
        )
        return
    chat_id = update.effective_chat.id
    gc = db.get_or_create_group_chat(chat_id)
    if gc["bot_introduced"]:
        # Already here — show menu (primary interface)
        await update.message.reply_text(
            msg.MENU_TEXT,
            parse_mode="Markdown",
            reply_markup=_main_menu_keyboard(),
        )
        return
    db.set_bot_introduced(chat_id)
    config = load_config()
    if config:
        db.sync_flatmates_from_config(config)
    flatmates = db.get_active_flatmates()
    counts = db.get_cleaning_count_per_flatmate()
    intro = msg.build_intro_message(flatmates, counts)
    await update.message.reply_text(
        intro,
        parse_mode="Markdown",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu with inline buttons. Pin this message for quick access."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Add me to a group chat first. Use /help.")
        return
    await update.message.reply_text(
        msg.MENU_TEXT,
        parse_mode="Markdown",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Replace a flatmate (someone moved out).
    Usage: /replace @old_username NewName @new_username
    Example: /replace @alice_old Alice @alice_new
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your flat's group chat.")
        return
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
    if db.replace_flatmate(old_user, new_name, new_user):
        await update.message.reply_text(
            f"[OK] Replaced @{old_user} with {new_name} (@{new_user}). "
            "The previous flatmate stays in history."
        )
        flatmates = db.get_active_flatmates()
        counts = db.get_cleaning_count_per_flatmate()
        tags = " ".join(f"@{msg.escape_md(f['telegram_username'])}" for f in flatmates)
        lines = [f"[ROSTER] **Updated.** {tags}\n---", "[STATS] **Current counters**\n"]
        for f in flatmates:
            c = counts.get(f["id"], 0)
            lines.append(f"  [>] {msg.escape_md(f['name'])} (@{msg.escape_md(f['telegram_username'])}): {c} cleanings")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Could not find @{old_user} in the flatmate list.")


async def cmd_cleaned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Log proactive cleaning: I cleaned a room without being reminded.
    Usage: /cleaned Kitchen  or  /cleaned Bathroom
    """
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your flat's group chat.")
        return
    args = context.args
    if not args:
        rooms = [r["name"] for r in db.get_rooms()]
        await update.message.reply_text(
            f"Usage: /cleaned <room>\n"
            f"Example: /cleaned Kitchen\n"
            f"Rooms: {', '.join(rooms) if rooms else '—'}"
        )
        return
    room_name = " ".join(args).strip()
    room = db.get_room_by_name(room_name)
    if not room:
        rooms = [r["name"] for r in db.get_rooms()]
        await update.message.reply_text(
            f"Room '{room_name}' not found. Rooms: {', '.join(rooms) if rooms else '—'}"
        )
        return
    username = (update.effective_user.username or "").lstrip("@") if update.effective_user else ""
    flatmate = db.get_flatmate_by_username(username)
    if not flatmate:
        await update.message.reply_text("You're not in the flatmate list. Ask admin to add you to config.json.")
        return

    start, end = sched.get_week_range(datetime.now())
    assignment = db.get_pending_assignment_for_room_in_week(room["id"], start, end)
    if assignment:
        db.update_assignment_status(assignment["id"], "done")
    db.record_cleaning(room["id"], flatmate["id"], was_assigned=False)
    counts = db.get_cleaning_count_per_flatmate()
    points = counts.get(flatmate["id"], 0)

    msg_text = msg.PROACTIVE_CLEANED_RESPONSE.format(
        username=msg.escape_md(username),
        room=msg.escape_md(room["name"]),
        points=points,
    )
    await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=_menu_back_keyboard())


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show cleaning stats per flatmate."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your flat's group chat.")
        return
    flatmates = db.get_active_flatmates()
    counts = db.get_cleaning_count_per_flatmate()
    if not flatmates:
        await update.message.reply_text("No flatmates in the database yet. Check your config.")
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


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full cleaning history with total points per person."""
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use this in your flat's group chat.")
        return
    flatmates = db.get_active_flatmates()
    counts = db.get_cleaning_count_per_flatmate()
    history = db.get_full_cleaning_history()
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
    config = load_config()
    if not config:
        await update.message.reply_text("No config.json found. Create one from config.example.json")
        return
    sched.ensure_assignments_exist(config)
    start, end = sched.get_week_range(datetime.now())
    assignments = db.get_assignments_for_week(start, end)
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

    if data == "show_menu":
        await query.edit_message_text(
            msg.MENU_TEXT,
            parse_mode="Markdown",
            reply_markup=_main_menu_keyboard(),
        )
        return

    if data == "show_schedule":
        config = load_config()
        if not config:
            await query.edit_message_text("No config. Use /help.", reply_markup=_menu_back_keyboard())
        else:
            sched.ensure_assignments_exist(config)
            start, end = sched.get_week_range(datetime.now())
            assignments = db.get_assignments_for_week(start, end)
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
        # Show room selection
        rooms = db.get_rooms()
        if not rooms:
            await query.edit_message_text(msg.CLEANED_CHOOSE_ROOM + "\n\nNo rooms in config.", reply_markup=_menu_back_keyboard())
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
        # Record cleaning for room_id, show points
        try:
            room_id = int(data.split(":")[1])
        except (ValueError, IndexError):
            await query.answer("Error")
            return
        room = next((r for r in db.get_rooms() if r["id"] == room_id), None)
        if not room:
            await query.answer("Room not found")
            return
        username = (query.from_user.username or "").lstrip("@") if query.from_user else ""
        flatmate = db.get_flatmate_by_username(username)
        if not flatmate:
            await query.edit_message_text(
                msg.CLEANED_NOT_FLATMATE,
                reply_markup=_menu_back_keyboard(),
            )
            return
        start, end = sched.get_week_range(datetime.now())
        assignment = db.get_pending_assignment_for_room_in_week(room_id, start, end)
        if assignment:
            db.update_assignment_status(assignment["id"], "done")
        db.record_cleaning(room_id, flatmate["id"], was_assigned=False)
        counts = db.get_cleaning_count_per_flatmate()
        points = counts.get(flatmate["id"], 0)
        text = msg.PROACTIVE_CLEANED_RESPONSE.format(
            username=msg.escape_md(username),
            room=msg.escape_md(room["name"]),
            points=points,
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_menu_back_keyboard())
        return

    if data == "show_history":
        flatmates = db.get_active_flatmates()
        counts = db.get_cleaning_count_per_flatmate()
        history = db.get_full_cleaning_history()
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
        flatmates = db.get_active_flatmates()
        counts = db.get_cleaning_count_per_flatmate()
        if not flatmates:
            await query.edit_message_text("No flatmates yet. Check config.", reply_markup=_menu_back_keyboard())
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
        return
    action, assignment_id_str = data.split(":", 1)
    try:
        assignment_id = int(assignment_id_str)
    except ValueError:
        return

    assignment = db.get_assignment_by_id(assignment_id)
    if not assignment or assignment["status"] != "pending":
        await query.edit_message_text("This task was already handled.")
        return

    chat_id = query.message.chat_id
    config = load_config()
    if not config:
        return

    # Who clicked?
    clicker_id = query.from_user.id if query.from_user else None
    clicker_username = (query.from_user.username or "").lstrip("@") if query.from_user else ""
    assigned_username = assignment["telegram_username"]
    room_name = assignment["room_name"]
    room_id = assignment["room_id"]
    due_date = assignment["due_date"]

    if action == "done":
        # Find who actually did it
        clicker = db.get_flatmate_by_username(clicker_username)
        was_assigned = clicker and clicker["id"] == assignment["flatmate_id"]

        if clicker:
            db.record_cleaning(room_id, clicker["id"], was_assigned=was_assigned)
        else:
            # Unknown user clicked - count for assigned person
            db.record_cleaning(room_id, assignment["flatmate_id"], was_assigned=True)

        db.update_assignment_status(assignment_id, "done")

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
        db.set_remind_on(assignment_id, tomorrow)
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
        db.set_remind_on(assignment_id, in_three)
        if context.job_queue:
            context.job_queue.run_once(
                _reminder_job,
                when=datetime.now() + timedelta(days=3),
                data={"assignment_id": assignment_id, "chat_id": chat_id},
            )
        reply = msg.THREE_DAYS_REPLY.format(username=msg.escape_md(assigned_username))
        await query.edit_message_text(reply, parse_mode="Markdown")

    elif action == "skip_week":
        db.update_assignment_status(assignment_id, "skipped")
        # Reassign to someone else
        exclude = [assignment["flatmate_id"]]
        next_person = db.get_flatmate_with_fewest_cleanings_excluding(exclude)
        if next_person:
            db.create_assignment(room_id, next_person["id"], due_date)
            reply = msg.SKIP_REASSIGN.format(
                username=msg.escape_md(assigned_username),
                new_username=msg.escape_md(next_person["telegram_username"]),
                room=msg.escape_md(room_name),
            )
            await query.edit_message_text(reply, parse_mode="Markdown")
        else:
            reply = msg.SKIP_WEEK_REPLY.format(username=msg.escape_md(assigned_username), room=msg.escape_md(room_name))
            await query.edit_message_text(reply, parse_mode="Markdown")


async def _reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Job callback for deferred reminders."""
    job = context.job
    assignment_id = job.data.get("assignment_id")
    chat_id = job.data.get("chat_id")
    if assignment_id and chat_id:
        await send_reminder(context, chat_id, assignment_id)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, assignment_id: int):
    """Send reminder for an assignment (used by job_queue)."""
    assignment = db.get_assignment_by_id(assignment_id)
    if not assignment or assignment["status"] != "pending":
        return
    reminder_count = assignment["reminder_count"]
    phrase_idx = db.get_and_advance_phrase(assignment["room_id"])
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
    db.increment_reminder_count(assignment_id)


def _job_reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    assignment_id = job.data.get("assignment_id")
    chat_id = job.data.get("chat_id", job.chat_id)
    if assignment_id and chat_id:
        import asyncio
        asyncio.create_task(send_reminder(context, chat_id, assignment_id))


async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Called daily by job_queue. Send reminders for today's assignments."""
    config = load_config()
    if not config:
        return
    sched.ensure_assignments_exist(config)

    today = datetime.now().strftime("%Y-%m-%d")
    assignments = db.get_pending_assignments_for_date(today)
    if not assignments:
        return

    # We need to know which group chats to send to. For now, we store chat_id when bot is added.
    # Get all groups where bot was introduced
    # We don't have that in DB - we need to store chat_id when bot joins. For now, get from config or...
    # Actually: we need a way to know which chat to send to. The bot is in ONE group per deployment.
    # So we need config to have a group_chat_id, or we discover it when bot is added.
    # Let's add optional group_chat_id to config. If not set, we try to send to all known group_chats.
    chat_ids = db.get_chat_ids_with_bot_introduced()

    for a in assignments:
        phrase_idx = db.get_and_advance_phrase(a["room_id"])
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
        for chat_id in chat_ids:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception:
                pass
        db.increment_reminder_count(a["id"])


async def send_monthly_stats(context: ContextTypes.DEFAULT_TYPE):
    """Send monthly stats at end of month (runs daily, checks if last day)."""
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    if tomorrow.month == today.month:
        return  # Not last day of month
    year, month = today.year, today.month
    stats = db.get_monthly_stats(year, month)
    text = msg.format_monthly_stats(year, month, stats)

    chat_ids = db.get_chat_ids_with_bot_introduced()

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception:
            pass


async def send_weekly_schedule(context: ContextTypes.DEFAULT_TYPE):
    """Send weekly schedule to all groups (Sunday)."""
    config = load_config()
    if not config:
        return
    sched.ensure_assignments_exist(config)

    start, end = sched.get_week_range(datetime.now())
    assignments = db.get_assignments_for_week(start, end)
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

    chat_ids = db.get_chat_ids_with_bot_introduced()

    for chat_id in chat_ids:
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
            gc = db.get_or_create_group_chat(chat_id)
            if not gc["bot_introduced"]:
                db.set_bot_introduced(chat_id)
                config = load_config()
                if config:
                    db.sync_flatmates_from_config(config)
                flatmates = db.get_active_flatmates()
                counts = db.get_cleaning_count_per_flatmate()
                intro = msg.build_intro_message(flatmates, counts)
                await context.bot.send_message(chat_id=chat_id, text=intro, parse_mode="Markdown")


async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When bot is added via 'Add members'."""
    for u in update.message.new_chat_members:
        if u.is_bot and u.id == context.bot.id:
            chat_id = update.effective_chat.id
            gc = db.get_or_create_group_chat(chat_id)
            if not gc["bot_introduced"]:
                db.set_bot_introduced(chat_id)
                config = load_config()
                if config:
                    db.sync_flatmates_from_config(config)
                flatmates = db.get_active_flatmates()
                counts = db.get_cleaning_count_per_flatmate()
                intro = msg.build_intro_message(flatmates, counts)
                await context.bot.send_message(chat_id=chat_id, text=intro, parse_mode="Markdown")
            break


def build_application(token: str) -> Application:
    config = load_config()
    db.init_db()
    if config:
        db.save_config(config)
        sched.ensure_assignments_exist(config)

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("replace", cmd_replace))
    app.add_handler(CommandHandler("cleaned", cmd_cleaned))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(ChatMemberHandler(on_bot_added_to_group, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))

    # Daily reminders at configured time; weekly schedule on Sunday
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

    return app
