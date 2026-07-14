"""Data-access layer. Backend-pluggable: local SQLite (default) or Turso/libSQL
(persistent) when TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set.

Both backends are normalized to return dict rows (built from cursor.description),
because libsql cursors return plain tuples (no name access) unlike sqlite3.Row.
"""
import sqlite3
import time
from pathlib import Path

import config

_conn = None
USING_TURSO = bool(config.TURSO_DATABASE_URL and config.TURSO_AUTH_TOKEN)


def conn():
    global _conn
    if _conn is None:
        if USING_TURSO:
            import libsql_experimental as libsql
            _conn = libsql.connect(database=config.TURSO_DATABASE_URL,
                                   auth_token=config.TURSO_AUTH_TOKEN)
        else:
            _conn = sqlite3.connect(config.DB_PATH)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def _cursor(sql: str, params=()):
    c = conn()
    return c.execute(sql, tuple(params)) if params else c.execute(sql)


def _rows(sql: str, params=()) -> list[dict]:
    cur = _cursor(sql, params)
    cols = [d[0] for d in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _row(sql: str, params=()) -> dict | None:
    cur = _cursor(sql, params)
    cols = [d[0] for d in (cur.description or [])]
    r = cur.fetchone()
    return dict(zip(cols, r)) if r is not None else None


def _write(sql: str, params=()):
    _cursor(sql, params)
    conn().commit()


def _is_unique_violation(exc: Exception) -> bool:
    # sqlite3 -> IntegrityError; libsql -> ValueError; both mention UNIQUE.
    return isinstance(exc, (sqlite3.IntegrityError, ValueError)) and \
        "unique" in str(exc).lower()


_SNOWFLAKE_TABLES = ("participants", "contests", "contest_participants",
                     "solves", "votes", "performances")
_SNOWFLAKE_COLS = {"discord_id", "guild_id", "channel_id",
                   "leaderboard_message_id", "join_message_id", "created_by"}


def init():
    _fix_snowflake_tables()   # recreate any wrong-typed EMPTY tables (no data loss)
    schema = Path(__file__).with_name("schema.sql").read_text()
    conn().executescript(schema)
    conn().commit()
    _migrate()


def _fix_snowflake_tables():
    """Older tables stored snowflake IDs as INTEGER (precision-lossy on libSQL).
    Drop and recreate ONLY tables that are still INTEGER-typed AND empty — so this
    never destroys data. Fresh installs are unaffected."""
    for t in _SNOWFLAKE_TABLES:
        try:
            info = _rows(f"PRAGMA table_info({t})")
        except Exception:
            continue
        if not info:
            continue  # table doesn't exist yet — executescript will create it (TEXT)
        int_snow = any(r["name"] in _SNOWFLAKE_COLS and
                       (r["type"] or "").upper() == "INTEGER" for r in info)
        if not int_snow:
            continue
        try:
            n = _row(f"SELECT COUNT(*) AS n FROM {t}")["n"]
        except Exception:
            continue
        if n == 0:
            _write(f"DROP TABLE {t}")


def _migrate():
    # Add columns that existing tables may lack (no-op if present).
    for col, decl in (("join_message_id", "TEXT"), ("draw_epoch", "INTEGER")):
        try:
            _write(f"ALTER TABLE contests ADD COLUMN {col} {decl}")
        except Exception:
            pass


# --- participants ---

def upsert_participant(discord_id: int, pe_username: str, friend_key: str | None):
    _write(
        "INSERT INTO participants (discord_id, pe_username, friend_key, registered_at) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(discord_id) DO UPDATE SET pe_username=excluded.pe_username, "
        "friend_key=excluded.friend_key",
        (str(discord_id), pe_username, friend_key, _now_iso()),
    )


def get_participant(discord_id: int) -> dict | None:
    return _row("SELECT * FROM participants WHERE discord_id=?", (str(discord_id),))


def all_participants() -> list[dict]:
    return _rows("SELECT * FROM participants")


def participant_count() -> int:
    return _row("SELECT COUNT(*) AS n FROM participants")["n"]


# --- contests ---

def create_contest(name, start_epoch, duration_min, contest_type, num_problems,
                   guild_id, channel_id, created_by, draw_epoch) -> int:
    row = _row(
        "INSERT INTO contests (name, start_epoch, duration_min, contest_type, "
        "num_problems, status, guild_id, channel_id, created_by, created_at, draw_epoch) "
        "VALUES (?,?,?,?,?,'recruiting',?,?,?,?,?) RETURNING id",
        (name, start_epoch, duration_min, contest_type, num_problems,
         str(guild_id), str(channel_id), str(created_by), _now_iso(), draw_epoch),
    )
    conn().commit()
    return row["id"]


def set_join_message(contest_id: int, message_id: int):
    _write("UPDATE contests SET join_message_id=? WHERE id=?",
           (str(message_id), contest_id))


def contest_by_join_message(message_id: int) -> dict | None:
    return _row("SELECT * FROM contests WHERE join_message_id=?", (str(message_id),))


# --- contest join list (per-contest opt-in) ---

def join_contest(contest_id: int, discord_id: int) -> bool:
    try:
        _write("INSERT INTO contest_participants (contest_id, discord_id, joined_at) "
               "VALUES (?,?,?)", (contest_id, str(discord_id), _now_iso()))
        return True
    except Exception as e:
        if _is_unique_violation(e):
            return False
        raise


def leave_contest(contest_id: int, discord_id: int) -> bool:
    before = is_joined(contest_id, discord_id)
    _write("DELETE FROM contest_participants WHERE contest_id=? AND discord_id=?",
           (contest_id, str(discord_id)))
    return before


def is_joined(contest_id: int, discord_id: int) -> bool:
    return _row("SELECT 1 AS x FROM contest_participants WHERE contest_id=? AND discord_id=?",
                (contest_id, str(discord_id))) is not None


def joined_participants(contest_id: int) -> list[dict]:
    return _rows(
        "SELECT p.discord_id, p.pe_username, p.friend_key "
        "FROM contest_participants cp JOIN participants p ON p.discord_id = cp.discord_id "
        "WHERE cp.contest_id=?", (contest_id,))


def joined_count(contest_id: int) -> int:
    return _row("SELECT COUNT(*) AS n FROM contest_participants WHERE contest_id=?",
                (contest_id,))["n"]


def add_contest_problems(contest_id: int, problems: list[dict]):
    for p in problems:
        _cursor(
            "INSERT OR REPLACE INTO contest_problems (contest_id, problem_id, title, difficulty) "
            "VALUES (?,?,?,?)",
            (contest_id, p["id"], p["title"], p["difficulty"]),
        )
    conn().commit()


def get_contest(contest_id: int) -> dict | None:
    return _row("SELECT * FROM contests WHERE id=?", (contest_id,))


def contest_problems(contest_id: int) -> list[dict]:
    return _rows(
        "SELECT * FROM contest_problems WHERE contest_id=? ORDER BY difficulty, problem_id",
        (contest_id,),
    )


def set_contest_status(contest_id: int, status: str):
    _write("UPDATE contests SET status=? WHERE id=?", (status, contest_id))


def set_leaderboard_message(contest_id: int, message_id: int):
    _write("UPDATE contests SET leaderboard_message_id=? WHERE id=?",
           (str(message_id), contest_id))


def contests_by_status(status: str) -> list[dict]:
    return _rows("SELECT * FROM contests WHERE status=?", (status,))


def latest_running_contest(guild_id: int) -> dict | None:
    return _row(
        "SELECT * FROM contests WHERE guild_id=? AND status='running' "
        "ORDER BY start_epoch DESC LIMIT 1",
        (str(guild_id),),
    )


def latest_contest(guild_id: int) -> dict | None:
    return _row(
        "SELECT * FROM contests WHERE guild_id=? ORDER BY id DESC LIMIT 1", (str(guild_id),))


# --- solves ---

def record_solve(contest_id, discord_id, problem_id, points, solved_epoch) -> bool:
    """True if newly recorded, False if already present."""
    try:
        _write(
            "INSERT INTO solves (contest_id, discord_id, problem_id, points, "
            "solved_epoch, verified_epoch) VALUES (?,?,?,?,?,?)",
            (contest_id, str(discord_id), problem_id, points, solved_epoch, int(time.time())),
        )
        return True
    except Exception as e:
        if _is_unique_violation(e):
            return False
        raise


def has_solve(contest_id, discord_id, problem_id) -> bool:
    return _row(
        "SELECT 1 AS x FROM solves WHERE contest_id=? AND discord_id=? AND problem_id=?",
        (contest_id, str(discord_id), problem_id),
    ) is not None


def solved_map(contest_id: int) -> dict[int, set]:
    m: dict[int, set] = {}
    for r in _rows("SELECT discord_id, problem_id FROM solves WHERE contest_id=?",
                   (contest_id,)):
        m.setdefault(r["discord_id"], set()).add(r["problem_id"])
    return m


def leaderboard(contest_id: int) -> list[dict]:
    """Ranked: total points desc, then earliest last-solve time (tiebreak)."""
    return _rows(
        "SELECT s.discord_id, p.pe_username, SUM(s.points) AS pts, "
        "COUNT(*) AS solved, MAX(COALESCE(s.solved_epoch, s.verified_epoch)) AS last_solve "
        "FROM solves s JOIN participants p ON p.discord_id = s.discord_id "
        "WHERE s.contest_id=? GROUP BY s.discord_id "
        "ORDER BY pts DESC, last_solve ASC",
        (contest_id,),
    )


# --- votes (recommend) ---

def add_vote(discord_id: int, problem_id: int) -> bool:
    """False if this user already voted for this problem."""
    try:
        _write("INSERT INTO votes (discord_id, problem_id, voted_at) VALUES (?,?,?)",
               (str(discord_id), problem_id, _now_iso()))
        return True
    except Exception as e:
        if _is_unique_violation(e):
            return False
        raise


def vote_counts() -> list[tuple]:
    """[(problem_id, unique_user_votes)] sorted by votes desc, then problem_id asc."""
    return [(r["problem_id"], r["votes"]) for r in _rows(
        "SELECT problem_id, COUNT(*) AS votes FROM votes "
        "GROUP BY problem_id ORDER BY votes DESC, problem_id ASC")]


# --- performances / rating ---

def record_performance(discord_id: int, contest_id: int, perf: int, at_epoch: int):
    _write(
        "INSERT OR IGNORE INTO performances (discord_id, contest_id, perf, at_epoch) "
        "VALUES (?,?,?,?)",
        (str(discord_id), contest_id, perf, at_epoch),
    )


def contest_has_performances(contest_id: int) -> bool:
    return _row("SELECT 1 AS x FROM performances WHERE contest_id=? LIMIT 1",
                (contest_id,)) is not None


def all_performances() -> list[dict]:
    """Every performance row joined with the participant's PE username."""
    return _rows(
        "SELECT f.discord_id, p.pe_username, f.perf, f.at_epoch "
        "FROM performances f JOIN participants p ON p.discord_id = f.discord_id "
        "ORDER BY f.at_epoch DESC")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
