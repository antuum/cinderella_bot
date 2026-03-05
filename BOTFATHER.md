# BotFather setup for Cinderella

Configure your bot in [@BotFather](https://t.me/BotFather) for the most intuitive experience.

---

## 1. Set bot commands

In BotFather: **My Bots** → your bot → **Bot Settings** → **Commands**.

Paste this list (each line: `command - description`):

```
menu - Quick actions (tap buttons, no typing). Pin this message.
start - Start or show menu
schedule - This week's roster
stats - Cleaning counts
history - Full log
cleaned - Log cleaning (or use Cleaned button)
replace - Replace flatmate (@old NewName @new)
help - All commands
```

**Result:** When users type `/` in the chat, they see this menu. `/menu` is first so it's the obvious entry point.

---

## 2. Set bot description

**Bot Settings** → **Description**. Shown when users open the bot profile.

```
Shared flat cleaning bot. Manages rotation, sends reminders, tracks who cleaned what. Add me to your flat's group chat.
```

---

## 3. Set bot about (short bio)

**Bot Settings** → **About**. Shown in search results.

```
Flat cleaning rotation bot. Schedule, reminders, fair tracking.
```

---

## 4. Disable group privacy (if needed)

**Bot Settings** → **Group Privacy** → **Turn off**.

When ON, the bot only receives messages that start with `/` or @mention it. When OFF, it receives all messages. For Cinderella, keep it **ON** (default) — users interact via commands and inline buttons, so the bot doesn't need to read regular messages.

---

## Usage after setup

1. Add the bot to your flat's Telegram group.
2. Send `/start` or `/menu`.
3. **Pin the message with the buttons** — then everyone can tap Schedule, Stats, Cleaned, History, Help without typing.
4. To log proactive cleaning: tap **Cleaned** → choose room → done. Your points are shown.
5. Commands (`/schedule`, `/stats`, etc.) still work as fallback.
