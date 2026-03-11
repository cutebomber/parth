#!/usr/bin/env python3
"""
Run this from anywhere:
  python run.py bot       → starts the Telegram bot
  python run.py panel     → starts the web admin panel
  python run.py both      → starts both (bot in background)
"""
import sys
import os
import subprocess

# Ensure we're always running from the project root
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

mode = sys.argv[1] if len(sys.argv) > 1 else "bot"

if mode == "bot":
    print("🤖 Starting @ikycbot...")
    os.execv(sys.executable, [sys.executable, "bot.py"])

elif mode == "panel":
    print("🖥️  Starting admin panel on port 8080...")
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn",
        "webpanel.app:app", "--host", "0.0.0.0", "--port", "8080"])

elif mode == "both":
    print("🚀 Starting bot + admin panel...")
    bot_proc = subprocess.Popen([sys.executable, "bot.py"])
    print(f"🤖 Bot PID: {bot_proc.pid}")
    # Run panel in foreground
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn",
        "webpanel.app:app", "--host", "0.0.0.0", "--port", "8080"])

else:
    print("Usage: python run.py [bot|panel|both]")
