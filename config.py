import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "data" / "store.db"))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

SHOP_NAME_DEFAULT = os.environ.get("SHOP_NAME", "Nebula Kirana Store")
