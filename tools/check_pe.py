"""PEクッキーが有効かを確認する動作チェック。secretは一切出力しない。

    .venv/bin/python tools/check_pe.py                 # 認証 + カタログ確認
    .venv/bin/python tools/check_pe.py <PEユーザ名>     # そのfriendのsolve状況を読む

成功すれば全問題数・難易度分布・選抜ドライランを表示。失敗すれば理由と対処を出す。
"""
import collections
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config       # noqa: E402
import contest      # noqa: E402
import pe_client    # noqa: E402


def check_friend(username: str):
    print(f"friend '{username}' の solve 状況を読み取り中...")
    try:
        solved = sorted(pe_client.solved_ids(username))
    except pe_client.ProgressUnavailable as e:
        print("❌", e)
        print("→ bot のPEアカウントに、この人の friend key を追加してにゃ。")
        sys.exit(1)
    except pe_client.SessionExpired as e:
        print("❌ botセッション失効:", e)
        sys.exit(1)
    print(f"✅ 読み取りOK: {len(solved)} 問 solved")
    print("   solved ids:", solved[:40], ("..." if len(solved) > 40 else ""))


def main():
    if len(sys.argv) > 1:
        check_friend(sys.argv[1])
        return
    print("PE_BOT_USERNAME:", config.PE_BOT_USERNAME or "(未設定!)")
    print("cookie names   :", list(pe_client._config_cookies().keys()) or "(なし)")
    print("-" * 50)
    try:
        cat = pe_client.catalog()
    except pe_client.SessionExpired as e:
        print("❌ 認証できないにゃ:", e)
        print("→ ブラウザ(bot用PEアカウントでログイン)のDevTools > Network >")
        print("  projecteuler.net のリクエスト > Request Headers の `Cookie:` を")
        print("  丸ごと .env の PE_COOKIE に貼り直してにゃ。")
        sys.exit(1)
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        sys.exit(1)

    solved = sum(1 for c in cat.values() if c.solved)
    print(f"✅ 認証OK・全 {len(cat)} 問を取得（最大番号 {max(cat)}）")
    print(f"   bot自身: solved={solved} / 未solved={len(cat) - solved}")
    bands = collections.Counter((c.difficulty // 10) * 10 for c in cat.values())
    print("   難易度分布:", {f"{k}-{k + 9}%": bands[k] for k in sorted(bands)})
    excluded = {pid for pid, c in cat.items() if c.solved}
    for tier in contest.CONTEST_TYPES:
        try:
            picks = contest.select_problems(cat, excluded, tier, rng=random.Random(42))
            spec = contest.CONTEST_TYPES[tier]
            print(f"✅ {spec['label']}({tier}): {len(picks)}問 "
                  f"[{', '.join('P%d/%d%%' % (p['id'], p['difficulty']) for p in picks)}]")
        except ValueError as e:
            print(f"   {tier} 選抜エラー:", e)
    print("\n😺 準備OKにゃ！")


if __name__ == "__main__":
    main()
