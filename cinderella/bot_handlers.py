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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "group" and update.effective_chat.type != "supergroup":
        await update.message.reply_text(
            "👋 I'm Cinderella! Add me to a group chat to manage your flat's cleaning schedule. "
            "I only work in groups."
        )
        return
    chat_id = update.effective_chat.id
    gc = db.get_or_create_group_chat(chat_id)
    if gc["bot_introduced"]:
        await update.message.reply_text("I'm already here! Use /schedule to see this week's plan.")
        return
    db.set_bot_introduced(chat_id)
    await update.message.reply_text(msg.INTRO, parse_mode="Markdown")


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
            f"✓ Replaced @{old_user} with {new_name} (@{new_user}). "
            "The previous flatmate stays in history."
        )
    else:
        await update.message.reply_text(f"Could not find @{old_user} in the flatmate list.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show cleaning stats per flatmate."""
    flatmates = db.get_active_flatmates()
    counts = db.get_cleaning_count_per_flatmate()
    if not flatmates:
        await update.message.reply_text("No flatmates in the database yet. Check your config.")
        return
    lines = ["📊 **Cleaning stats**\n"]
    for f in flatmates:
        c = counts.get(f["id"], 0)
        lines.append(f"• {f['name']} (@{f['telegram_username']}): {c} cleanings")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show this week's schedule."""
    config = load_config()
    if not config:
        await update.message.reply_text("No config.json found. Create one from config.example.json")
        return
    sched.ensure_assignments_exist(config)
    start, end = sched.get_week_range(datetime.now())
    assignments = db.get_assignments_for_week(start, end)
    text = msg.WEEKLY_HEADER.format(start=start, end=end)
    if not assignments:
        text += msg.WEEKLY_EMPTY
    else:
        for a in assignments:
            text += msg.WEEKLY_LINE.format(
                date=a["due_date"],
                room=a["room_name"],
                username=a["telegram_username"],
            )
    await update.message.reply_text(text, parse_mode="Markdown")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data or ":" not in data:
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
                username=clicker_username,
                room=room_name,
                next_person="?",  # TODO: could compute next
                next_room="?",
            )
        else:
            done_msg = random.choice(msg.DONE_MESSAGES).format(
                username=assigned_username,
                room=room_name,
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
        reply = msg.NOT_TODAY_REPLY.format(username=assigned_username)
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
        reply = msg.THREE_DAYS_REPLY.format(username=assigned_username)
        await query.edit_message_text(reply, parse_mode="Markdown")

    elif action == "skip_week":
        db.update_assignment_status(assignment_id, "skipped")
        # Reassign to someone else
        exclude = [assignment["flatmate_id"]]
        next_person = db.get_flatmate_with_fewest_cleanings_excluding(exclude)
        if next_person:
            db.create_assignment(room_id, next_person["id"], due_date)
            reply = msg.SKIP_REASSIGN.format(
                username=assigned_username,
                new_username=next_person["telegram_username"],
                room=room_name,
            )
            await query.edit_message_text(reply, parse_mode="Markdown")
        else:
            reply = msg.SKIP_WEEK_REPLY.format(username=assigned_username, room=room_name)
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
    # Use current reminder_count for tone, then increment after sending
    reminder_count = assignment["reminder_count"]
    text = msg.get_reminder_text(
        assignment["room_name"],
        assignment["telegram_username"],
        reminder_count,
    )
    keyboard = [
        [
            InlineKeyboardButton("Not today", callback_data=f"not_today:{assignment_id}"),
            InlineKeyboardButton("3 more days", callback_data=f"three_days:{assignment_id}"),
        ],
        [
            InlineKeyboardButton("Skip the week", callback_data=f"skip_week:{assignment_id}"),
            InlineKeyboardButton("Done ✓", callback_data=f"done:{assignment_id}"),
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
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT chat_id FROM group_chats WHERE bot_introduced = 1"
        ).fetchall()
        chat_ids = [r["chat_id"] for r in rows]
    finally:
        conn.close()

    for chat_id in chat_ids:
        for a in assignments:
            text = msg.get_reminder_text(
                a["room_name"],
                a["telegram_username"],
                a["reminder_count"],
            )
            keyboard = [
                [
                    InlineKeyboardButton("Not today", callback_data=f"not_today:{a['id']}"),
                    InlineKeyboardButton("3 more days", callback_data=f"three_days:{a['id']}"),
                ],
                [
                    InlineKeyboardButton("Skip the week", callback_data=f"skip_week:{a['id']}"),
                    InlineKeyboardButton("Done ✓", callback_data=f"done:{a['id']}"),
                ],
            ]
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                db.increment_reminder_count(a["id"])
            except Exception:
                pass


async def send_monthly_stats(context: ContextTypes.DEFAULT_TYPE):
    """Send monthly stats at end of month (runs daily, checks if last day)."""
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    if tomorrow.month == today.month:
        return  # Not last day of month
    year, month = today.year, today.month
    stats = db.get_monthly_stats(year, month)
    text = msg.format_monthly_stats(year, month, stats)

    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT chat_id FROM group_chats WHERE bot_introduced = 1"
        ).fetchall()
        chat_ids = [r["chat_id"] for r in rows]
    finally:
        conn.close()

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
    text = msg.WEEKLY_HEADER.format(start=start, end=end)
    if not assignments:
        text += msg.WEEKLY_EMPTY
    else:
        for a in assignments:
            text += msg.WEEKLY_LINE.format(
                date=a["due_date"],
                room=a["room_name"],
                username=a["telegram_username"],
            )

    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT chat_id FROM group_chats WHERE bot_introduced = 1"
        ).fetchall()
        chat_ids = [r["chat_id"] for r in rows]
    finally:
        conn.close()

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
                await context.bot.send_message(chat_id=chat_id, text=msg.INTRO, parse_mode="Markdown")


async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """When bot is added via 'Add members'."""
    for u in update.message.new_chat_members:
        if u.is_bot and u.id == context.bot.id:
            chat_id = update.effective_chat.id
            gc = db.get_or_create_group_chat(chat_id)
            if not gc["bot_introduced"]:
                db.set_bot_introduced(chat_id)
                await context.bot.send_message(chat_id=chat_id, text=msg.INTRO, parse_mode="Markdown")
            break


def build_application(token: str) -> Application:
    config = load_config()
    db.init_db()
    if config:
        db.save_config(config)
        sched.ensure_assignments_exist(config)

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("replace", cmd_replace))
    app.add_handler(CommandHandler("stats", cmd_stats))
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
