```
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
  ═══════════════════════════════════════════════
       C I N D E R E L L A
       shared flat cleaning bot
  ═══════════════════════════════════════════════
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
```

A Telegram bot for shared flats that manages cleaning rotation fairly. **Cinderella** sends weekly schedules, daily reminders with tone escalation, and tracks who cleaned what so everyone does their share.

**Mission:** The bot externalizes the role of the person who reminds others to clean. So you don't have to be that person. This supports healthy, honest relationships among flatmates — free from unspoken resentment.

**License:** [MIT](LICENSE) — Use, modify, and share freely.

---

## Features

```
  [>] Weekly schedule    — Sunday: random weekday per person (one reminder/day; postpones excepted)
  [>] Monthly stats      — End of month: ranked output (most to least active)
  [>] Daily reminders    — Tags the responsible unit on cleaning day
  [>] Inline buttons     — Not today | 3 more days | Skip the week | Done [OK]
  [>] Fair rotation      — Tracks cleanings; person with fewest gets the next
  [>] Proactive cleaning — Someone else did your turn? Logged. You rest later.
  [>] Tone escalation    — Friendly -> firm -> military -> guilt
  [>] Replace flatmates  — Someone moved out? /replace keeps history
```

---

## Quick Start

### 1. Create a Telegram Bot

```
  [*] Open @BotFather on Telegram
  [*] Send /newbot and follow the prompts
  [*] Copy the API token
```

### 2. Clone the Project

```bash
git clone https://github.com/antuum/cinderella_bot.git
cd cinderella_bot
```

Or download the ZIP from GitHub and extract it.

### 3. Configure

```bash
# Create .env with your bot token
cp .env.example .env
# Edit .env: TELEGRAM_BOT_TOKEN=your_token_here

# Create config from example
cp config.example.json config.json
# Edit config.json: rooms, flatmates (names + Telegram usernames)
```

### 4. Run

```bash
./run.sh
```

Or manually:

```bash
python3 -m venv venv
. venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 5. Add Bot to Your Group

```
  [*] Create a Telegram group for your flat
  [*] Add the bot as a member
  [*] Cinderella introduces itself automatically
  [*] Use /start in the group if it doesn't
```

---
```
  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
```

---

## Configuration (`config.json`)

| Key | Description |
|-----|-------------|
| `flat_name` | Optional display name for your flat |
| `rooms` | List of rooms and cleaning frequency |
| `flatmates` | List of people with names and Telegram usernames |
| `weekly_report_day` | Day for weekly schedule (e.g. `"sunday"`) |
| `weekly_report_hour` | Hour for weekly message (0–23) |
| `weekly_report_minute` | Minute for weekly message |
| `reminder_hour` | Hour for daily reminders |
| `reminder_minute` | Minute for daily reminders |
| `monthly_report_hour` | Hour for end-of-month stats (default 20) |
| `monthly_report_minute` | Minute for monthly stats |

### Example

```json
{
  "flat_name": "Sunny Apartment",
  "rooms": [
    { "name": "Kitchen", "times_per_month": 4 },
    { "name": "Bathroom", "times_per_month": 4 },
    { "name": "Living Room", "times_per_month": 2 }
  ],
  "flatmates": [
    { "name": "Alice", "telegram_username": "alice_flat" },
    { "name": "Bob", "telegram_username": "bob_flat" }
  ],
  "weekly_report_hour": 10,
  "weekly_report_minute": 0,
  "reminder_hour": 9,
  "reminder_minute": 0
}
```

- **times_per_month**: 4 = once per week, 2 = every two weeks
- **telegram_username**: Must match the user's @username on Telegram (without the `@`)

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start / intro (in group) |
| `/schedule` | Show this week's cleaning schedule |
| `/stats` | Show cleaning counts per flatmate |
| `/replace @old NewName @new` | Replace a flatmate (someone moved out) |

---

## Inline Button Options

When reminded about a cleaning:

```
  [>] Not today   — Remind again tomorrow
  [>] 3 more days — Remind in 3 days
  [>] Skip the week — Reassign to another flatmate
  [>] Done [OK]   — Anyone can mark it; counts for the person who clicked
```

---

## Running on Different Servers

The project is self-contained:

```
  [*] Copy the whole folder (including data/ if you already ran it)
  [*] Set TELEGRAM_BOT_TOKEN in .env
  [*] Adjust config.json if needed
  [*] Run ./run.sh
```

The SQLite database is stored in `data/cinderella.db`. Moving this folder keeps all history.

---

## Replacing a Flatmate

When someone moves out:

```
  1. /replace @old_username NewName @new_username
  2. Example: /replace @alice_old Alice @alice_new
  3. Update config.json: new person in flatmates instead of old
  4. Restart the bot
```

The old flatmate stays in history and stats. Phrase order reshuffles on replace. The new person gets a starting count equal to the minimum of the others, so they enter the rotation immediately — the most proactive person stays safe.

---

## Requirements

```
  [>] Python 3.8+
  [>] Linux, macOS, or Windows
```

---

## Troubleshooting

**Bot doesn't respond in the group**

```
  [*] Ensure the bot was added to the group
  [*] Send /start in the group
  [*] Check TELEGRAM_BOT_TOKEN in .env
```

**"No config.json found"**

```
  [*] Copy config.example.json to config.json and edit it
```

**Reminders not sent**

```
  [*] Bot must have been added to the group at least once
  [*] Check reminder_hour and reminder_minute in config
  [*] Bot must be running at that time (systemd, cron, etc.)
```

**Running 24/7 (Linux)**

Example `systemd` unit:

```ini
[Unit]
Description=Cinderella Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/Papialushka_Bot
ExecStart=/path/to/Papialushka_Bot/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable cinderella
sudo systemctl start cinderella
```

---

## Security

```
  [!] Never commit your .env file or real bot token
  [!] Use your own token from @BotFather
  [!] If a token was exposed, revoke it in @BotFather and create a new bot
```

---
```
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
         One room at a time.
    ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
```
