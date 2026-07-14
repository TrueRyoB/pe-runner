"""PEクッキーが有効かを確認する動作チェック。secretは一切出力しない。

    .venv/bin/python tools/check_pe.py

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


def main():
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
    dist = collections.Counter(contest.bucket_of(c.difficulty) or "other"
                               for c in cat.values())
    print("   難易度分布:", dict(sorted(dist.items())))
    excluded = {pid for pid, c in cat.items() if c.solved}
    try:
        picks = contest.select_problems(cat, excluded, "balanced", 6,
                                        rng=random.Random(42))
        print("✅ 選抜ドライラン(balanced, 6問):")
        for p in picks:
            print(f"     P{p['id']} — {p['difficulty']}pt — {p['title']}")
    except ValueError as e:
        print("   選抜エラー:", e)
    print("\n😺 準備OKにゃ！")


if __name__ == "__main__":
    main()
