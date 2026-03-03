"""
Cinderella bot message templates and tone escalation.
Friendly -> less friendly -> military -> guilt manipulation.
Hacker-style text art, no emojis.
"""


def escape_md(text: str) -> str:
    """Escape characters that break Telegram Markdown parsing (e.g. underscores in usernames)."""
    if not text:
        return text
    return text.replace("\\", "\\\\").replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


INTRO_TEMPLATE = """
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
          _
        (   )
         | |
        /   \\
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·

**The task repeats. What changes is how we meet it.**

The floor is swept. Tomorrow it is swept again. When sweeping, sweep — nothing else in that moment. The way we tend to one corner is the way we tend to the whole. Discipline in the small becomes discipline in the large. A tended space allows clarity.

  ═══════════════════════════════════════
       C I N D E R E L L A
       flat cleaning system
  ═══════════════════════════════════════

My mission: I am the annoying one who reminds. So you don't have to be. I externalize that role to support healthy, honest relationships among flatmates — free from unspoken resentment.

I support the routine:

  · **Weekly schedule** — Each person, one random day. I notify when your day arrives.
  · **Monthly stats** — Ranked: who tended their share.
  · **Daily reminders** — I tag the one whose turn it is.
  · **Choices** — Not today | 3 more days | Skip week | Done
  · **Fair rotation** — I track. Equal distribution.
  · **Proactive cleaning** — Step up for another? It counts. You rest later.

Admin: edit config.json and restart.

{greeting}

{stats}

    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
              One room at a time.
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
"""


def build_intro_message(flatmates: list, counts: dict) -> str:
    """Build intro with personal tags and current counters."""
    if not flatmates:
        greeting = ""
        stats = ""
    else:
        tags = " ".join(f"@{escape_md(f['telegram_username'])}" for f in flatmates)
        greeting = f"Greetings, {tags}. Verify your username is correct."
        lines = ["[STATS] **Current counters** (from invite or last replace)\n---"]
        for f in flatmates:
            c = counts.get(f["id"], 0)
            lines.append(f"  [>] {escape_md(f['name'])} (@{escape_md(f['telegram_username'])}): {c} cleanings")
        stats = "\n".join(lines)
    return INTRO_TEMPLATE.format(greeting=greeting, stats=stats)

# 33 awareness-provoking phrases per room. Short, clear, no instructions. Cycled in shuffled order.
AWARENESS_PHRASES = [
    "Notice what needs attention.",
    "The room is waiting.",
    "What you postpone, you carry.",
    "A clear space begins with a single action.",
    "Your turn. Your attention.",
    "The details matter.",
    "One thing at a time.",
    "The space reflects the care you give it.",
    "Presence is the first step.",
    "What you avoid accumulates.",
    "Attention is a choice.",
    "Begin.",
    "The room knows.",
    "No one else will do this for you today.",
    "Small actions, clear results.",
    "What are you avoiding?",
    "The moment is now.",
    "Clarity starts here.",
    "Your flatmates trust you.",
    "Do it fully or don't do it.",
    "The room deserves care.",
    "What would it feel like to finish?",
    "One corner. Then the next.",
    "No excuses today.",
    "The task is simple. The choice is yours.",
    "Begin with one thing.",
    "Attention before action.",
    "What needs to be seen?",
    "The room is asking for care.",
    "You know what to do.",
    "Action follows awareness.",
    "What will you choose?",
    "The space is waiting for you.",
]

# Reminder tones by reminder_count (0 = first, 1 = second, ...)
REMINDER_TONES = [
    # 0 - First reminder, friendly
    [
        ">> @{username} | Your turn for **{room}** today. You've got this.",
        "[!] @{username} — **{room}** requires attention. Flatmates will appreciate it.",
        ">> @{username}, **{room}** is queued for today. TLC recommended.",
    ],
    # 1 - Second reminder, still nice
    [
        ">> @{username} | Nudge: **{room}** still pending today.",
        ">> @{username} | Reminder: **{room}**. No pressure, but...",
        "[PING] @{username} — **{room}**. Still on your queue?",
    ],
    # 2 - Third, less friendly
    [
        ">> @{username}. **{room}**. Again. Please.",
        "[!] Reminder #3 | @{username}: **{room}** status: dirty.",
        ">> @{username}, we've been through this. **{room}**. Today.",
    ],
    # 3 - Fourth, firm
    [
        ">> @{username}. The **{room}** will not clean itself. Step up.",
        "[!] Final reminder | @{username}: **{room}**. Flatmates are waiting.",
        ">> @{username}. Enough delays. **{room}**. Now.",
    ],
    # 4 - Military (caps for visibility, not anger)
    [
        "[!] @{username} — REPORT FOR DUTY. **{room}**. THAT IS AN ORDER.",
        "[!] ATTENTION @{username}: **{room}** REQUIRES IMMEDIATE ACTION. NO EXCUSES.",
        ">> @{username}. **{room}**. CONSIDER THIS YOUR FORMAL NOTICE.",
    ],
    # 5+ - Guilt / emotion (caps for visibility, stands out in chat)
    [
        ">> YOUR FLATMATES WALK INTO A DIRTY **{room}** BECAUSE OF YOU, @{username}. JUST SAYING.",
        ">> EVERYONE DOES THEIR PART. EXCEPT **{room}** TODAY. @{username} — IS THIS WHO YOU WANT TO BE?",
        ">> @{username} — **{room}** STILL WAITING. YOUR FRIENDS DESERVE BETTER.",
    ],
]

DONE_MESSAGES = [
    "[+] @{username} | **{room}** logged as cleaned. Acknowledged.",
    "[OK] @{username} | **{room}** complete. Everyone will appreciate it.",
    "[+] @{username} | **{room}** done. Next: **{next_person}** for **{next_room}**.",
]

# When someone else did it (proactive)
DONE_BY_OTHER_MESSAGES = [
    "[+] @{username} took initiative. **{room}** cleaned. Logged. Next: **{next_person}** for **{next_room}**.",
    "[OK] @{username} stepped up for **{room}**. Counts for you. Next: **{next_person}** — **{next_room}**.",
]

SKIP_REASSIGN = "[>] @{username} acknowledged. @{new_username}, you have the lightest load. **{room}** this week."

NOT_TODAY_REPLY = "[>] @{username} | Reminder rescheduled for tomorrow."
THREE_DAYS_REPLY = "[>] @{username} | Checkback in 3 days."
SKIP_WEEK_REPLY = "[>] @{username} | Finding alternative for **{room}** this week."

WEEKLY_HEADER = """[SCHEDULE] **Cleaning roster** ({start} – {end})
---
"""

WEEKLY_LINE = "  [>] **{date}** | {room}: @{username}\n"
WEEKLY_EMPTY = "_No cleanings scheduled this week — stand down._"

MONTHLY_HEADER = """[STATS] **Monthly cleaning report** — {month} {year}
_Ranked: most to least active_
---
"""

MONTHLY_LINE = "  [>] **{rank}.** @{username} — {total} cleanings\n    {room_breakdown}\n"
MONTHLY_EMPTY = "_No cleanings recorded this month._"


def format_monthly_stats(year: int, month: int, stats: list) -> str:
    from calendar import month_name
    month_str = month_name[month]
    if not stats:
        return MONTHLY_HEADER.format(month=month_str, year=year) + MONTHLY_EMPTY
    lines = [MONTHLY_HEADER.format(month=month_str, year=year)]
    for i, s in enumerate(stats, 1):
        room_parts = [f"{escape_md(room)}: {cnt}x" for room, cnt in sorted(s["rooms"].items())]
        room_breakdown = ", ".join(room_parts) if room_parts else "—"
        lines.append(MONTHLY_LINE.format(
            rank=i,
            username=escape_md(s["username"]),
            total=s["total"],
            room_breakdown=room_breakdown,
        ))
    return "".join(lines)


def get_reminder_text(room: str, username: str, reminder_count: int, phrase_idx: int = 0) -> str:
    """Build reminder: tone wrapper + awareness phrase from loop."""
    tier = min(reminder_count, len(REMINDER_TONES) - 1)
    choices = REMINDER_TONES[tier]
    import random
    tone_line = random.choice(choices).format(room=escape_md(room), username=escape_md(username))
    phrase = AWARENESS_PHRASES[phrase_idx % len(AWARENESS_PHRASES)]
    return f"{tone_line}\n\n{phrase}"
