"""Runtime configuration loaded from environment / .env."""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default=None):
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = _int("GUILD_ID")
ORGANIZER_ROLE_ID = _int("ORGANIZER_ROLE_ID")

PE_SESSION_COOKIE = os.getenv("PE_SESSION_COOKIE", "")
PE_KEEP_ALIVE_COOKIE = os.getenv("PE_KEEP_ALIVE_COOKIE", "")
PE_BOT_USERNAME = os.getenv("PE_BOT_USERNAME", "")

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo"))
DB_PATH = os.getenv("DB_PATH", "pe_runner.db")
FRIEND_LIMIT = _int("FRIEND_LIMIT", 64)


def require(*names: str):
    """Raise if any required env var is missing, with a clear message."""
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit(
            "Missing required config: " + ", ".join(missing) +
            "\nCopy .env.example to .env and fill it in."
        )
