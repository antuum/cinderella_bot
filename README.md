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
  [>] 33 awareness phrases — Rotating prompts per room; reshuffle on replace
  [>] New person = min count — Enters rotation immediately; proactive people stay safe
```

---

## Run Modes

```
  ./run.sh              Foreground. Attached to terminal. Stops when you close it.
  ./run.sh -d           Daemon. Runs in background. Survives terminal close. Logs to data/cinderella.log
  ./run.sh --install    Install autorun (one-time). Starts on login. Restarts on crash.
  ./run.sh --start      Start the installed service. Use after --stop. No reinstall needed.
  ./run.sh --stop       Pause the bot. Use --start to resume.
  ./run.sh --status     Check if the bot is running.
  ./run.sh --auto       Try autorun first; if that fails, daemon; else foreground.
```

**Stop / Start workflow**

```
  1. ./run.sh --stop    — Pause the bot (maintenance, config change, etc.)
  2. Edit config, restart machine, whatever you need
  3. ./run.sh --start   — Resume. No --install. The service stays installed.
```

If you never ran `--install`, `--start` will fail. Run `--install` once to set up autorun. After that, `--stop` and `--start` are all you need.

**Autorun** — Linux: systemd (`~/.config/systemd/user/`). macOS: launchd (`~/Library/LaunchAgents/`). No sudo. Headless Linux: `loginctl enable-lingering $USER` if the service doesn't run without login.

**Daemon** — Writes PID to `data/cinderella.pid`. Does not survive reboot; use `--install` for that.

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
./run.sh              # Foreground (default)
./run.sh -d           # Background (survives terminal close)
./run.sh --install    # Install autorun (one-time); bot starts on login
./run.sh --start      # Start the service (use after --stop; no reinstall)
./run.sh --stop       # Pause the bot
./run.sh --status     # Check if running
./run.sh --auto       # Try autorun, else background, else foreground
```

**First time:** `./run.sh --install` — installs the service, starts the bot. **Stopped it?** `./run.sh --start` — resumes. **Never** run `--install` again unless you moved the folder or reinstalled the OS.

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
  [*] Cinderella introduces itself: tags everyone from config.json, shows current counters
  [*] Each person gets @mentioned — verify your username is correct
  [*] Use /start in the group if the intro doesn't appear
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

**Tracking** — Fair rotation uses all-time totals (no monthly reset). `/stats` shows real cleanings. Monthly report shows that month only. New flatmate via `/replace` gets starting_offset = min(others) so they enter rotation immediately.

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

The project is self-contained. Copy the folder (including `data/` if you already ran it) to another machine:

```
  [*] Copy the whole folder
  [*] Set TELEGRAM_BOT_TOKEN in .env
  [*] Adjust config.json if needed
  [*] ./run.sh --install   (autorun) or ./run.sh -d (daemon) or ./run.sh (foreground)
```

The SQLite database is in `data/cinderella.db`. Logs: `data/cinderella.log`. PID: `data/cinderella.pid`.

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

**Running 24/7**

Use `./run.sh --install` — it installs the service and starts the bot. One command. On headless Linux: `loginctl enable-lingering $USER` if the service does not start without a login.

Manual system-wide install (Linux, requires sudo, optional):

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
