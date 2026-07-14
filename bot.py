"""Discord bot: registration, contest creation, submission verification, leaderboard.

All user-facing text lives in messages.py (spoken by the mascot オイラーにゃん 🐱).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import tasks

import config
import contest as contest_mod
import db
import messages as msg
import pe_client

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------------------------------------------------------------- helpers

def is_organizer(interaction: discord.Interaction) -> bool:
    if config.ORGANIZER_ROLE_ID:
        member = interaction.user
        return isinstance(member, discord.Member) and any(
            r.id == config.ORGANIZER_ROLE_ID for r in member.roles
        )
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.manage_guild)


def parse_start(text: str) -> int:
    """'YYYY-MM-DD HH:MM' in configured TZ -> unix epoch."""
    dt = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=config.TIMEZONE)
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
    rows = db.leaderboard(contest_row["id"])
    problems = db.contest_problems(contest_row["id"])
    max_pts = sum(p["difficulty"] for p in problems)
    status = contest_row["status"]
    e = discord.Embed(
        title=msg.lb_title(contest_row["name"]),
        color=0x2ecc71 if status == "running" else 0x95a5a6,
    )
    if not rows:
        e.description = msg.LB_EMPTY
    else:
        lines = []
        for i, r in enumerate(rows, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            lines.append(f"{medal} **{r['pe_username']}** — {r['pts']} pts ({r['solved']}問)")
        e.description = "\n".join(lines)
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

@tree.command(name="register", description="PEユーザ名とfriend keyを登録するにゃ")
@app_commands.describe(pe_username="Project Eulerのユーザ名", friend_key="あなたのfriend key")
async def register(interaction: discord.Interaction, pe_username: str, friend_key: str):
    await interaction.response.defer(ephemeral=True)
    uname = pe_username.strip()
    fkey = friend_key.strip()

    # 1) friend key format check.
    if not pe_client.valid_friend_key(fkey):
        await interaction.followup.send(msg.REGISTER_INVALID_KEY, ephemeral=True)
        return

    # 2) username existence check (public profile endpoint).
    try:
        exists = await asyncio.to_thread(pe_client.username_exists, uname)
    except Exception:
        await interaction.followup.send(msg.register_check_failed(), ephemeral=True)
        return
    if not exists:
        await interaction.followup.send(msg.register_invalid_user(uname), ephemeral=True)
        return

    # 3) friend-cap safeguard (only for genuinely new registrants).
    count = db.participant_count()
    if db.get_participant(interaction.user.id) is None and count >= config.FRIEND_LIMIT:
        await interaction.followup.send(msg.register_limit(config.FRIEND_LIMIT), ephemeral=True)
        return

    db.upsert_participant(interaction.user.id, uname, fkey)

    # 4) can we already read their progress? (i.e. is friendship set up)
    try:
        await asyncio.to_thread(pe_client.solved_ids, uname)
        note = msg.REGISTER_NOTE_VERIFIED
    except (pe_client.ProgressUnavailable, pe_client.SolveStatusUnavailable):
        note = msg.REGISTER_NOTE_PENDING   # friendship not set up yet
    except pe_client.SessionExpired:
        note = msg.REGISTER_NOTE_UNKNOWN   # bot's own PE session problem
    except Exception:
        note = msg.REGISTER_NOTE_UNKNOWN

    warn = ""
    if count + 1 >= config.FRIEND_LIMIT - 5:
        warn = msg.register_warn(count + 1, config.FRIEND_LIMIT)
    await interaction.followup.send(msg.register_ok(uname, note, warn), ephemeral=True)


@tree.command(name="create_contest", description="コンテストを作成するにゃ（運営のみ）")
@app_commands.describe(
    name="コンテスト名",
    start="開始時刻 'YYYY-MM-DD HH:MM'（" + str(config.TIMEZONE) + "）",
    duration_minutes="開催時間（分）",
    contest_type="難易度分布のタイプ",
    num_problems="問題数",
)
@app_commands.choices(contest_type=[
    app_commands.Choice(name=k, value=k) for k in contest_mod.CONTEST_TYPES
])
async def create_contest(interaction: discord.Interaction, name: str, start: str,
                         duration_minutes: int, contest_type: app_commands.Choice[str],
                         num_problems: int):
    if not is_organizer(interaction):
        await interaction.response.send_message(msg.NOT_ORGANIZER, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        start_epoch = parse_start(start)
    except ValueError:
        await interaction.followup.send(msg.BAD_TIME, ephemeral=True)
        return

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
        problems = contest_mod.select_problems(
            catalog, excluded, contest_type.value, num_problems)
    except ValueError as e:
        await interaction.followup.send(msg.select_fail(e), ephemeral=True)
        return

    cid = db.create_contest(name, start_epoch, duration_minutes, contest_type.value,
                            num_problems, interaction.guild_id,
                            interaction.channel_id, interaction.user.id)
    db.add_contest_problems(cid, problems)
    await interaction.followup.send(
        msg.create_ok(cid, name, start_epoch, duration_minutes,
                      contest_type.value, len(problems)),
        ephemeral=True,
    )


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
        await interaction.followup.send(msg.submit_ok(pid, points), ephemeral=True)
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
    guild = discord.Object(id=config.GUILD_ID)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    if not scheduler.is_running():
        scheduler.start()
    print(msg.ready_log(client.user))


def main():
    config.require("DISCORD_TOKEN", "GUILD_ID", "PE_BOT_USERNAME", "PE_SESSION_COOKIE")
    client.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
