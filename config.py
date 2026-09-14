import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "data" / "store.db"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
# Free-tier daily quota is per-model (observed: 20 req/day on gemini-3.6-flash) and each
# model has its own independent bucket. Until billing is decided for the live deployment,
# fall through this list on RESOURCE_EXHAUSTED so one model running dry doesn't stop the bot.
GEMINI_MODEL_FALLBACKS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODEL_FALLBACKS",
        "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.7-flash,gemini-3.8-flash",
    ).split(",")
    if m.strip()
]
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

SHOP_NAME_DEFAULT = os.environ.get("SHOP_NAME", "Nebula Kirana Store")
