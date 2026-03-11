#!/usr/bin/env python3
import sys
import os

# Always run from project root — fixes ALL import errors
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

mode = sys.argv[1] if len(sys.argv) > 1 else "bot"

if mode == "bot":
    print("🤖 Starting @ikycbot...")
    import asyncio
    import importlib.util
    spec = importlib.util.spec_from_file_location("bot", os.path.join(ROOT, "bot.py"))
    bot_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot_module)
    asyncio.run(bot_module.main())

elif mode == "panel":
    print("🖥️  Starting admin panel on port 8080...")
    import uvicorn
    uvicorn.run("webpanel.app:app", host="0.0.0.0", port=8080, reload=False)

elif mode == "both":
    import subprocess
    import uvicorn
    print("🚀 Starting bot + admin panel...")
    bot_proc = subprocess.Popen(
        [sys.executable, "run.py", "bot"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": ROOT}
    )
    print(f"🤖 Bot PID: {bot_proc.pid}")
    uvicorn.run("webpanel.app:app", host="0.0.0.0", port=8080, reload=False)

else:
    print("Usage: python run.py [bot|panel|both]")
