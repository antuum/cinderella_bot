"""
Cinderella bot message templates and tone escalation.
Friendly -> less friendly -> military -> guilt manipulation.
"""

INTRO = """👋 Hey everyone! I'm **Cinderella**, your flat cleaning fairy.

I help you share cleaning fairly. Here's what I do:

📅 **Weekly schedule** — Every Sunday I assign each person a random day of the week (one per day), then remind you when your day comes.
📊 **Monthly stats** — At the end of each month I rank who cleaned what (most to least active).
🧹 **Daily reminders** — On cleaning days I'll tag the responsible person.
⌨️ **Quick choices** — Use the buttons: Not today • 3 more days • Skip week • Done
📊 **Fair rotation** — I track who cleaned what so everyone does their share.
🌟 **Proactive cleaning** — Did someone else's turn? I'll count it for you and you'll get a break later.

Add me to your group and make sure your flatmates are in the config! If you're the admin, edit `config.json` and restart me.

Let's keep our flat sparkly! ✨"""

# Reminder tones by reminder_count (0 = first, 1 = second, ...)
REMINDER_TONES = [
    # 0 - First reminder, friendly
    [
        "Hey @{username}! ✨ It's your turn to clean the **{room}** today. You've got this!",
        "Good morning @{username}! 🧹 Time for the **{room}** — your flatmates will appreciate it!",
        "@{username}, the **{room}** is waiting for you today. A little TLC goes a long way!",
    ],
    # 1 - Second reminder, still nice
    [
        "Hey @{username}, just a gentle nudge — **{room}** still needs cleaning today. 🙏",
        "@{username}, reminder: **{room}** today. No pressure, but... you know. 😊",
        "Ping! @{username} — **{room}**. Still on your to-do?",
    ],
    # 2 - Third, less friendly
    [
        "@{username}. **{room}**. Again. Please. 😐",
        "Reminder #3 for @{username}: **{room}** is still dirty.",
        "@{username}, we've been through this. **{room}**. Today.",
    ],
    # 3 - Fourth, firm
    [
        "@{username}. The **{room}** is not going to clean itself. Step up.",
        "Final reminder @{username}: **{room}**. Your flatmates are waiting.",
        "@{username}. Enough delays. **{room}**. Now.",
    ],
    # 4 - Military
    [
        "@{username} — REPORT FOR DUTY. **{room}**. THAT IS AN ORDER.",
        "ATTENTION @{username}: The **{room}** requires your immediate attention. No excuses.",
        "@{username}. **{room}**. Consider this your formal notice.",
    ],
    # 5+ - Guilt / emotion
    [
        "Your flatmates have to walk into a dirty **{room}** because of you @{username}. Just saying.",
        "Everyone does their part. Except for **{room}** today. @{username}, is this really who you want to be?",
        "@{username} — the **{room}** is still waiting. Your friends deserve better than this.",
    ],
]

DONE_MESSAGES = [
    "Thank you @{username}! ✨ The **{room}** is sparkling thanks to you!",
    "Amazing job @{username}! The **{room}** is clean and everyone will love it. 🌟",
    "You're a star @{username}! **{room}** done — next up: **{next_person}** for **{next_room}**.",
]

# When someone else did it (proactive)
DONE_BY_OTHER_MESSAGES = [
    "Wow, @{username} stepped up and cleaned the **{room}**! What a legend! 🙌 Next: **{next_person}** for **{next_room}**.",
    "Shoutout to @{username} for doing the **{room}**! That counts for you. Next up: **{next_person}** — **{next_room}**.",
]

SKIP_REASSIGN = "No problem @{username}. @{new_username}, could you take the **{room}** this week? You've got the lightest load. 🙏"

NOT_TODAY_REPLY = "No worries @{username}, I'll remind you again tomorrow! 🙂"
THREE_DAYS_REPLY = "Got it @{username}, I'll check back in 3 days. 👍"
SKIP_WEEK_REPLY = "Understood @{username}. I'll find someone else for the **{room}** this week."

WEEKLY_HEADER = """📅 **Cleaning schedule for this week** ({start} – {end})

"""

WEEKLY_LINE = "• **{date}** — {room}: @{username}\n"
WEEKLY_EMPTY = "_No cleanings scheduled this week — enjoy the break!_"

MONTHLY_HEADER = """📊 **Monthly cleaning stats** — {month} {year}
_Ranked from most to least active_

"""

MONTHLY_LINE = "• **{rank}.** @{username} — {total} cleanings\n  {room_breakdown}\n"
MONTHLY_EMPTY = "_No cleanings recorded this month._"


def format_monthly_stats(year: int, month: int, stats: list) -> str:
    from calendar import month_name
    month_str = month_name[month]
    if not stats:
        return MONTHLY_HEADER.format(month=month_str, year=year) + MONTHLY_EMPTY
    lines = [MONTHLY_HEADER.format(month=month_str, year=year)]
    for i, s in enumerate(stats, 1):
        room_parts = [f"{room}: {cnt}×" for room, cnt in sorted(s["rooms"].items())]
        room_breakdown = ", ".join(room_parts) if room_parts else "—"
        lines.append(MONTHLY_LINE.format(
            rank=i,
            username=s["username"],
            total=s["total"],
            room_breakdown=room_breakdown,
        ))
    return "".join(lines)


def get_reminder_text(room: str, username: str, reminder_count: int) -> str:
    tier = min(reminder_count, len(REMINDER_TONES) - 1)
    choices = REMINDER_TONES[tier]
    import random
    return random.choice(choices).format(room=room, username=username)
