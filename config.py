"""Runtime configuration loaded from environment / .env."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load the .env sitting next to this file, regardless of the current working
# directory (find_dotenv()'s cwd-based search is unreliable under some runners).
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)


def _int(name: str, default=None):
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = _int("GUILD_ID")
# Only this Discord account may delete the bot's messages. Accepts a username
# (e.g. "trueryob") or a numeric user ID.
OWNER = os.getenv("OWNER", "trueryob")

# Preferred: paste the whole `Cookie:` request header ("PHPSESSID=..; keep_alive=..").
PE_COOKIE = os.getenv("PE_COOKIE", "")
# Legacy/alternative: individual cookies. A bare value (no "name=") is assumed to be
# PHPSESSID / keep_alive respectively.
PE_SESSION_COOKIE = os.getenv("PE_SESSION_COOKIE", "")
PE_KEEP_ALIVE_COOKIE = os.getenv("PE_KEEP_ALIVE_COOKIE", "")
PE_BOT_USERNAME = os.getenv("PE_BOT_USERNAME", "")

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo"))
DB_PATH = os.getenv("DB_PATH", "pe_runner.db")
# Optional persistent DB (Turso/libSQL). If both are set, db.py uses Turso instead
# of the local (ephemeral on Render) SQLite file. Empty => unchanged sqlite3 behavior.
# Accept either our DB_URL/DB_TOKEN_RW names or the TURSO_* names.
TURSO_DATABASE_URL = os.getenv("DB_URL") or os.getenv("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.getenv("DB_TOKEN_RW") or os.getenv("TURSO_AUTH_TOKEN", "")
FRIEND_LIMIT = _int("FRIEND_LIMIT", 64)
# Where the rotating PE cookie jar is persisted (contains secrets — gitignored).
COOKIE_JAR_PATH = os.getenv(
    "COOKIE_JAR_PATH", str(Path(__file__).resolve().parent / "pe_cookies.pkl"))


def require(*names: str):
    """Raise if any required env var is missing, with a clear message."""
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit(
            "Missing required config: " + ", ".join(missing) +
            "\nCopy .env.example to .env and fill it in."
        )
