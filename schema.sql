-- Discord snowflake IDs are stored as TEXT: they exceed 2^53 and libSQL loses
-- integer precision beyond that, corrupting the IDs. TEXT round-trips exactly.
CREATE TABLE IF NOT EXISTS participants (
    discord_id    TEXT PRIMARY KEY,
    pe_username   TEXT NOT NULL,
    friend_key    TEXT,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    start_epoch   INTEGER NOT NULL,
    duration_min  INTEGER NOT NULL,
    contest_type  TEXT NOT NULL,
    num_problems  INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'recruiting',  -- recruiting | scheduled | running | finished
    guild_id      TEXT,
    channel_id    TEXT,
    leaderboard_message_id TEXT,
    join_message_id TEXT,
    draw_epoch    INTEGER,        -- when problems are drawn (before start)
    created_by    TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contest_participants (
    contest_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    joined_at  TEXT NOT NULL,
    PRIMARY KEY (contest_id, discord_id)
);

-- Problems a (late) joiner had ALREADY solved before joining: shown as 'x' and
-- worth 0 points (they can't score a problem solved before the contest).
CREATE TABLE IF NOT EXISTS contest_presolved (
    contest_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    problem_id INTEGER NOT NULL,
    PRIMARY KEY (contest_id, discord_id, problem_id)
);

CREATE TABLE IF NOT EXISTS contest_problems (
    contest_id   INTEGER NOT NULL,
    problem_id   INTEGER NOT NULL,
    title        TEXT,
    difficulty   INTEGER NOT NULL,   -- percent (PE difficulty rating)
    PRIMARY KEY (contest_id, problem_id)
);

CREATE TABLE IF NOT EXISTS performances (
    discord_id TEXT NOT NULL,
    contest_id INTEGER NOT NULL,
    perf       INTEGER NOT NULL,   -- AtCoder-style performance for that contest
    at_epoch   INTEGER NOT NULL,   -- when the contest finished (for time decay)
    PRIMARY KEY (discord_id, contest_id)
);

CREATE TABLE IF NOT EXISTS votes (
    discord_id TEXT NOT NULL,
    problem_id INTEGER NOT NULL,
    voted_at   TEXT NOT NULL,
    PRIMARY KEY (discord_id, problem_id)   -- one vote per user per problem (unique user)
);

-- Anonymous feedback: sender identity is deliberately NOT stored.
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS solves (
    contest_id     INTEGER NOT NULL,
    discord_id     TEXT NOT NULL,
    problem_id     INTEGER NOT NULL,
    points         INTEGER NOT NULL,
    solved_epoch   INTEGER,           -- from PE progress timestamp when available
    verified_epoch INTEGER NOT NULL,  -- when the bot confirmed the solve
    PRIMARY KEY (contest_id, discord_id, problem_id)
);
