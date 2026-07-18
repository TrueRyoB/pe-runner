"""All user-facing text, spoken by the mascot: オイラーニャン.

Two registers, split by OBJECTIVITY (objectivity is what reads as official):
- Objective contest facts / records / operational status (recruiting, draw, start,
  standings, ratings, AC confirmations, join records) → OFFICIAL: 丁寧語, concise,
  no "にゃ", minimal emoji (conciseness is NOT emoji).
- Relational / subjective moments (self-intro, error guidance, post-contest chatter,
  social acks) → keep the mascot's playful "にゃ" voice.

Centralized here so tone can be tuned in one place.
"""
from __future__ import annotations

# --- /register ---

REGISTER_INVALID_KEY = (
    "🐾 にゃ〜、そのfriend keyはヘンだにゃ…\n"
    "`123456_xxxxxxxxxxxx` みたいな形（数字＋アンダースコア＋英数字）で入れてほしいにゃ！"
)


def register_invalid_user(name: str) -> str:
    return (f"🙀 `{name}` っていうPEユーザは見つからなかったにゃ…\n"
            "スペル合ってるかにゃ?")


def register_check_failed() -> str:
    return ("😿 いまPEに確認しにいけなかったにゃ…\n"
            "少し待ってからもう一度 `/register` お願いにゃ。")


def register_limit(limit: int) -> str:
    return (f"😿 ごめんにゃ、参加者が上限（{limit}人）まで埋まっちゃったにゃ…\n"
            "運営さん(@aphelios_like)に相談してほしいにゃ。")


REGISTER_NOTE_VERIFIED = "✅ ちゃんとキミのprogressが読めたにゃ〜。準備OKにゃ！"
REGISTER_NOTE_PENDING = (
    "⏳ まだキミのprogressが読めないにゃ。**PEユーザ名**が"
    "合ってるか確認して、もう一度登録してにゃ！（friend登録は自動でやったにゃ）"
)
REGISTER_NOTE_UNKNOWN = (
    "⏳ うまく確認できなかったにゃ…ユーザ名とfriend登録をもう一度見てみてにゃ。"
)


def register_ok(display_name: str, pe_username: str, note: str, warn: str = "") -> str:
    return (f"😺 **{display_name}** さんが **{pe_username}**で登録完了にゃ！"
            f"ようこそにゃ！\n{note}{warn}")


REGISTER_ACK = "✅ 登録完了にゃ！"


def register_pending(display_name: str, pe_username: str, note: str) -> str:
    return (f"⏳ {display_name}さん、{pe_username} で登録は受け付けたにゃ。"
            f"でもまだ確認できてないにゃ:\n{note}")
REGISTER_PANEL_TEXT = (
    "🐾 **コンテスト参加登録** 🐾\n"
    "下のボタンから、PEユーザ名と friend key を初回登録してにゃ！\n"
)


def create_ack() -> str:
    return "参加受付を開始しました。"


def register_warn(count: int, limit: int) -> str:
    return f"\n⚠️ 参加者 {count}/{limit}人にゃ。そろそろ満員に近いにゃ〜。"


# --- /create_contest ---

NOT_ORGANIZER = "🐾 このコマンドは運営さんだけにゃ。ごめんにゃ！"
BAD_TIME = ("🙀 時刻の書き方がヘンだにゃ。次のどれかで入れてにゃ：\n"
            "・`21:00`（今日）\n・`07-15 21:00`（今年）\n・`2026-07-15 21:00`")
PAST_TIME = "🙀 その時刻はもう過ぎてるにゃ。今日以降の時刻を指定してにゃ！"
NO_PARTICIPANTS = "😿 まだ誰も登録してないにゃ。まず `/register` してもらってにゃ！"


def session_expired(err) -> str:
    return (f"⚠️ PEのセッション切れが発生したにゃ（{err}）\n"
            "運営さん(@aphelios_like)にcookieの貼り直しをお願いするにゃ。")


def unreadable_note(names) -> str:
    joined = ", ".join(names)
    return (f"⚠️ **{joined}**さんは、progressが読めなかったため、**未AC保証の対象外**にしたにゃ。\n"
            "本人に `/register` し直してもらうにゃ。")


def select_fail(err) -> str:
    return (f"😾 条件に合う問題を選べなかったにゃ…（{err}）\n"
            "難易度タイプをゆるめるか、問題数を減らしてみてにゃ。")


def contest_recruiting(name: str, joined_ids: list[int], when: str = "") -> str:
    who = " ".join(f"<@{i}>" for i in joined_ids) if joined_ids else "---"
    head = f"{name} {when}".rstrip()
    return (f"**{head}**\n"
            f"参加登録受付中!\n\n"
            f"参加者: {who}")


def contest_drawn(name: str, when: str, problem_list: str) -> str:
    return (f"**{name}** の問題を抽選しました！\n"
            f"開催: {when}\n\n{problem_list}")


def contest_no_joiners(name: str) -> str:
    return f"**{name}** は参加者不在のため中止となりました。"


def draw_failed(name: str, err) -> str:
    return f"**{name}** は問題抽選に失敗したため中止します（{err}）。"


JOIN_CLOSED = "このコンテストの参加受付は終了していますにゃ"
NOT_JOINED = "このコンテストに参加してないにゃ。次回は受付中に「参加する」を押してにゃ！"


def joined(display_name: str, count: int) -> str:
    return "参加登録をしました"


def left(display_name: str, count: int) -> str:
    return "参加を取り消しました"


CANNOT_LEAVE = "受付終了後は退出できないにゃ。"


def late_join_presolved(pids: list[int]) -> str:
    ps = ", ".join(f"P{p}" for p in pids)
    return (f"\n参加前にAC済みの問題があります: （{ps}）。"
            f"これらは順位表で **x** 扱いになります。")


# --- /submit ---

NOT_REGISTERED = "🐾 初回参加登録がまだにゃ！`/register <PEユーザ名> <friend key>` で登録にゃ。"
NO_RUNNING = "😴 いまは開催中のコンテストがないにゃ。"
NOTHING_TO_SUBMIT = "😺 提出できる問題がもうないにゃ！すごいにゃ。"


def cannot_read_progress() -> str:
    return ("🙀 キミの解答状況が読めないにゃ… オイラとfriend登録できてるか"
            "運営さん(@aphelios_like)に確認してほしいにゃ。")


def submit_batch_ok(display_name: str, newly: list) -> str:
    total = sum(pts for _, pts in newly)
    detail = "、".join(f"P{pid}(+{pts})" for pid, pts in newly)
    return (f"{display_name} さんの{len(newly)}問の新ACを確認しました！"
            f"{detail}計 **+{total}点**")


def submit_none_new() -> str:
    return ("🙀 まだ新しくACとして確認できた問題は見つからなかったにゃ...")


# --- /recommend & /recommendations ---

def recommend_ok(display_name: str, pid: int, title: str) -> str:
    return f"🗳️ Problem {pid}「{title}」を推薦したにゃ！"


def recommend_invalid(pid: int) -> str:
    return f"🙀 Problem {pid} なんて無いにゃ…番号を確認してにゃ。"


def recommend_dup(display_name: str, pid: int) -> str:
    return f"😹 Problem {pid} はもう推薦済みだにゃ。"


def rec_title(display_name: str) -> str:
    return f"🐾 {display_name}さんへのおすすめ問題にゃ"


REC_EMPTY = "😿 おすすめできる問題が見つから無いにゃ。"


# --- /feedback ---

FEEDBACK_ACK = "📨 匿名フィードバックを送ったにゃ！ありがとにゃ〜"
FEEDBACK_EMPTY = "📭 まだフィードバックは無いにゃ。"


def feedback_title(n: int) -> str:
    return f"📨 フィードバック 全{n}件"


def feedback_cleared(n: int) -> str:
    return f"🗑️ 表示していた {n} 件を削除したにゃ。"


# --- /tweet ---

NO_CONTEST_TWEET = "😿 まだツイートできるコンテストが無いにゃ。"


RATING_EMPTY = "まだレーティングがないにゃ。"
RATING_TITLE = "📈 コミュニティレーティング"


def rating_footer() -> str:
    return (f"pe-runner")


def rating_half_life() -> float:
    import rating as _r
    return _r.HALF_LIFE_DAYS


# --- /profile ---

def profile_not_found(pe_username: str) -> str:
    return (f"🙀 `{pe_username}` の登録が見つからなかったにゃ…\n"
            "PEユーザ名のスペルを確認してにゃ。")


def profile_no_rating(pe_username: str) -> str:
    return f"{pe_username}さんはまだレーティングがないにゃ。"


def profile_title(pe_username: str) -> str:
    return f"📊 {pe_username}さんのレーティング"


def profile_body(current: int, delta: int, highest: int, live, n: int) -> str:
    sign = f"+{delta}" if delta >= 0 else str(delta)
    body = f"**{current}** ({sign}) (highest:{highest})\n{n}戦"
    days = int(live["days_inactive"]) if live else 0
    if live and days > 0:
        body += f"\n※ 実効レート **{live['rating']}**"
    return body


def tweet_panel(text: str, url: str) -> str:
    return (f"🐦 最後のコンテスト結果のツイート文だにゃ！下のリンクから投稿してにゃ：\n"
            f"`\n{url}")


# --- /leaderboard & embeds ---

NOT_OWNER = "🐾 これはオーナーだけができるにゃ。ごめんにゃ！"
NOT_BOT_MESSAGE = "🙀 オイラのメッセージだけ消せるにゃ。"
DELETED = "🗑️ 消したにゃ！"

NO_CONTEST = "😿 まだコンテストがないにゃ。"
LB_EMPTY = "まだ提出がありません。"


def lb_title(name: str) -> str:
    return f"🏆 {name} — 順位表"


def lb_footer(max_pts: int, n: int, status: str) -> str:
    label = {"running": "開催中", "finished": "終了", "scheduled": "開始前"}.get(status, status)
    return f"満点 {max_pts}pts / {n}問 · {label} "


def lb_time_line(end_epoch: int, status: str) -> str:
    """Live end-time / remaining line for the leaderboard (Discord dynamic timestamps)."""
    if status == "finished":
        return f"終了しました（<t:{end_epoch}:f>）\n"
    return f"終了 <t:{end_epoch}:t> ・ 残り <t:{end_epoch}:R>\n"


# --- scheduler events ---

def contest_start(name: str, when: str, problem_list: str) -> str:
    return (f"**{name}** 開始です！（{when}）\n"
            f"ACしたら `/submit` で提出してください。\n\n{problem_list}")


def contest_end(name: str) -> str:
    return (f"🏁 **{name}** 終了! おつでしたにゃ")


INTRODUCE = (
    "😺 はじめまして！\n"
    "オイラ、Project Eulerを軸としたコンテストを主催する猫、**オイラーニャン** だにゃ！🐾\n"
    "できること一覧は `/service` を見てにゃ。よろしくにゃ！\n"
    "*（このメッセージは10秒で自動消去にゃ）*"
)


def ready_log(user) -> str:
    return f"😺 {user} でログインしたにゃ！オイラ準備OKにゃ"
