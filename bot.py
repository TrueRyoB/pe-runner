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
STATUS = {"ready": False, "user": None, "guilds": [], "synced": {}, "errors": [],
          "started_at": None, "db": None}
_views_added = False

import config
import contest as contest_mod
import db
import messages as msg
import pe_client
import rating

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
            continue
        except pe_client.SessionExpired:
            raise
        except Exception:
            pass
        # Link may have broken (they un-friended / went private). Try re-adding the
        # friend once and retry; only if that still fails, skip them (don't abort).
        try:
            await asyncio.to_thread(pe_client.add_friend, p["friend_key"])
            result |= await asyncio.to_thread(pe_client.solved_ids, p["pe_username"])
        except pe_client.SessionExpired:
            raise
        except Exception:
            unreadable.append(p["pe_username"])
    return result, unreadable


def leaderboard_embed(contest_row) -> discord.Embed:
    # Presentation order = how the problems were announced (difficulty asc, id tiebreak),
    # NOT problem-id order. db.contest_problems already returns them ORDER BY difficulty.
    problems = db.contest_problems(contest_row["id"])
    smap = db.solved_map(contest_row["id"])
    pmap = db.presolved_map(contest_row["id"])
    tmap = db.solve_times_map(contest_row["id"])
    lb = {r["discord_id"]: r for r in db.leaderboard(contest_row["id"])}
    max_pts = sum(p["difficulty"] for p in problems)
    status = contest_row["status"]
    start = contest_row["start_epoch"]
    end = start + contest_row["duration_min"] * 60
    e = discord.Embed(
        title=msg.lb_title(contest_row["name"]),
        color=0x2ecc71 if status == "running" else 0x95a5a6,
    )
    # Live end-time / remaining line (Discord dynamic timestamps auto-update, so a
    # silent edit still shows the correct "残りN分" without re-sending).
    time_line = msg.lb_time_line(end, status)

    # AC cells show the confirmed time as elapsed-from-start (mm:ss). With many
    # problems (hardcore) mm:ss is too wide for a phone, so fall back to minutes-only.
    compact = len(problems) > 6

    def fmt_time(epoch):
        elapsed = max(0, epoch - start)
        if compact:
            return str(elapsed // 60)          # minutes only
        m, s = divmod(elapsed, 60)
        return f"{m}:{s:02d}"

    # Every JOINED participant is a row (0-solve ones show all ·).
    entries = []
    for p in db.joined_participants(contest_row["id"]):
        info = lb.get(p["discord_id"])
        entries.append({
            "name": p["pe_username"],
            "pts": info["pts"] if info else 0,
            "last": info["last_solve"] if info else None,
            "solved": smap.get(p["discord_id"], set()),
            "presolved": pmap.get(p["discord_id"], set()),
            "times": tmap.get(p["discord_id"], {}),
        })
    if not entries:
        e.description = time_line + msg.LB_EMPTY
        e.set_footer(text=msg.lb_footer(max_pts, len(problems), status))
        return e
    # Rank: points desc, then earliest last-solve (non-solvers last).
    entries.sort(key=lambda x: (-x["pts"], x["last"] if x["last"] is not None else float("inf")))

    def mark(pid, ent):
        if pid in ent["presolved"]:
            return "x"          # already solved before joining -> 0 pts
        if pid in ent["solved"]:
            return fmt_time(ent["times"].get(pid, 0))
        return "·"

    # Monospace table: rank | name | pts | one time/·/x column per problem.
    name_w = min(max(len(e2["name"]) for e2 in entries), 14)
    headers = [f"P{p['problem_id']}" for p in problems]
    body_marks = [[mark(p["problem_id"], ent) for p in problems] for ent in entries]
    col_w = [max(len(headers[i]), 3,
                 *(len(row[i]) for row in body_marks)) for i in range(len(problems))]

    def line(rank, name, pts, marks):
        cells = " ".join(marks[i].center(col_w[i]) for i in range(len(marks)))
        return f"{rank:>2} {name[:name_w].ljust(name_w)} {str(pts):>4} {cells}"

    head = (f"{'#':>2} {'name'.ljust(name_w)} {'pts':>4} "
            + " ".join(headers[i].center(col_w[i]) for i in range(len(headers))))
    body = [line(i, ent["name"], ent["pts"], body_marks[i - 1])
            for i, ent in enumerate(entries, 1)]
    e.description = time_line + "```\n" + head + "\n" + "\n".join(body) + "\n```"
    e.set_footer(text=msg.lb_footer(max_pts, len(problems), status))
    return e


def record_contest_performances(contest_row):
    """At contest finish, store each participant's performance (shaped by the contest
    FORMAT), then snapshot their post-contest rating (for /profile's +delta / highest).
    Only participants who solved >=1 (i.e. appear in the leaderboard) get one, so
    skipping/not-solving never records a (rating-lowering) performance."""
    cid = contest_row["id"]
    if db.contest_has_performances(cid):
        return
    lb = db.leaderboard(cid)  # ranked: pts desc, last_solve asc
    max_pts = sum(p["difficulty"] for p in db.contest_problems(cid)) or 1
    field = len(lb)
    at = int(time.time())
    spec = contest_mod.CONTEST_TYPES.get(contest_row["contest_type"], {})
    cap, floor = spec.get("perf_cap"), spec.get("loss_floor", 0.0)
    for i, r in enumerate(lb):
        perf = rating.performance(i + 1, field, r["pts"] or 0, max_pts,
                                  perf_cap=cap, loss_floor=floor)
        db.record_performance(r["discord_id"], cid, perf, at)
    # Snapshot the post-contest rating (decay=0 at finish => un-decayed) per participant.
    for r in lb:
        perfs = [p["perf"] for p in db.user_performances(r["discord_id"])]
        comp = rating.compute(perfs, at, at)
        if comp:
            db.record_rating_snapshot(r["discord_id"], cid, comp["rating"], at)


async def _ping(channel):
    """Play the channel's notification sound without leaving residue: send a tiny
    message and immediately retract it. Editing an embed is silent, so this is how a
    leaderboard update makes a sound (no special permissions needed)."""
    try:
        m = await channel.send("🔔")
        await m.delete()
    except Exception:
        pass


async def refresh_leaderboard(contest_row):
    """Update (or create) the leaderboard message for a contest."""
    channel = client.get_channel(int(contest_row["channel_id"]))
    if channel is None:
        return
    embed = leaderboard_embed(contest_row)
    msg_id = contest_row["leaderboard_message_id"]
    if msg_id:
        try:
            existing = await channel.fetch_message(msg_id)
            await existing.edit(embed=embed)
            await _ping(channel)   # the edit is silent — chime so players notice
            return
        except discord.NotFound:
            pass
    sent = await channel.send(embed=embed)  # a fresh send already chimes
    db.set_leaderboard_message(contest_row["id"], sent.id)


# ---------------------------------------------------------------- commands

async def _do_register(user_id: int, display_name: str, pe_username: str, friend_key: str):
    """Core registration. Returns (public_msg, private_msg).

    public_msg is set ONLY on verified success (progress readable), so the public
    announcement appears only when registration truly succeeds. Failures and
    pending (unreadable) cases are private to the user (public_msg=None).
    NOTE: no profile.txt existence gate; reading the friend's progress is the
    authoritative existence+friendship check.
    """
    uname = (pe_username or "").strip()
    fkey = (friend_key or "").strip()
    if not pe_client.valid_friend_key(fkey):
        return None, msg.REGISTER_INVALID_KEY
    count = db.participant_count()
    if db.get_participant(user_id) is None and count >= config.FRIEND_LIMIT:
        return None, msg.register_limit(config.FRIEND_LIMIT)
    db.upsert_participant(user_id, uname, fkey)
    # Auto-add as a friend on the bot's PE account (best-effort).
    try:
        await asyncio.to_thread(pe_client.add_friend, fkey)
    except Exception:
        pass
    try:
        await asyncio.to_thread(pe_client.solved_ids, uname)
    except (pe_client.ProgressUnavailable, pe_client.SolveStatusUnavailable):
        return None, msg.register_pending(display_name, uname, msg.REGISTER_NOTE_PENDING)
    except pe_client.SessionExpired:
        return None, msg.register_pending(display_name, uname, msg.REGISTER_NOTE_UNKNOWN)
    except Exception:
        return None, msg.register_pending(display_name, uname, msg.REGISTER_NOTE_UNKNOWN)
    # verified
    warn = ""
    if count + 1 >= config.FRIEND_LIMIT - 5:
        warn = msg.register_warn(count + 1, config.FRIEND_LIMIT)
    return msg.register_ok(display_name, uname, msg.REGISTER_NOTE_VERIFIED, warn), msg.REGISTER_ACK


async def _finish_register(interaction: discord.Interaction, public_msg, private_msg):
    """Public announcement only on verified success; otherwise private-only.
    channel.send for the public part (ephemeral followups stay private)."""
    if public_msg:
        await interaction.channel.send(public_msg)
    await interaction.followup.send(private_msg, ephemeral=True)


@tree.command(name="register", description="PEユーザ名とfriend keyで参加登録するにゃ")
@app_commands.describe(pe_username="Project Eulerのユーザ名", friend_key="あなたのfriend key")
async def register(interaction: discord.Interaction, pe_username: str, friend_key: str):
    await interaction.response.defer(ephemeral=True)
    public_msg, private_msg = await _do_register(
        interaction.user.id, interaction.user.display_name, pe_username, friend_key)
    await _finish_register(interaction, public_msg, private_msg)


def _contest_type_choices():
    out = []
    for k, v in contest_mod.CONTEST_TYPES.items():
        recipe = contest_mod.recipe_summary(v)
        out.append(app_commands.Choice(
            name=f"{v['label']}（{recipe} / {v['duration']}分）"[:100],
            value=k))
    return out


@tree.command(name="create_contest", description="コンテストを作成するにゃ（誰でもOK）")
@app_commands.describe(
    start="開始時刻: '21:00'(今日) / '07-15 21:00' / '2026-07-15 21:00'（"
          + str(config.TIMEZONE) + "・過去は不可）",
    contest_type="開催形式（問題構成・制限時間もこれで決まるにゃ）",
)
@app_commands.choices(contest_type=_contest_type_choices())
async def create_contest(interaction: discord.Interaction, start: str,
                         contest_type: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    try:
        start_epoch = parse_start(start)
    except ValueError as e:
        await interaction.followup.send(
            msg.PAST_TIME if str(e) == "past" else msg.BAD_TIME, ephemeral=True)
        return

    spec = contest_mod.CONTEST_TYPES[contest_type.value]
    now = int(time.time())
    # Draw problems at: no earlier than 1h before start and 10min after signups
    # open, no later than 5min before start; and never in the past.
    draw_epoch = max(now, min(start_epoch - 300, max(start_epoch - 3600, now + 600)))

    # AtCoder-style code + per-format serial (ERC001 / EHC001 / EFC001), permanent.
    seq = db.count_contests_by_type(contest_type.value) + 1
    name = f"{spec['code']}{seq:03d}"
    # hardcore's problem count depends on the randomly-drawn variant; store a nominal
    # now (0 = unknown) and set the real count at draw time (_draw_contest).
    cid = db.create_contest(name, start_epoch, spec["duration"], contest_type.value,
                            contest_mod.total_num(spec) or 0, interaction.guild_id,
                            interaction.channel_id, interaction.user.id, draw_epoch)
    # Public recruiting announcement with Join/Leave buttons (no problems yet —
    # they're drawn at draw_epoch from whoever actually joined).
    sent = await interaction.channel.send(
        msg.contest_recruiting(name, [], _recruit_subtitle(contest_type.value, start_epoch)),
        view=JoinView())
    db.set_join_message(cid, sent.id)
    await interaction.followup.send(msg.create_ack(), ephemeral=True)


def _recruit_subtitle(contest_type: str, start_epoch: int) -> str:
    """Context line under the terse code (ERC001): format, duration, recipe, start."""
    spec = contest_mod.CONTEST_TYPES.get(contest_type, {})
    label = spec.get("label", contest_type)
    dur = spec.get("duration", "?")
    recipe = contest_mod.recipe_summary(spec) if spec else ""
    return f"{label}・{dur}分・{recipe}・開始 <t:{start_epoch}:F>"


class JoinView(discord.ui.View):
    """Persistent toggle button. Join is allowed while the contest isn't finished
    (including AFTER the draw = late join). Leaving is only allowed before the draw
    (status 'recruiting'). A late joiner's already-solved drawn problems are recorded
    as pre-solved (shown 'x', worth 0)."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _refresh(self, interaction, c):
        ids = [p["discord_id"] for p in db.joined_participants(c["id"])]
        try:
            await interaction.message.edit(
                content=msg.contest_recruiting(
                    c["name"], ids, _recruit_subtitle(c["contest_type"], c["start_epoch"])),
                view=self, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            pass

    @discord.ui.button(label="参加する / 取り消す 🙋", style=discord.ButtonStyle.primary,
                       custom_id="contest_toggle")
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        c = db.contest_by_join_message(interaction.message.id)
        if c is None or c["status"] == "finished":
            await interaction.followup.send(msg.JOIN_CLOSED, ephemeral=True)
            return
        if db.get_participant(interaction.user.id) is None:
            await interaction.followup.send(msg.NOT_REGISTERED, ephemeral=True)
            return
        uid = interaction.user.id
        if db.is_joined(c["id"], uid):
            if c["status"] != "recruiting":   # after the draw: no leaving
                await interaction.followup.send(msg.CANNOT_LEAVE, ephemeral=True)
                return
            db.leave_contest(c["id"], uid)
            ack = msg.left(interaction.user.display_name, db.joined_count(c["id"]))
        else:
            db.join_contest(c["id"], uid)
            note = ""
            if c["status"] != "recruiting":   # late join: mark already-solved problems
                pre = await _record_presolved(c["id"], uid)
                if pre:
                    note = msg.late_join_presolved(pre)
            ack = msg.joined(interaction.user.display_name, db.joined_count(c["id"])) + note
        await interaction.followup.send(ack, ephemeral=True)
        await self._refresh(interaction, c)


async def _record_presolved(contest_id: int, discord_id: int) -> list[int]:
    """For a late joiner, record which drawn problems they had already solved.
    Returns the pre-solved problem ids (best-effort; empty on PE read failure)."""
    part = db.get_participant(discord_id)
    if not part:
        return []
    try:
        solved = await asyncio.to_thread(pe_client.solved_ids, part["pe_username"])
    except Exception:
        return []
    drawn = [p["problem_id"] for p in db.contest_problems(contest_id)]
    pre = [pid for pid in drawn if pid in solved]
    if pre:
        db.add_presolved(contest_id, discord_id, pre)
    return pre


@tree.command(name="submit",
              description="ACした問題をまとめて確認・計上するにゃ（番号選択は不要）")
async def submit(interaction: discord.Interaction):
    part = db.get_participant(interaction.user.id)
    if not part:
        await interaction.response.send_message(msg.NOT_REGISTERED, ephemeral=True)
        return
    contest_row = db.latest_running_contest(interaction.guild_id)
    if not contest_row:
        await interaction.response.send_message(msg.NO_RUNNING, ephemeral=True)
        return
    cid = contest_row["id"]
    uid = interaction.user.id
    if not db.is_joined(cid, uid):
        await interaction.response.send_message(msg.NOT_JOINED, ephemeral=True)
        return
    # Every contest problem this user hasn't already been credited for (and didn't
    # solve before joining). We check ALL of them against PE in one pass.
    candidates = [p for p in db.contest_problems(cid)
                  if not db.has_solve(cid, uid, p["problem_id"])
                  and not db.is_presolved(cid, uid, p["problem_id"])]
    if not candidates:
        await interaction.response.send_message(msg.NOTHING_TO_SUBMIT, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)   # PE fetch is slow
    try:
        grid = await asyncio.to_thread(pe_client.fetch_progress_grid, part["pe_username"])
    except pe_client.ProgressUnavailable:
        await interaction.followup.send(msg.cannot_read_progress(), ephemeral=True)
        return
    except pe_client.SessionExpired as e:
        await interaction.followup.send(msg.session_expired(e), ephemeral=True)
        return
    if not pe_client._exposes_solve_status(grid):
        await interaction.followup.send(msg.cannot_read_progress(), ephemeral=True)
        return
    newly = []
    for p in candidates:
        pid = p["problem_id"]
        cell = grid.get(pid)
        if cell and cell.solved:
            if db.record_solve(cid, uid, pid, p["difficulty"], cell.solved_epoch):
                newly.append((pid, p["difficulty"]))
    if not newly:
        await interaction.followup.send(msg.submit_none_new(), ephemeral=True)
        return
    await interaction.followup.send(
        msg.submit_batch_ok(interaction.user.display_name, newly), ephemeral=True)
    await refresh_leaderboard(db.get_contest(cid))


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


@tree.command(name="introduce", description="オイラーにゃんが自己紹介するにゃ（10秒で消える）")
async def introduce(interaction: discord.Interaction):
    # Public and auto-deletes after ~10s so it doesn't clutter the channel.
    await interaction.response.send_message(msg.INTRODUCE, delete_after=10)


@tree.command(name="say", description="オイラーにゃんに喋らせるにゃ（指定秒で消える）")
@app_commands.describe(message="喋らせる内容", seconds="消えるまでの秒数（1〜3600）")
async def say(interaction: discord.Interaction, message: str,
              seconds: app_commands.Range[int, 1, 3600]):
    # Public, auto-deletes after `seconds`. Mentions disabled so it can't be used
    # to ping @everyone/roles/users via the bot.
    await interaction.response.send_message(
        f"😺 {message}", delete_after=float(seconds),
        allowed_mentions=discord.AllowedMentions.none())


@tree.command(name="feedback", description="匿名でフィードバックを送るにゃ")
@app_commands.describe(message="送りたい内容（匿名・送信者は記録しないにゃ）")
async def feedback(interaction: discord.Interaction, message: str):
    db.add_feedback(message.strip())
    await interaction.response.send_message(msg.FEEDBACK_ACK, ephemeral=True)


@tree.command(name="feedback_list", description="届いたフィードバックを見る（オーナーのみ）")
@app_commands.describe(limit="表示件数（1〜50、既定20）")
async def feedback_list(interaction: discord.Interaction,
                        limit: app_commands.Range[int, 1, 50] = 20):
    if not is_owner(interaction.user):
        await interaction.response.send_message(msg.NOT_OWNER, ephemeral=True)
        return
    rows = db.list_feedback(limit)
    if not rows:
        await interaction.response.send_message(msg.FEEDBACK_EMPTY, ephemeral=True)
        return
    e = discord.Embed(title=msg.feedback_title(db.feedback_count()), color=0x1abc9c)
    e.description = "\n\n".join(
        f"**#{r['id']}** ({r['created_at'].replace('T', ' ')})\n{r['message']}"
        for r in rows)[:4000]
    ids = [r["id"] for r in rows]
    await interaction.response.send_message(
        embed=e, view=FeedbackReadView(ids), ephemeral=True)


class FeedbackReadView(discord.ui.View):
    """Shown with /feedback_list (owner-only, ephemeral). The button deletes exactly
    the feedback rows that were displayed (mark-as-read)."""
    def __init__(self, ids: list[int]):
        super().__init__(timeout=600)
        self.ids = ids

    @discord.ui.button(label="閲覧済み（表示分を削除）🗑️", style=discord.ButtonStyle.danger)
    async def mark_read(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner(interaction.user):
            await interaction.response.send_message(msg.NOT_OWNER, ephemeral=True)
            return
        db.delete_feedback(self.ids)
        await interaction.response.edit_message(
            content=msg.feedback_cleared(len(self.ids)), embed=None, view=None)


@tree.command(name="service", description="使えるコマンド一覧を表示するにゃ")
async def service(interaction: discord.Interaction):
    e = discord.Embed(title="🐾 オイラーにゃん コマンド一覧", color=0xf1c40f)
    e.description = "\n".join([
        "**/register** `pe_username` `friend_key` — 参加登録",
        "**/create_contest** `start` `contest_type` — コンテスト作成（誰でも）",
        "**/submit** — ACした問題をまとめて確認・計上（開催中のみ）",
        "**/leaderboard** — 順位表（参加者 × 各問題のAC時刻）",
        "**/recommend** `problem_id` — 問題を推薦（投票）",
        "**/recommendations** — 人気のおすすめ問題（未ACのみ・最大5件）",
        "**/tweet** — 最後のコンテスト結果のツイート文を生成",
        "**/rating** — コミュニティ・レーティング（AtCoder風・非活動で減衰）",
        "**/profile** `pe_username` — 指定ユーザの詳しいレート（+差分・最高）",
        "**/introduce** — オイラーにゃんの自己紹介（10秒で消える）",
        "**/say** `message` `seconds` — 指定内容を喋らせる（指定秒で消える）",
        "**/feedback** `message` — 匿名でフィードバックを送る",
        "**/service** — このコマンド一覧",
        "（`/feedback_list`・botメッセージ削除はオーナー限定にゃ）",
    ])
    await interaction.response.send_message(embed=e, ephemeral=True)


@tree.command(name="rating", description="コミュニティ・レーティングを表示するにゃ")
async def rating_cmd(interaction: discord.Interaction):
    perfs = db.all_performances()  # joined w/ names, at_epoch DESC (=> recent first)
    if not perfs:
        await interaction.response.send_message(msg.RATING_EMPTY, ephemeral=True)
        return
    by_user: dict = {}
    for row in perfs:
        u = by_user.setdefault(row["discord_id"],
                               {"name": row["pe_username"], "perfs": [], "last": 0})
        u["perfs"].append(row["perf"])            # already recent-first
        u["last"] = max(u["last"], row["at_epoch"])
    now = int(time.time())
    ranked = []
    for u in by_user.values():
        r = rating.compute(u["perfs"], u["last"], now)
        if r:
            ranked.append((u["name"], r))
    ranked.sort(key=lambda x: -x[1]["rating"])

    name_w = min(max(len(n) for n, _ in ranked), 14)

    def line(rank, name, r):
        days = int(r["days_inactive"])
        tag = f"{days}d" if days > 0 else "今"
        return f"{rank:>2} {name[:name_w].ljust(name_w)} {r['rating']:>5} {r['n']:>2}戦 {tag:>4}"

    head = f"{'#':>2} {'name'.ljust(name_w)} {'rate':>5} {'':>3} {'最終':>4}"
    body = [line(i, n, r) for i, (n, r) in enumerate(ranked, 1)]
    e = discord.Embed(title=msg.RATING_TITLE, color=0x9b59b6)
    e.description = "```\n" + head + "\n" + "\n".join(body) + "\n```"
    e.set_footer(text=msg.rating_footer())
    await interaction.response.send_message(embed=e)


@tree.command(name="profile", description="指定PEユーザの詳しいレートを表示するにゃ")
@app_commands.describe(pe_username="見たいPEユーザ名")
async def profile_cmd(interaction: discord.Interaction, pe_username: str):
    part = db.get_participant_by_pe(pe_username)
    if not part:
        await interaction.response.send_message(
            msg.profile_not_found(pe_username), ephemeral=True)
        return
    perfs = db.user_performances(part["discord_id"])   # recent first
    snaps = db.rating_snapshots(part["discord_id"])     # oldest first
    if not perfs or not snaps:
        await interaction.response.send_message(
            msg.profile_no_rating(part["pe_username"]), ephemeral=True)
        return
    now = int(time.time())
    last = max(p["at_epoch"] for p in perfs)
    live = rating.compute([p["perf"] for p in perfs], last, now)
    # AtCoder-style triple uses the (un-decayed) snapshots so +delta / highest stay
    # consistent; the live decayed value is shown separately as an extra note.
    current = snaps[-1]["rating"]
    prev = snaps[-2]["rating"] if len(snaps) >= 2 else 0
    delta = current - prev
    highest = max(s["rating"] for s in snaps)
    e = discord.Embed(title=msg.profile_title(part["pe_username"]), color=0x9b59b6)
    e.description = msg.profile_body(current, delta, highest, live, len(snaps))
    e.set_footer(text=msg.rating_footer())
    await interaction.response.send_message(embed=e)


# ---------------------------------------------------------------- scheduler

def _problem_list_md(problems) -> str:
    """Markdown bullet list. Accepts rows with 'problem_id' or dicts with 'id'."""
    out = []
    for p in problems:
        pid = p["problem_id"] if "problem_id" in p.keys() else p["id"]
        out.append(f"• [Problem {pid}](https://projecteuler.net/problem={pid}) "
                   f"— {p['difficulty']}pt")
    return "\n".join(out)


async def _draw_contest(contest_row):
    """Draw problems from the JOINED participants' all-unsolved pool, post the list."""
    cid = contest_row["id"]
    channel = client.get_channel(int(contest_row["channel_id"]))
    joined = db.joined_participants(cid)
    if not joined:
        db.set_contest_status(cid, "finished")
        if channel:
            await channel.send(msg.contest_no_joiners(contest_row["name"]))
        return
    try:
        catalog = await asyncio.to_thread(pe_client.catalog)
        excluded, _unreadable = await union_solved(joined)
    except pe_client.SessionExpired:
        return  # leave recruiting; retry on the next tick
    try:
        problems = contest_mod.select_problems(catalog, excluded, contest_row["contest_type"])
    except ValueError as e:
        db.set_contest_status(cid, "finished")
        if channel:
            await channel.send(msg.draw_failed(contest_row["name"], e))
        return
    db.add_contest_problems(cid, problems)
    db.set_num_problems(cid, len(problems))   # actual count (hardcore variant now known)
    db.set_contest_status(cid, "scheduled")
    if channel:
        await channel.send(msg.contest_drawn(
            contest_row["name"], contest_row["start_epoch"],
            _problem_list_md(problems), db.joined_count(cid)))


@tasks.loop(seconds=30)
async def scheduler():
    now = int(time.time())
    # recruiting -> scheduled (draw problems from the joined participants)
    for c in db.contests_by_status("recruiting"):
        if c["draw_epoch"] is not None and now >= c["draw_epoch"]:
            await _draw_contest(c)
    # scheduled -> running
    for c in db.contests_by_status("scheduled"):
        if now >= c["start_epoch"]:
            db.set_contest_status(c["id"], "running")
            channel = client.get_channel(int(c["channel_id"]))
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
            record_contest_performances(db.get_contest(c["id"]))  # update ratings
            await refresh_leaderboard(db.get_contest(c["id"]))
            channel = client.get_channel(int(c["channel_id"]))
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
    global _views_added
    if not _views_added:
        client.add_view(JoinView())  # persistent Join/Leave buttons survive restarts
        _views_added = True
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
    STATUS["started_at"] = int(time.time())  # to measure uptime / restart frequency
    STATUS["db"] = "turso" if db.USING_TURSO else "sqlite"
    start_keepalive_server()
    client.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
