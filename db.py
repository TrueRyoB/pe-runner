"""Thin SQLite data-access layer. One connection, WAL mode, dict rows."""
import sqlite3
import time
from pathlib import Path

import config

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init():
    schema = Path(__file__).with_name("schema.sql").read_text()
    conn().executescript(schema)
    conn().commit()


# --- participants ---

def upsert_participant(discord_id: int, pe_username: str, friend_key: str | None):
    conn().execute(
        "INSERT INTO participants (discord_id, pe_username, friend_key, registered_at) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(discord_id) DO UPDATE SET pe_username=excluded.pe_username, "
        "friend_key=excluded.friend_key",
        (discord_id, pe_username, friend_key, _now_iso()),
    )
    conn().commit()


def get_participant(discord_id: int) -> sqlite3.Row | None:
    return conn().execute(
        "SELECT * FROM participants WHERE discord_id=?", (discord_id,)
    ).fetchone()


def all_participants() -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM participants").fetchall()


def participant_count() -> int:
    return conn().execute("SELECT COUNT(*) FROM participants").fetchone()[0]


# --- contests ---

def create_contest(name, start_epoch, duration_min, contest_type, num_problems,
                   guild_id, channel_id, created_by) -> int:
    cur = conn().execute(
        "INSERT INTO contests (name, start_epoch, duration_min, contest_type, "
        "num_problems, guild_id, channel_id, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (name, start_epoch, duration_min, contest_type, num_problems,
         guild_id, channel_id, created_by, _now_iso()),
    )
    conn().commit()
    return cur.lastrowid


def add_contest_problems(contest_id: int, problems: list[dict]):
    conn().executemany(
        "INSERT OR REPLACE INTO contest_problems (contest_id, problem_id, title, difficulty) "
        "VALUES (?,?,?,?)",
        [(contest_id, p["id"], p["title"], p["difficulty"]) for p in problems],
    )
    conn().commit()


def get_contest(contest_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM contests WHERE id=?", (contest_id,)).fetchone()


def contest_problems(contest_id: int) -> list[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM contest_problems WHERE contest_id=? ORDER BY difficulty, problem_id",
        (contest_id,),
    ).fetchall()


def set_contest_status(contest_id: int, status: str):
    conn().execute("UPDATE contests SET status=? WHERE id=?", (status, contest_id))
    conn().commit()


def set_leaderboard_message(contest_id: int, message_id: int):
    conn().execute(
        "UPDATE contests SET leaderboard_message_id=? WHERE id=?",
        (message_id, contest_id),
    )
    conn().commit()


def contests_by_status(status: str) -> list[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM contests WHERE status=?", (status,)
    ).fetchall()


def latest_running_contest(guild_id: int) -> sqlite3.Row | None:
    return conn().execute(
        "SELECT * FROM contests WHERE guild_id=? AND status='running' "
        "ORDER BY start_epoch DESC LIMIT 1",
        (guild_id,),
    ).fetchone()


# --- solves ---

def record_solve(contest_id, discord_id, problem_id, points, solved_epoch) -> bool:
    """Returns True if newly recorded, False if it was already there."""
    try:
        conn().execute(
            "INSERT INTO solves (contest_id, discord_id, problem_id, points, "
            "solved_epoch, verified_epoch) VALUES (?,?,?,?,?,?)",
            (contest_id, discord_id, problem_id, points, solved_epoch, int(time.time())),
        )
        conn().commit()
        return True
    except sqlite3.IntegrityError:
        return False


def has_solve(contest_id, discord_id, problem_id) -> bool:
    return conn().execute(
        "SELECT 1 FROM solves WHERE contest_id=? AND discord_id=? AND problem_id=?",
        (contest_id, discord_id, problem_id),
    ).fetchone() is not None


def leaderboard(contest_id: int) -> list[dict]:
    """Ranked: total points desc, then earliest last-solve time (tiebreak)."""
    rows = conn().execute(
        "SELECT s.discord_id, p.pe_username, SUM(s.points) AS pts, "
        "COUNT(*) AS solved, MAX(COALESCE(s.solved_epoch, s.verified_epoch)) AS last_solve "
        "FROM solves s JOIN participants p ON p.discord_id = s.discord_id "
        "WHERE s.contest_id=? GROUP BY s.discord_id "
        "ORDER BY pts DESC, last_solve ASC",
        (contest_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
