"""Project Euler data access.

Everything we need comes from ONE authenticated page: ``progress=<username>``.
For any user we can view (ourselves, or a friend who added our friend key), it
yields, for every problem: solved/unsolved, difficulty %, title, global solve
count, and — for solved problems — the solve timestamp.

Auth: PE's login has a CAPTCHA, so we do not log in programmatically. Instead we
reuse a browser session cookie (see .env.example). If the session expires, calls
raise SessionExpired and the operator must refresh the cookie.
"""
from __future__ import annotations

import os
import pickle
import re
import threading
from calendar import timegm
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

import config

BASE = "https://projecteuler.net"
PROGRESS_URL = BASE + "/progress={username}"
PROFILE_TXT_URL = BASE + "/profile/{username}.txt"

# Friend keys look like "942079_iEDMDDXDe13LYMmzlReee7a2IXghArkI".
_FRIEND_KEY_RE = re.compile(r"^\d+_[A-Za-z0-9]{8,}$")

_DIFF_RE = re.compile(r"\[(\d+)%\]")
_SOLVED_BY_RE = re.compile(r"Solved by\s+([\d,]+)")
_TITLE_RE = re.compile(r'"([^"]+)"')
# e.g. "Sun, 12 Jul 2026, 23:37"
_DATE_RE = re.compile(r"(\w{3}, \d{1,2} \w{3} \d{4}, \d{2}:\d{2})")


class SessionExpired(RuntimeError):
    pass


class ProblemCell:
    __slots__ = ("id", "solved", "difficulty", "title", "global_solved_by", "solved_epoch")

    def __init__(self, id, solved, difficulty, title, global_solved_by, solved_epoch):
        self.id = id
        self.solved = solved
        self.difficulty = difficulty
        self.title = title
        self.global_solved_by = global_solved_by
        self.solved_epoch = solved_epoch


# A browser-like UA avoids PE's anti-bot handling on some endpoints.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _config_cookies() -> dict[str, str]:
    """Resolve the cookies to send. PE auth needs BOTH PHPSESSID and keep_alive."""
    jar: dict[str, str] = {}
    # Preferred: a full "k=v; k2=v2" header string.
    full = config.PE_COOKIE.strip()
    if full:
        for part in full.split(";"):
            if "=" in part:
                name, _, value = part.strip().partition("=")
                jar[name.strip()] = value.strip()
        return _normalize(jar)
    # Fallback: individual cookies; a bare value gets its conventional name.
    sess = config.PE_SESSION_COOKIE.strip()
    if sess:
        if "=" in sess:
            name, _, value = sess.partition("=")
        else:
            name, value = "PHPSESSID", sess
        jar[name.strip()] = value.strip()
    keep = config.PE_KEEP_ALIVE_COOKIE.strip()
    if keep:
        if "=" in keep:
            name, _, value = keep.partition("=")
        else:
            name, value = "keep_alive", keep
        jar[name.strip()] = value.strip()
    return _normalize(jar)


def _normalize(jar: dict[str, str]) -> dict[str, str]:
    """PE's real session cookie is `__Host-PHPSESSID` (a __Host- prefixed cookie),
    NOT plain `PHPSESSID`. People routinely copy it under the wrong name, so fix it."""
    if "PHPSESSID" in jar and "__Host-PHPSESSID" not in jar:
        jar["__Host-PHPSESSID"] = jar.pop("PHPSESSID")
    return jar


# PE's keep_alive is a ROTATING remember-me token: each authenticated request may
# hand back a fresh one via Set-Cookie, invalidating the old. So we keep ONE
# long-lived session (auto-updates its jar), persist that jar to disk across
# restarts, and serialize requests so concurrent calls can't race the rotation.
# The .env cookie is only the initial SEED; once seeded, the persisted jar wins —
# unless .env is edited afterwards (mtime newer), which forces a re-seed.
_SESSION: requests.Session | None = None
_LOCK = threading.Lock()


def _jar_is_fresher_than_env() -> bool:
    jar, env = config.COOKIE_JAR_PATH, str(config.ENV_PATH)
    if not os.path.exists(jar):
        return False
    if not os.path.exists(env):
        return True
    return os.path.getmtime(jar) >= os.path.getmtime(env)


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    s = requests.Session()
    s.headers["User-Agent"] = _UA
    loaded = False
    if _jar_is_fresher_than_env():
        try:
            with open(config.COOKIE_JAR_PATH, "rb") as f:
                s.cookies.update(pickle.load(f))
            loaded = True
        except Exception:
            loaded = False
    if not loaded:  # (re)seed from .env
        for name, value in _config_cookies().items():
            s.cookies.set(name, value, domain="projecteuler.net")
    _SESSION = s
    return _SESSION


def _save_cookies():
    if _SESSION is None:
        return
    try:
        with open(config.COOKIE_JAR_PATH, "wb") as f:
            pickle.dump(_SESSION.cookies, f)
    except Exception:
        pass


def reset_session():
    """Drop the in-memory session (next call rebuilds it from jar/.env)."""
    global _SESSION
    _SESSION = None


def _parse_date(text: str) -> int | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%a, %d %b %Y, %H:%M")
        return timegm(dt.timetuple())  # PE times are UTC
    except ValueError:
        return None


def fetch_progress_grid(username: str) -> dict[int, ProblemCell]:
    """Fetch the progress grid for ``username``. Returns {problem_id: ProblemCell}.

    Requires that our session can view this user's progress (self or friend).
    """
    with _LOCK:  # serialize to avoid racing the rotating keep_alive token
        resp = _session().get(PROGRESS_URL.format(username=quote(username, safe="")),
                              timeout=30)
        resp.raise_for_status()
        html = resp.text

        # A logged-out / expired session is redirected to sign_in / about.
        redirected = any(x in resp.url for x in ("/sign_in", "/about"))
        if redirected or 'name="Username"' in html:
            raise SessionExpired(
                "PEセッションが無効/失効。ブラウザで取り直して .env を更新してください。"
            )

        cells = _parse_grid(html)
        if not cells:
            raise SessionExpired(
                "問題グリッドが見つかりません（未認証か、このユーザを閲覧できません）。"
            )
        _save_cookies()  # persist any rotated cookies PE just handed back
        return cells


def _parse_grid(html: str) -> dict[int, ProblemCell]:
    """Parse the progress grid.

    The page contains problems twice (a by-number grid and a by-level grid), so we
    dedupe by id. Per-problem solve status comes from the cell's own_problem_* class:
      - own_problem_solved   -> solved = True
      - own_problem_unsolved -> solved = False
      - neither (plain/unauthorized grid, e.g. a stranger's page or a 0-solve self
        page) -> solved = None  (i.e. "solve status not exposed here")
    Difficulty/title/global-count are always present, so catalog use works either way.
    """
    soup = BeautifulSoup(html, "lxml")
    cells: dict[int, ProblemCell] = {}
    for a in soup.select('a[href^="problem="]'):
        m = re.search(r"problem=(\d+)", a.get("href", ""))
        if not m:
            continue
        pid = int(m.group(1))
        ahtml = str(a)
        if "own_problem_unsolved" in ahtml:
            solved = False
        elif "own_problem_solved" in ahtml:
            solved = True
        else:
            solved = None
        tip = a.get_text(" ", strip=True)
        diff_m = _DIFF_RE.search(tip)
        difficulty = int(diff_m.group(1)) if diff_m else 0
        title_m = _TITLE_RE.search(tip)
        title = title_m.group(1) if title_m else f"Problem {pid}"
        sb_m = _SOLVED_BY_RE.search(tip)
        global_solved_by = int(sb_m.group(1).replace(",", "")) if sb_m else 0
        solved_epoch = _parse_date(tip) if solved else None
        cell = ProblemCell(pid, solved, difficulty, title, global_solved_by, solved_epoch)
        # Dedupe across the two grids; prefer a cell whose solve status is known.
        old = cells.get(pid)
        if old is None or (old.solved is None and solved is not None):
            cells[pid] = cell
    return cells


def _exposes_solve_status(grid: dict[int, ProblemCell]) -> bool:
    """True if this page actually revealed per-problem solve status (self or friend)."""
    return any(c.solved is not None for c in grid.values())


def valid_friend_key(key: str) -> bool:
    """Format-check a PE friend key. (Full validity is only known once the friend
    is actually added, which we don't automate.)"""
    return bool(_FRIEND_KEY_RE.match((key or "").strip()))


def username_exists(username: str) -> bool:
    """True if the PE username exists. Uses the public (no-auth) profile endpoint:
    a valid user returns a CSV line whose first field is the username; an invalid
    user returns an empty body."""
    u = (username or "").strip()
    if not u:
        return False
    with _LOCK:
        resp = _session().get(PROFILE_TXT_URL.format(username=quote(u, safe="")),
                              timeout=20)
    body = resp.text.strip()
    if not body or "<" in body[:50]:  # empty => not found; HTML => error page
        return False
    first = body.split(",", 1)[0].strip().lower()
    return first == u.lower()


class SolveStatusUnavailable(RuntimeError):
    """The progress page loaded but didn't expose this user's per-problem solve
    status — we're neither them nor an accepted friend (or they've solved nothing
    and PE shows a plain grid)."""


def solved_ids(username: str) -> set[int]:
    grid = fetch_progress_grid(username)
    if not _exposes_solve_status(grid):
        raise SolveStatusUnavailable(
            f"{username} の解答状況を読めません（bot と friend 登録されていない可能性）。"
        )
    return {pid for pid, c in grid.items() if c.solved}


def catalog() -> dict[int, ProblemCell]:
    """Full problem list with difficulty/title, read from the bot's own progress
    page. Solved flags here are the bot's and are ignored by callers."""
    return fetch_progress_grid(config.PE_BOT_USERNAME)
