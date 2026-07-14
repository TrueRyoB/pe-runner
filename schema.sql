CREATE TABLE IF NOT EXISTS participants (
    discord_id    INTEGER PRIMARY KEY,
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
    status        TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | running | finished
    guild_id      INTEGER,
    channel_id    INTEGER,
    leaderboard_message_id INTEGER,
    created_by    INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contest_problems (
    contest_id   INTEGER NOT NULL,
    problem_id   INTEGER NOT NULL,
    title        TEXT,
    difficulty   INTEGER NOT NULL,   -- percent (PE difficulty rating)
    PRIMARY KEY (contest_id, problem_id)
);

CREATE TABLE IF NOT EXISTS solves (
    contest_id     INTEGER NOT NULL,
    discord_id     INTEGER NOT NULL,
    problem_id     INTEGER NOT NULL,
    points         INTEGER NOT NULL,
    solved_epoch   INTEGER,           -- from PE progress timestamp when available
    verified_epoch INTEGER NOT NULL,  -- when the bot confirmed the solve
    PRIMARY KEY (contest_id, discord_id, problem_id)
);
