"""Discord bot: registration, contest creation, submission verification, leaderboard.

All user-facing text lives in messages.py (spoken by the mascot オイラーにゃん 🐱).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from urllib.parse import quote
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands
from discord.ext import tasks

# Render/PaaS capture stdout via a pipe -> block-buffered -> our prints never show.
# Force line buffering so diagnostics appear in the logs immediately.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# Live status, surfaced on the health endpoint for remote diagnosis.
STATUS = {"ready": False, "user": None, "guilds": [], "synced": {}, "errors": []}
_panel_registered = False

import config
import contest as contest_mod
import db
import messages as msg
import pe_client

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------------------------------------------------------------- helpers

def parse_start(text: str) -> int:
    """Parse a start time in the configured TZ; reject past times.

    Accepts: 'HH:MM' (today), 'MM-DD HH:MM' / 'MM/DD HH:MM' (this year),
    'YYYY-MM-DD HH:MM'. Raises ValueError('format') / ValueError('past')."""
    text = text.strip()
    now = datetime.now(config.TIMEZONE)
    dt = None
    for fmt, kind in (("%H:%M", "time"), ("%m-%d %H:%M", "md"),
                      ("%m/%d %H:%M", "md"), ("%Y-%m-%d %H:%M", "full")):
        try:
            p = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if kind == "time":
            dt = now.replace(hour=p.hour, minute=p.minute, second=0, microsecond=0)
        elif kind == "md":
            dt = now.replace(month=p.month, day=p.day, hour=p.hour, minute=p.minute,
                             second=0, microsecond=0)
        else:
            dt = p.replace(tzinfo=config.TIMEZONE)
        break
    if dt is None:
        raise ValueError("format")
    if dt < now:
        raise ValueError("past")
    return int(dt.timestamp())


async def union_solved(participants):
    """Union of every participant's solved problems (for all-unsolved selection).
    Returns (solved_ids, unreadable_usernames). Raises SessionExpired if the bot's
    own session is dead (that aborts creation)."""
    result: set[int] = set()
    unreadable: list[str] = []
    for p in participants:
        try:
            result |= await asyncio.to_thread(pe_client.solved_ids, p["pe_username"])
        except pe_client.SessionExpired:
            raise
        except Exception:
            # not friended / unreadable — surface it rather than silently skipping.
            unreadable.append(p["pe_username"])
    return result, unreadable


def leaderboard_embed(contest_row) -> discord.Embed:
    problems = sorted(db.contest_problems(contest_row["id"]), key=lambda p: p["problem_id"])
    smap = db.solved_map(contest_row["id"])
    lb = {r["discord_id"]: r for r in db.leaderboard(contest_row["id"])}
    max_pts = sum(p["difficulty"] for p in problems)
    status = contest_row["status"]
    e = discord.Embed(
        title=msg.lb_title(contest_row["name"]),
        color=0x2ecc71 if status == "running" else 0x95a5a6,
    )

    # Every registered participant is a row (0-solve ones show all ·).
    entries = []
    for p in db.all_participants():
        info = lb.get(p["discord_id"])
        entries.append({
            "name": p["pe_username"],
            "pts": info["pts"] if info else 0,
            "last": info["last_solve"] if info else None,
            "solved": smap.get(p["discord_id"], set()),
        })
    if not entries:
        e.description = msg.LB_EMPTY
        e.set_footer(text=msg.lb_footer(max_pts, len(problems), status))
        return e
    # Rank: points desc, then earliest last-solve (non-solvers last).
    entries.sort(key=lambda x: (-x["pts"], x["last"] if x["last"] is not None else float("inf")))

    # Monospace table: rank | name | pts | one ✓/· column per problem.
    name_w = min(max(len(e2["name"]) for e2 in entries), 14)
    headers = [f"P{p['problem_id']}" for p in problems]
    col_w = [max(len(h), 3) for h in headers]

    def line(rank, name, pts, marks):
        cells = " ".join(marks[i].center(col_w[i]) for i in range(len(marks)))
        return f"{rank:>2} {name[:name_w].ljust(name_w)} {str(pts):>4} {cells}"

    head = (f"{'#':>2} {'name'.ljust(name_w)} {'pts':>4} "
            + " ".join(headers[i].center(col_w[i]) for i in range(len(headers))))
    body = []
    for i, ent in enumerate(entries, 1):
        marks = ["✓" if p["problem_id"] in ent["solved"] else "·" for p in problems]
        body.append(line(i, ent["name"], ent["pts"], marks))
    e.description = "```\n" + head + "\n" + "\n".join(body) + "\n```"
    e.set_footer(text=msg.lb_footer(max_pts, len(problems), status))
    return e


async def refresh_leaderboard(contest_row):
    """Update (or create) the leaderboard message for a contest."""
    channel = client.get_channel(contest_row["channel_id"])
    if channel is None:
        return
    embed = leaderboard_embed(contest_row)
    msg_id = contest_row["leaderboard_message_id"]
    if msg_id:
        try:
            existing = await channel.fetch_message(msg_id)
            await existing.edit(embed=embed)
            return
        except discord.NotFound:
            pass
    sent = await channel.send(embed=embed)
    db.set_leaderboard_message(contest_row["id"], sent.id)


# ---------------------------------------------------------------- commands

async def _do_register(user_id: int, display_name: str, pe_username: str, friend_key: str):
    """Core registration logic. Returns (ok, private_error_msg, public_success_msg).

    NOTE: no profile.txt existence gate (unreliable for private profiles). The
    authoritative existence+friendship check is reading the friend's progress.
    """
    uname = (pe_username or "").strip()
    fkey = (friend_key or "").strip()
    if not pe_client.valid_friend_key(fkey):
        return False, msg.REGISTER_INVALID_KEY, None
    count = db.participant_count()
    if db.get_participant(user_id) is None and count >= config.FRIEND_LIMIT:
        return False, msg.register_limit(config.FRIEND_LIMIT), None
    db.upsert_participant(user_id, uname, fkey)
    # Auto-add as a friend on the bot's PE account (was a manual operator step).
    # Best-effort: the solved_ids check below is the authoritative confirmation.
    try:
        await asyncio.to_thread(pe_client.add_friend, fkey)
    except Exception:
        pass
    try:
        await asyncio.to_thread(pe_client.solved_ids, uname)
        note = msg.REGISTER_NOTE_VERIFIED
    except (pe_client.ProgressUnavailable, pe_client.SolveStatusUnavailable):
        note = msg.REGISTER_NOTE_PENDING   # wrong username OR not friended yet
    except pe_client.SessionExpired:
        note = msg.REGISTER_NOTE_UNKNOWN   # bot's own PE session problem
    except Exception:
        note = msg.REGISTER_NOTE_UNKNOWN
    warn = ""
    if count + 1 >= config.FRIEND_LIMIT - 5:
        warn = msg.register_warn(count + 1, config.FRIEND_LIMIT)
    return True, None, msg.register_ok(display_name, uname, note, warn)


async def _finish_register(interaction: discord.Interaction, ok, priv, pub):
    """Public success (posted to the channel) or ephemeral error to the user.
    Uses channel.send for the public part — non-ephemeral followups after an
    ephemeral defer/response stay private, so we must post to the channel."""
    if ok:
        await interaction.channel.send(pub)
        await interaction.followup.send(msg.REGISTER_ACK, ephemeral=True)
    else:
        await interaction.followup.send(priv, ephemeral=True)


class RegisterModal(discord.ui.Modal):
    """Registration form. Prefills the PE username when updating an existing entry."""
    def __init__(self, existing_username: str | None = None):
        super().__init__(title="参加登録にゃ 🐾")
        self.pe_username = discord.ui.TextInput(
            label="PEユーザ名", placeholder="Project Eulerのユーザ名",
            default=existing_username or "", required=True, max_length=64)
        self.friend_key = discord.ui.TextInput(
            label="friend key", placeholder="例: 123456_xxxxxxxxxxxx",
            required=True, max_length=128)
        self.add_item(self.pe_username)
        self.add_item(self.friend_key)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, priv, pub = await _do_register(
            interaction.user.id, interaction.user.display_name,
            str(self.pe_username), str(self.friend_key))
        await _finish_register(interaction, ok, priv, pub)


class RegisterPanel(discord.ui.View):
    """Persistent view: a button that opens the registration modal, guiding
    unregistered users to register and letting registered users update."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="参加登録するにゃ 🐾", style=discord.ButtonStyle.primary,
                       custom_id="pe_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        part = db.get_participant(interaction.user.id)
        # Not registered -> guide into the (blank) registration form.
        # Already registered -> same form, prefilled, so it doubles as an update.
        existing = part["pe_username"] if part else None
        await interaction.response.send_modal(RegisterModal(existing_username=existing))


@tree.command(name="register", description="参加登録ボタンを設置するにゃ（ボタンから登録）")
async def register(interaction: discord.Interaction):
    await interaction.channel.send(msg.REGISTER_PANEL_TEXT, view=RegisterPanel())
    await interaction.response.send_message("参加登録ボタンを設置したにゃ！", ephemeral=True)


def _contest_type_choices():
    out = []
    for k, v in contest_mod.CONTEST_TYPES.items():
        out.append(app_commands.Choice(
            name=f"{v['label']}（難易度{v['min']}-{v['max']}% / {v['num']}問 / {v['duration']}分）",
            value=k))
    return out


@tree.command(name="create_contest", description="コンテストを作成するにゃ（誰でもOK）")
@app_commands.describe(
    start="開始時刻: '21:00'(今日) / '07-15 21:00' / '2026-07-15 21:00'（"
          + str(config.TIMEZONE) + "・過去は不可）",
    contest_type="難易度タイプ（問題数・制限時間もこれで決まるにゃ）",
)
@app_commands.choices(contest_type=_contest_type_choices())
async def create_contest(interaction: discord.Interaction, start: str,
                         contest_type: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    try:
        start_epoch = parse_start(start)
    except ValueError as e:
        which = str(e)
        await interaction.followup.send(
            msg.PAST_TIME if which == "past" else msg.BAD_TIME, ephemeral=True)
        return

    spec = contest_mod.CONTEST_TYPES[contest_type.value]
    participants = db.all_participants()
    if not participants:
        await interaction.followup.send(msg.NO_PARTICIPANTS, ephemeral=True)
        return

    try:
        catalog = await asyncio.to_thread(pe_client.catalog)
        excluded, unreadable = await union_solved(participants)
    except pe_client.SessionExpired as e:
        await interaction.followup.send(msg.session_expired(e), ephemeral=True)
        return

    # If some participants can't be read, their solved problems can't be excluded —
    # abort rather than risk handing out a problem someone already solved.
    if unreadable:
        await interaction.followup.send(msg.unreadable_participants(unreadable),
                                        ephemeral=True)
        return

    try:
        problems = contest_mod.select_problems(catalog, excluded, contest_type.value)
    except ValueError as e:
        await interaction.followup.send(msg.select_fail(e), ephemeral=True)
        return

    # Auto-generate the name from tier + start time (JST).
    when = datetime.fromtimestamp(start_epoch, config.TIMEZONE).strftime("%m-%d %H:%M")
    name = f"{spec['label']}コンテスト {when}"
    cid = db.create_contest(name, start_epoch, spec["duration"], contest_type.value,
                            spec["num"], interaction.guild_id,
                            interaction.channel_id, interaction.user.id)
    db.add_contest_problems(cid, problems)
    # Public announcement (channel.send — ephemeral defer would keep it private).
    await interaction.channel.send(
        msg.create_ok(cid, name, start_epoch, spec["duration"],
                      contest_type.value, len(problems)))
    await interaction.followup.send(msg.create_ack(), ephemeral=True)


class SubmitView(discord.ui.View):
    def __init__(self, contest_row, pe_username: str, discord_id: int):
        super().__init__(timeout=120)
        self.contest_row = contest_row
        self.pe_username = pe_username
        self.discord_id = discord_id
        options = []
        for p in db.contest_problems(contest_row["id"]):
            if db.has_solve(contest_row["id"], discord_id, p["problem_id"]):
                continue
            options.append(discord.SelectOption(
                label=f"Problem {p['problem_id']} — {p['difficulty']}pt",
                description=(p["title"] or "")[:100],
                value=str(p["problem_id"]),
            ))
        if options:
            self.select = discord.ui.Select(
                placeholder=msg.SELECT_PLACEHOLDER, options=options[:25])
            self.select.callback = self.on_select
            self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        pid = int(self.select.values[0])
        try:
            grid = await asyncio.to_thread(pe_client.fetch_progress_grid, self.pe_username)
        except pe_client.ProgressUnavailable:
            await interaction.followup.send(msg.cannot_read_progress(), ephemeral=True)
            return
        except pe_client.SessionExpired as e:
            await interaction.followup.send(msg.session_expired(e), ephemeral=True)
            return
        if not pe_client._exposes_solve_status(grid):
            await interaction.followup.send(msg.cannot_read_progress(), ephemeral=True)
            return
        cell = grid.get(pid)
        if not cell or not cell.solved:
            await interaction.followup.send(msg.not_solved(pid), ephemeral=True)
            return
        prob = next((p for p in db.contest_problems(self.contest_row["id"])
                     if p["problem_id"] == pid), None)
        points = prob["difficulty"] if prob else cell.difficulty
        new = db.record_solve(self.contest_row["id"], self.discord_id, pid,
                              points, cell.solved_epoch)
        if not new:
            await interaction.followup.send(msg.already_counted(pid), ephemeral=True)
            return
        await interaction.followup.send(
            msg.submit_ok(interaction.user.display_name, pid, points), ephemeral=True)
        await refresh_leaderboard(db.get_contest(self.contest_row["id"]))


@tree.command(name="submit", description="ACした問題番号を提出するにゃ")
async def submit(interaction: discord.Interaction):
    part = db.get_participant(interaction.user.id)
    if not part:
        await interaction.response.send_message(msg.NOT_REGISTERED, ephemeral=True)
        return
    contest_row = db.latest_running_contest(interaction.guild_id)
    if not contest_row:
        await interaction.response.send_message(msg.NO_RUNNING, ephemeral=True)
        return
    view = SubmitView(contest_row, part["pe_username"], interaction.user.id)
    if not view.children:
        await interaction.response.send_message(msg.NOTHING_TO_SUBMIT, ephemeral=True)
        return
    await interaction.response.send_message(msg.SUBMIT_PROMPT, view=view, ephemeral=True)


def is_owner(user: discord.abc.User) -> bool:
    """True only for the configured OWNER (by username or numeric ID)."""
    o = config.OWNER.strip()
    return bool(o) and (user.name == o or str(user.id) == o)


@tree.context_menu(name="botメッセージを削除")
async def delete_bot_message(interaction: discord.Interaction, message: discord.Message):
    if not is_owner(interaction.user):
        await interaction.response.send_message(msg.NOT_OWNER, ephemeral=True)
        return
    if message.author.id != interaction.client.user.id:
        await interaction.response.send_message(msg.NOT_BOT_MESSAGE, ephemeral=True)
        return
    await message.delete()
    await interaction.response.send_message(msg.DELETED, ephemeral=True)


@tree.command(name="leaderboard", description="現在の順位表を表示するにゃ")
async def leaderboard_cmd(interaction: discord.Interaction):
    contest_row = db.latest_running_contest(interaction.guild_id)
    if not contest_row:
        finished = db.contests_by_status("finished")
        contest_row = finished[-1] if finished else None
    if not contest_row:
        await interaction.response.send_message(msg.NO_CONTEST, ephemeral=True)
        return
    await interaction.response.send_message(embed=leaderboard_embed(contest_row))


@tree.command(name="recommend", description="問題を推薦（投票）するにゃ")
@app_commands.describe(problem_id="推薦したいPEの問題番号")
async def recommend(interaction: discord.Interaction, problem_id: int):
    await interaction.response.defer(ephemeral=True)
    try:
        cat = await asyncio.to_thread(pe_client.catalog_cached)
    except pe_client.SessionExpired as e:
        await interaction.followup.send(msg.session_expired(e), ephemeral=True)
        return
    cell = cat.get(problem_id)
    if not cell:
        await interaction.followup.send(msg.recommend_invalid(problem_id), ephemeral=True)
        return
    name = interaction.user.display_name
    if not db.add_vote(interaction.user.id, problem_id):
        await interaction.followup.send(msg.recommend_dup(name, problem_id), ephemeral=True)
        return
    await interaction.followup.send(
        msg.recommend_ok(name, problem_id, cell.title), ephemeral=True)


@tree.command(name="recommendations",
              description="人気のおすすめ問題（あなたが未ACのみ・最大5件）にゃ")
async def recommendations(interaction: discord.Interaction):
    part = db.get_participant(interaction.user.id)
    if not part:
        await interaction.response.send_message(msg.NOT_REGISTERED, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        cat = await asyncio.to_thread(pe_client.catalog_cached)
        solved = await asyncio.to_thread(pe_client.solved_ids, part["pe_username"])
    except pe_client.ProgressUnavailable:
        await interaction.followup.send(msg.cannot_read_progress(), ephemeral=True)
        return
    except pe_client.SessionExpired as e:
        await interaction.followup.send(msg.session_expired(e), ephemeral=True)
        return
    picks = []
    for pid, votes in db.vote_counts():          # already sorted by votes desc
        if pid in solved:
            continue
        cell = cat.get(pid)
        if not cell:
            continue
        picks.append((pid, votes, cell))
        if len(picks) >= 5:
            break
    if not picks:
        await interaction.followup.send(msg.REC_EMPTY, ephemeral=True)
        return
    e = discord.Embed(title=msg.rec_title(interaction.user.display_name), color=0x3498db)
    e.description = "\n".join(
        f"{i}. [Problem {pid}](https://projecteuler.net/problem={pid}) "
        f"「{cell.title}」— {votes}票 / 難易度{cell.difficulty}%"
        for i, (pid, votes, cell) in enumerate(picks, 1))
    await interaction.followup.send(embed=e, ephemeral=True)


def _build_tweet(contest_row, rows) -> str:
    lines = [f"🏆 {contest_row['name']} の結果！"]
    medals = ["🥇", "🥈", "🥉"]
    if rows:
        for i, r in enumerate(rows[:3]):
            lines.append(f"{medals[i]} {r['pe_username']} {r['pts']}pt")
    else:
        lines.append("（参加者なし）")
    lines.append("#ProjectEuler #オイラーにゃん")
    return "\n".join(lines)[:270]


@tree.command(name="tweet", description="最後のコンテスト結果のツイート文を作るにゃ")
async def tweet(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    contest_row = db.latest_contest(interaction.guild_id)
    if not contest_row:
        await interaction.followup.send(msg.NO_CONTEST_TWEET, ephemeral=True)
        return
    text = _build_tweet(contest_row, db.leaderboard(contest_row["id"]))
    url = "https://twitter.com/intent/tweet?text=" + quote(text)
    await interaction.channel.send(msg.tweet_panel(text, url))
    await interaction.followup.send("ツイート文を出したにゃ🐦", ephemeral=True)


@tree.command(name="service", description="使えるコマンド一覧を表示するにゃ")
async def service(interaction: discord.Interaction):
    e = discord.Embed(title="🐾 オイラーにゃん コマンド一覧", color=0xf1c40f)
    e.description = "\n".join([
        "**/register** — 参加登録ボタンを設置（ボタン→フォームで登録）",
        "**/create_contest** `start` `contest_type` — コンテスト作成（誰でも）",
        "**/submit** — ACした問題を提出（開催中のみ）",
        "**/leaderboard** — 順位表（参加者 × 各問題のAC状況）",
        "**/recommend** `problem_id` — 問題を推薦（投票）",
        "**/recommendations** — 人気のおすすめ問題（未ACのみ・最大5件）",
        "**/tweet** — 最後のコンテスト結果のツイート文を生成",
        "**/service** — このコマンド一覧",
        "（botメッセージを右クリック→アプリ→「botメッセージを削除」はオーナー限定にゃ）",
    ])
    await interaction.response.send_message(embed=e, ephemeral=True)


# ---------------------------------------------------------------- scheduler

@tasks.loop(seconds=30)
async def scheduler():
    now = int(time.time())
    # scheduled -> running
    for c in db.contests_by_status("scheduled"):
        if now >= c["start_epoch"]:
            db.set_contest_status(c["id"], "running")
            channel = client.get_channel(c["channel_id"])
            if channel:
                probs = db.contest_problems(c["id"])
                lst = "\n".join(
                    f"• [Problem {p['problem_id']}](https://projecteuler.net/problem={p['problem_id']}) "
                    f"— {p['difficulty']}pt" for p in probs)
                await channel.send(msg.contest_start(c["name"], c["duration_min"], lst))
                await refresh_leaderboard(db.get_contest(c["id"]))
    # running -> finished
    for c in db.contests_by_status("running"):
        if now >= c["start_epoch"] + c["duration_min"] * 60:
            db.set_contest_status(c["id"], "finished")
            await refresh_leaderboard(db.get_contest(c["id"]))
            channel = client.get_channel(c["channel_id"])
            if channel:
                await channel.send(msg.contest_end(c["name"]))


@client.event
async def on_ready():
    db.init()
    # Sync to every guild the bot is actually in (robust against a wrong GUILD_ID).
    # Fall back to GUILD_ID if guild list isn't populated yet.
    targets = list(client.guilds) or (
        [discord.Object(id=config.GUILD_ID)] if config.GUILD_ID else [])
    STATUS["user"] = str(client.user)
    STATUS["guilds"] = [g.id for g in client.guilds]
    if not targets:
        print("⚠️ bot is in no guilds — invite it to your server first.")
    for g in targets:
        try:
            tree.copy_global_to(guild=g)
            synced = await tree.sync(guild=g)
            STATUS["synced"][str(g.id)] = len(synced)
            print(f"synced {len(synced)} slash commands to guild {g.id}")
        except discord.Forbidden:
            STATUS["errors"].append(f"403 Missing Access on guild {getattr(g, 'id', '?')}")
            print(f"⚠️ 403 Missing Access syncing to guild {getattr(g, 'id', '?')}: "
                  "re-invite the bot with 'applications.commands' scope. (Bot stays online.)")
        except Exception as e:
            STATUS["errors"].append(f"{getattr(g, 'id', '?')}: {e!r}")
            print(f"⚠️ command sync failed for guild {getattr(g, 'id', '?')}: {e!r}")
    global _panel_registered
    if not _panel_registered:
        client.add_view(RegisterPanel())  # make the button work after restarts
        _panel_registered = True
    if not scheduler.is_running():
        scheduler.start()
    STATUS["ready"] = True
    print(msg.ready_log(client.user))


class _HealthHandler(BaseHTTPRequestHandler):
    """Tiny HTTP endpoint so PaaS platforms (Render free) see a live web service
    and an external pinger (cron-job.org) can keep it awake. Also returns live
    status JSON for remote diagnosis (guild IDs / sync counts / errors)."""
    def do_GET(self):
        body = json.dumps(STATUS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence access logs
        pass


def start_keepalive_server():
    """Bind to $PORT (Render requires web services to open a port). No-op locally
    if PORT is unset AND we can't bind — but we default to 8080 so it always runs."""
    port = int(os.getenv("PORT", "8080"))
    try:
        srv = HTTPServer(("0.0.0.0", port), _HealthHandler)
    except OSError as e:
        print(f"keepalive server not started ({e})")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"keepalive HTTP server on :{port}")


def main():
    config.require("DISCORD_TOKEN", "GUILD_ID", "PE_BOT_USERNAME")
    start_keepalive_server()
    client.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
