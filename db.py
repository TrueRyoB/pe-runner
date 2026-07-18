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
                     "contest_presolved", "solves", "votes", "performances")
_SNOWFLAKE_COLS = {"discord_id", "guild_id", "channel_id",
                   "leaderboard_message_id", "join_message_id", "created_by"}


def init():
    _fix_snowflake_tables()   # recreate any wrong-typed EMPTY tables (no data loss)
    schema = Path(__file__).with_name("schema.sql").read_text()
    conn().executescript(schema)
    conn().commit()
    _migrate()


def _fix_snowflake_tables():
    """Recreate snowflake tables as TEXT (INTEGER loses precision on libSQL,
    corrupting IDs). SAFETY: only ever drops a table that is BOTH still INTEGER-typed
    AND empty — so a deploy can NEVER wipe a table that has data. TEXT tables and
    any non-empty table are left untouched. Fresh installs are unaffected."""
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
            continue  # already TEXT — leave its (correct) data alone
        try:
            n = _row(f"SELECT COUNT(*) AS n FROM {t}")["n"]
        except Exception:
            continue  # can't confirm it's empty -> do NOT drop
        if n == 0:
            _write(f"DROP TABLE {t}")   # empty old-schema table -> safe to recreate TEXT


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


def get_participant_by_pe(pe_username: str) -> dict | None:
    """Look up a participant by PE username (case-insensitive). For /profile."""
    return _row("SELECT * FROM participants WHERE LOWER(pe_username)=LOWER(?)",
                (pe_username.strip(),))


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


def count_contests_by_type(contest_type: str) -> int:
    """How many contests of this format exist (for the per-format serial: ERC001…).
    Counts every row incl. cancelled ones, so numbers are permanent and never reused."""
    return _row("SELECT COUNT(*) AS n FROM contests WHERE contest_type=?",
                (contest_type,))["n"]


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


# --- pre-solved (problems a late joiner had already AC'd before joining) ---

def add_presolved(contest_id: int, discord_id: int, problem_ids: list[int]):
    for pid in problem_ids:
        _cursor("INSERT OR IGNORE INTO contest_presolved (contest_id, discord_id, problem_id) "
                "VALUES (?,?,?)", (contest_id, str(discord_id), pid))
    conn().commit()


def is_presolved(contest_id: int, discord_id: int, problem_id: int) -> bool:
    return _row("SELECT 1 AS x FROM contest_presolved "
                "WHERE contest_id=? AND discord_id=? AND problem_id=?",
                (contest_id, str(discord_id), problem_id)) is not None


def presolved_map(contest_id: int) -> dict[str, set]:
    m: dict[str, set] = {}
    for r in _rows("SELECT discord_id, problem_id FROM contest_presolved WHERE contest_id=?",
                   (contest_id,)):
        m.setdefault(r["discord_id"], set()).add(r["problem_id"])
    return m


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


def set_num_problems(contest_id: int, n: int):
    """Set the actual drawn problem count (hardcore's variant is only known at draw)."""
    _write("UPDATE contests SET num_problems=? WHERE id=?", (n, contest_id))


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


def solve_times_map(contest_id: int) -> dict[str, dict[int, int]]:
    """{discord_id: {problem_id: confirmed_epoch}} — for showing AC times (mm:ss)
    on the leaderboard. Uses verified_epoch (when the bot confirmed the solve)."""
    m: dict[str, dict[int, int]] = {}
    for r in _rows("SELECT discord_id, problem_id, verified_epoch FROM solves "
                   "WHERE contest_id=?", (contest_id,)):
        m.setdefault(r["discord_id"], {})[r["problem_id"]] = r["verified_epoch"]
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


def user_performances(discord_id: int) -> list[dict]:
    """One user's performances, most-recent first (for rating.compute / /profile)."""
    return _rows(
        "SELECT perf, at_epoch FROM performances WHERE discord_id=? "
        "ORDER BY at_epoch DESC", (str(discord_id),))


def record_rating_snapshot(discord_id: int, contest_id: int, rating: int, at_epoch: int):
    _write(
        "INSERT OR REPLACE INTO rating_snapshots (discord_id, contest_id, rating, at_epoch) "
        "VALUES (?,?,?,?)",
        (str(discord_id), contest_id, rating, at_epoch),
    )


def rating_snapshots(discord_id: int) -> list[dict]:
    """One user's post-contest rating snapshots, oldest first (for +delta / highest)."""
    return _rows(
        "SELECT contest_id, rating, at_epoch FROM rating_snapshots WHERE discord_id=? "
        "ORDER BY at_epoch ASC", (str(discord_id),))


# --- anonymous feedback (no sender identity stored) ---

def add_feedback(message: str):
    _write("INSERT INTO feedback (message, created_at) VALUES (?,?)",
           (message, _now_iso()))


def list_feedback(limit: int = 20) -> list[dict]:
    return _rows("SELECT id, message, created_at FROM feedback "
                 "ORDER BY id DESC LIMIT ?", (limit,))


def feedback_count() -> int:
    return _row("SELECT COUNT(*) AS n FROM feedback")["n"]


def delete_feedback(ids: list[int]):
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    _write(f"DELETE FROM feedback WHERE id IN ({placeholders})", tuple(ids))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
