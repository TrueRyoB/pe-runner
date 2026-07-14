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
    status        TEXT NOT NULL DEFAULT 'recruiting',  -- recruiting | scheduled | running | finished
    guild_id      INTEGER,
    channel_id    INTEGER,
    leaderboard_message_id INTEGER,
    join_message_id INTEGER,
    draw_epoch    INTEGER,        -- when problems are drawn (before start)
    created_by    INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contest_participants (
    contest_id INTEGER NOT NULL,
    discord_id INTEGER NOT NULL,
    joined_at  TEXT NOT NULL,
    PRIMARY KEY (contest_id, discord_id)
);

CREATE TABLE IF NOT EXISTS contest_problems (
    contest_id   INTEGER NOT NULL,
    problem_id   INTEGER NOT NULL,
    title        TEXT,
    difficulty   INTEGER NOT NULL,   -- percent (PE difficulty rating)
    PRIMARY KEY (contest_id, problem_id)
);

CREATE TABLE IF NOT EXISTS performances (
    discord_id INTEGER NOT NULL,
    contest_id INTEGER NOT NULL,
    perf       INTEGER NOT NULL,   -- AtCoder-style performance for that contest
    at_epoch   INTEGER NOT NULL,   -- when the contest finished (for time decay)
    PRIMARY KEY (discord_id, contest_id)
);

CREATE TABLE IF NOT EXISTS votes (
    discord_id INTEGER NOT NULL,
    problem_id INTEGER NOT NULL,
    voted_at   TEXT NOT NULL,
    PRIMARY KEY (discord_id, problem_id)   -- one vote per user per problem (unique user)
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
