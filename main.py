#!/usr/bin/env python3
"""
Cinderella - Shared flat cleaning rotation bot for Telegram.
Run with: python main.py
Or use: ./run.sh (handles dependencies)
"""

import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from cinderella.database import init_db
from cinderella.bot_handlers import build_application


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print(
            "Error: TELEGRAM_BOT_TOKEN not set.\n"
            "Create a .env file with TELEGRAM_BOT_TOKEN=your_token\n"
            "Or run: export TELEGRAM_BOT_TOKEN=your_token"
        )
        sys.exit(1)

    init_db()
    app = build_application(token)

    print("Cinderella bot starting...")
    app.run_polling(allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"])


if __name__ == "__main__":
    main()
