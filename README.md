# Cinderella — Shared Flat Cleaning Bot

A Telegram bot for shared flats that manages cleaning rotation fairly. **Cinderella** sends weekly schedules, daily reminders with tone escalation, and tracks who cleaned what so everyone does their share.

**License:** [MIT](LICENSE) — Use, modify, and share freely.

## Features

- 📅 **Weekly schedule** — Every Sunday, sends the full cleaning plan for the week
- 📊 **Monthly stats** — End of each month, ranking of who cleaned what (most to least active)
- 🧹 **Daily reminders** — Tags the responsible person on cleaning day
- ⌨️ **Inline buttons** — Not today • 3 more days • Skip the week • Done
- 📊 **Fair rotation** — Tracks cleanings so the person with fewest does the next one
- 🌟 **Proactive cleaning** — If someone else does your turn, it counts for them
- 😊→😤 **Tone escalation** — Friendly at first, then less so, then military, then guilt
- 👋 **Replace flatmates** — Someone moved out? Use `/replace` and keep history

## Quick Start

### 1. Create a Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the API token you receive

### 2. Clone the Project

```bash
git clone https://github.com/YOUR_USERNAME/cinderella-bot.git
cd cinderella-bot
```

Or download the ZIP from GitHub and extract it.

### 3. Configure

```bash
cd Papialushka_Bot

# Create .env with your bot token
cp .env.example .env
# Edit .env and add: TELEGRAM_BOT_TOKEN=your_token_here

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
. venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 5. Add Bot to Your Group

1. Create a Telegram group for your flat
2. Add the bot as a member
3. Cinderella will introduce itself automatically
4. Use `/start` in the group if it doesn’t

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

- **times_per_month**: 4 ≈ once per week, 2 ≈ every two weeks
- **telegram_username**: Must match the user’s @username on Telegram (without the `@`)

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start / intro (in group) |
| `/schedule` | Show this week’s cleaning schedule |
| `/stats` | Show cleaning counts per flatmate |
| `/replace @old NewName @new` | Replace a flatmate (e.g. someone moved out) |

---

## Inline Button Options

When reminded about a cleaning:

- **Not today** — Remind again tomorrow
- **3 more days** — Remind in 3 days
- **Skip the week** — Reassign to another flatmate
- **Done ✓** — Anyone can mark it done; counts for the person who clicked

---

## Running on Different Servers

The project is self-contained:

1. Copy the whole folder (including `data/` if you already ran it)
2. Set `TELEGRAM_BOT_TOKEN` in `.env`
3. Adjust `config.json` if needed
4. Run `./run.sh`

The SQLite database is stored in `data/cinderella.db`. Moving this folder keeps all history.

---

## Replacing a Flatmate

When someone moves out:

1. Run: `/replace @old_username NewName @new_username`
2. Example: `/replace @alice_old Alice @alice_new`
3. Update `config.json` so the new person is in `flatmates` instead of the old one
4. Restart the bot so config is reloaded

The old flatmate stays in history and stats.

---

## Requirements

- Python 3.8+
- Linux, macOS, or Windows

---

## Troubleshooting

**Bot doesn’t respond in the group**

- Ensure the bot was added to the group
- Send `/start` in the group
- Check that the bot token in `.env` is correct

**“No config.json found”**

- Copy `config.example.json` to `config.json` and edit it

**Reminders not sent**

- The bot must have been added to the group at least once (so `bot_introduced = 1`)
- Check `reminder_hour` and `reminder_minute` in config
- The bot must be running at that time (e.g. via `systemd` or `cron`)

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

Save as `/etc/systemd/system/cinderella.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cinderella
sudo systemctl start cinderella
```

---

## Security

- **Never commit** your `.env` file or real bot token
- The token in this README or any example is a placeholder; use your own from @BotFather
- If a token was exposed, revoke it in @BotFather and create a new bot
