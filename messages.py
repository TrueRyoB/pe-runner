"""All user-facing text, spoken by the mascot: オイラーにゃん — a friendly,
math-loving cat 🐱. Keep persona consistent: warm, playful, gentle "にゃ" endings.

Centralized here so tone can be tuned in one place.
"""
from __future__ import annotations

# --- /register ---

REGISTER_INVALID_KEY = (
    "🐾 にゃ〜、そのfriend keyはヘンだにゃ…\n"
    "`123456_xxxxxxxxxxxx` みたいな形（数字＋アンダースコア＋英数字）で入れてほしいにゃ！"
)


def register_invalid_user(name: str) -> str:
    return (f"🙀 `{name}` っていうPEユーザーは見つからなかったにゃ…\n"
            "スペル合ってるかニャ、もう一度確認してみて！")


def register_check_failed() -> str:
    return ("😿 いまPEに確認しにいけなかったにゃ…（通信エラーかも）\n"
            "少し待ってからもう一度 `/register` してほしいにゃ。")


def register_limit(limit: int) -> str:
    return (f"😿 ごめんにゃ、参加者が上限（{limit}人）まで埋まっちゃったにゃ…\n"
            "運営さんに相談してほしいにゃ。")


REGISTER_NOTE_VERIFIED = "✅ ちゃんとキミのprogressが読めたにゃ〜。準備OKにゃ！"
REGISTER_NOTE_PENDING = (
    "⏳ まだキミのprogressが読めないにゃ。**PEユーザー名**か**friend key**が"
    "合ってるか確認して、もう一度登録してにゃ！（friend登録は自動でやったにゃ）"
)
REGISTER_NOTE_UNKNOWN = (
    "⏳ うまく確認できなかったにゃ…ユーザー名とfriend登録をもう一度見てみてにゃ。"
)


def register_ok(display_name: str, pe_username: str, note: str, warn: str = "") -> str:
    return (f"😺 **{display_name}** さんが **{pe_username}**（PE）で登録できたにゃ！"
            f"ようこそにゃ〜！\n{note}{warn}")


REGISTER_ACK = "✅ 登録したにゃ！（結果はみんなに公開したにゃ）"
REGISTER_PANEL_TEXT = (
    "🐾 **コンテスト参加登録** 🐾\n"
    "下のボタンから、PEユーザ名と friend key を登録してにゃ！（一度だけでOK）\n"
    "※ friend key は各自のPEアカウントの Account ページで確認できるにゃ。"
)


def create_ack() -> str:
    return "✅ コンテストを作ったにゃ！（みんなに公開したにゃ）"


def register_warn(count: int, limit: int) -> str:
    return f"\n⚠️ 参加者 {count}/{limit}人にゃ。そろそろ満員に近いにゃ〜。"


# --- /create_contest ---

NOT_ORGANIZER = "🐾 このコマンドは運営さんだけにゃ。ごめんにゃ！"
BAD_TIME = ("🙀 時刻の書き方がヘンだにゃ。次のどれかで入れてにゃ：\n"
            "・`21:00`（今日）\n・`07-15 21:00`（今年）\n・`2026-07-15 21:00`")
PAST_TIME = "🙀 その時刻はもう過ぎてるにゃ。今日以降の時刻を指定してにゃ！"
NO_PARTICIPANTS = "😿 まだ誰も登録してないにゃ。まず `/register` してもらってにゃ！"


def session_expired(err) -> str:
    return (f"⚠️ PEのセッションが切れちゃったみたいにゃ…（{err}）\n"
            "運営さんにcookieの貼り直しをお願いするにゃ。")


def unreadable_participants(names) -> str:
    joined = ", ".join(names)
    return (f"🙀 次の参加者のprogressが読めないにゃ: **{joined}**\n"
            "bot のPEアカウントに friend key を追加してから、もう一度作成してにゃ。"
            "（全員未AC保証のため、読めない人がいると作れないにゃ）")


def select_fail(err) -> str:
    return (f"😾 条件に合う問題を選べなかったにゃ…（{err}）\n"
            "難易度タイプをゆるめるか、問題数を減らしてみてにゃ。")


def create_ok(cid: int, name: str, start_epoch: int, duration: int,
              ctype: str, n: int) -> str:
    return (f"😸 コンテスト #{cid} **{name}** を用意したにゃ！\n"
            f"開始: <t:{start_epoch}:F> / {duration}分 / タイプ `{ctype}` / {n}問\n"
            f"（登録者全員がまだ解いてない問題だけ選んだにゃ！）\n"
            f"問題番号は開始時刻に発表するにゃ〜。楽しみにしててにゃ！")


# --- /submit ---

NOT_REGISTERED = ("🐾 まだ参加登録してないにゃ！`/register` で出てくる"
                  "「参加登録するにゃ」ボタンから登録してにゃ！")
NO_RUNNING = "😴 いまは開催中のコンテストがないにゃ〜。"
NOTHING_TO_SUBMIT = "😺 提出できる問題がもうないにゃ！全部AC済みかもにゃ、すごいにゃ〜！"
SELECT_PLACEHOLDER = "ACした問題を選ぶにゃ"
SUBMIT_PROMPT = "😸 どの問題をACしたのニャ？選んでにゃ:"


def cannot_read_progress() -> str:
    return ("🙀 キミの解答状況が読めないにゃ… ぉぃㇻ(bot)とfriend登録できてるか"
            "運営に確認してほしいにゃ。")


def not_solved(pid: int) -> str:
    return (f"🙀 Problem {pid} はまだACとして確認できないにゃ…\n"
            "解けてたら少し待ってからもう一度試してにゃ！")


def already_counted(pid: int) -> str:
    return f"😹 Problem {pid} はもう計上済みだにゃ〜。"


def submit_ok(display_name: str, pid: int, points: int) -> str:
    return (f"🎉 {display_name}さん、Problem {pid} のAC確認したにゃ！ "
            f"+{points}ポイントにゃ〜！やったにゃ！")


# --- /recommend & /recommendations ---

def recommend_ok(display_name: str, pid: int, title: str) -> str:
    return f"🗳️ {display_name}さん、Problem {pid}「{title}」を推薦したにゃ！"


def recommend_invalid(pid: int) -> str:
    return f"🙀 Problem {pid} なんて無いにゃ…番号を確認してにゃ。"


def recommend_dup(display_name: str, pid: int) -> str:
    return f"😹 {display_name}さん、Problem {pid} はもう推薦済みだにゃ〜。"


def rec_title(display_name: str) -> str:
    return f"🐾 {display_name}さんへのおすすめ問題にゃ（人気順・キミが未ACのだけ）"


REC_EMPTY = "😿 おすすめできる問題がまだ無いにゃ（投票が無いか、全部AC済みかも）。"


# --- /tweet ---

NO_CONTEST_TWEET = "😿 まだツイートできるコンテストが無いにゃ。"


RATING_EMPTY = "😿 まだレーティングが無いにゃ（コンテストが1つ終わると付くにゃ）。"
RATING_TITLE = "📈 コミュニティ・レーティングにゃ（AtCoder風・非活動で減衰）"


def rating_footer() -> str:
    return (f"参加時のみ変動・不参加で相対低下なし / "
            f"{int(rating_half_life())}日で半減 · by オイラーにゃん🐾")


def rating_half_life() -> float:
    import rating as _r
    return _r.HALF_LIFE_DAYS


def tweet_panel(text: str, url: str) -> str:
    return (f"🐦 最後のコンテスト結果のツイート文だにゃ！下のリンクから投稿してにゃ：\n"
            f"```\n{text}\n```\n{url}")


# --- /leaderboard & embeds ---

NOT_OWNER = "🐾 これはオーナーだけができるにゃ。ごめんにゃ！"
NOT_BOT_MESSAGE = "🙀 ぉぃㇻ(bot)のメッセージだけ消せるにゃ。"
DELETED = "🗑️ 消したにゃ！"

NO_CONTEST = "😿 まだコンテストがないにゃ。"
LB_EMPTY = "🐾 まだ誰も提出してないにゃ。一番乗りはキミかもにゃ！"


def lb_title(name: str) -> str:
    return f"🏆 {name} — 順位表にゃ"


def lb_footer(max_pts: int, n: int, status: str) -> str:
    label = {"running": "開催中", "finished": "終了", "scheduled": "開始前"}.get(status, status)
    return f"満点 {max_pts}pts / {n}問 · {label} · by オイラーにゃん🐾"


# --- scheduler events ---

def contest_start(name: str, duration: int, problem_list: str) -> str:
    return (f"🚀 **{name}** はじまるにゃ〜！（{duration}分間）みんな頑張るにゃ！\n"
            f"ACしたら `/submit` で教えてにゃ🐾\n\n{problem_list}")


def contest_end(name: str) -> str:
    return (f"🏁 **{name}** おしまいにゃ！おつかれさまにゃ〜！\n"
            "みんなよく頑張ったにゃ😺 結果を見てみてにゃ！")


def ready_log(user) -> str:
    return f"😺 {user} でログインしたにゃ！ぉぃㇻ、オイラーにゃん、準備OKにゃ〜"
