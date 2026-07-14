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

import re
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


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "pe-runner-contest-bot/0.1 (private hobby contest)"
    cookie = config.PE_SESSION_COOKIE.strip()
    if cookie:
        # Accept either "PHPSESSID=xxx" or a bare value.
        if "=" in cookie:
            name, _, value = cookie.partition("=")
        else:
            name, value = "PHPSESSID", cookie
        s.cookies.set(name.strip(), value.strip(), domain="projecteuler.net")
    keep = config.PE_KEEP_ALIVE_COOKIE.strip()
    if keep and "=" in keep:
        name, _, value = keep.partition("=")
        s.cookies.set(name.strip(), value.strip(), domain="projecteuler.net")
    return s


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
    resp = _session().get(PROGRESS_URL.format(username=username), timeout=30)
    resp.raise_for_status()
    html = resp.text

    # A logged-out / expired session gets redirected to the sign-in page.
    if "sign_in" in resp.url or "name=\"Username\"" in html or "Sign In" in html[:2000]:
        raise SessionExpired(
            "PE session appears invalid/expired. Refresh PE_SESSION_COOKIE."
        )

    cells = _parse_grid(html)
    if not cells:
        raise SessionExpired(
            "No problem grid found — the page structure changed or the user is not "
            "viewable with the current session."
        )
    return cells


def _parse_grid(html: str) -> dict[int, ProblemCell]:
    soup = BeautifulSoup(html, "lxml")
    cells: dict[int, ProblemCell] = {}
    for a in soup.select('a[href^="problem="]'):
        href = a.get("href", "")
        m = re.search(r"problem=(\d+)", href)
        if not m:
            continue
        pid = int(m.group(1))
        div = a.find("div")
        classes = " ".join(div.get("class", [])) if div else ""
        # Solved unless the status div is explicitly marked unsolved.
        solved = "unsolved" not in classes
        tip = a.get_text(" ", strip=True)
        diff_m = _DIFF_RE.search(tip)
        difficulty = int(diff_m.group(1)) if diff_m else 0
        title_m = _TITLE_RE.search(tip)
        title = title_m.group(1) if title_m else f"Problem {pid}"
        sb_m = _SOLVED_BY_RE.search(tip)
        global_solved_by = int(sb_m.group(1).replace(",", "")) if sb_m else 0
        solved_epoch = _parse_date(tip) if solved else None
        cells[pid] = ProblemCell(pid, solved, difficulty, title,
                                 global_solved_by, solved_epoch)
    return cells


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
    resp = _session().get(PROFILE_TXT_URL.format(username=quote(u, safe="")), timeout=20)
    body = resp.text.strip()
    if not body or "<" in body[:50]:  # empty => not found; HTML => error page
        return False
    first = body.split(",", 1)[0].strip().lower()
    return first == u.lower()


def solved_ids(username: str) -> set[int]:
    return {pid for pid, c in fetch_progress_grid(username).items() if c.solved}


def catalog() -> dict[int, ProblemCell]:
    """Full problem list with difficulty/title, read from the bot's own progress
    page. Solved flags here are the bot's and are ignored by callers."""
    return fetch_progress_grid(config.PE_BOT_USERNAME)
