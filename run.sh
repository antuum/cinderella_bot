#!/bin/bash
# Cinderella bot launcher - installs deps if needed, then runs the bot.
# Use on any Linux server: ./run.sh

set -e
cd "$(dirname "$0")"

# Use venv if present
if [ -d "venv" ]; then
    . venv/bin/activate
elif [ -d ".venv" ]; then
    . .venv/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv venv
    . venv/bin/activate
fi

echo "Installing/updating dependencies..."
pip install -q -r requirements.txt

echo "Starting Cinderella..."
exec python main.py
