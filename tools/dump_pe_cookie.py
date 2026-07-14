"""projecteuler.net のセッションcookieをローカルブラウザから取り出して、
.env にそのまま貼れる形で出力する一回きりのセットアップ用ツール。

PHPSESSID は HttpOnly なので `document.cookie` では読めない。このツールはブラウザの
cookie ストア（Chrome/Firefox/Safari/Edge/Brave/Arc 等）から直接読み出す。

前提: 事前にブラウザで projecteuler.net に「Keep me logged in」でログインしておくこと。

使い方:
    pip install browser_cookie3
    python tools/dump_pe_cookie.py            # 全ブラウザを試す
    python tools/dump_pe_cookie.py chrome     # ブラウザ指定
    python tools/dump_pe_cookie.py --list     # 対応ブラウザ一覧

※ macOS で Chrome 系を読むと Keychain のパスワード確認が出ることがある（正常）。
※ 出力にはセッション値（＝機密）が含まれる。人に見せたり貼り付け先を間違えないこと。
"""
import sys

try:
    import browser_cookie3 as bc
except ImportError:
    sys.exit("browser_cookie3 が未インストールにゃ。`pip install browser_cookie3` を実行してにゃ。")

DOMAIN = "projecteuler.net"

# 名前 -> loader。存在しないものは getattr で除外。
_CANDIDATES = ["chrome", "chromium", "brave", "edge", "opera", "opera_gx",
               "vivaldi", "arc", "firefox", "librewolf", "safari"]
BROWSERS = {name: getattr(bc, name) for name in _CANDIDATES if hasattr(bc, name)}


def cookies_from(loader) -> dict:
    jar = loader(domain_name=DOMAIN)
    return {c.name: c.value for c in jar}


def emit(name: str, cookies: dict) -> bool:
    if not cookies:
        return False
    print(f"\n=== {name}: {DOMAIN} の cookie が見つかったにゃ 🐾 ===")
    if "PHPSESSID" in cookies:
        print("↓ この行を .env にそのまま貼るにゃ:")
        print(f"PE_SESSION_COOKIE=PHPSESSID={cookies['PHPSESSID']}")
    else:
        print("⚠️ PHPSESSID が無いにゃ。ログイン状態か確認してにゃ。")
    # 永続(remember me)系がもしあれば PE_KEEP_ALIVE_COOKIE 候補として出す。
    for k in cookies:
        if k == "PHPSESSID":
            continue
        low = k.lower()
        if "keep" in low or "remember" in low or "login" in low:
            print(f"PE_KEEP_ALIVE_COOKIE={k}={cookies[k]}")
    print("（このブラウザにある全cookie名: " + ", ".join(cookies) + "）")
    return True


def main():
    args = sys.argv[1:]
    if args and args[0] in ("--list", "-l"):
        print("対応ブラウザ:", ", ".join(BROWSERS))
        return
    targets = args or list(BROWSERS)
    found_any = False
    for name in targets:
        loader = BROWSERS.get(name)
        if loader is None:
            print(f"[{name}] 未対応/未検出にゃ（--list で一覧を確認）")
            continue
        try:
            cookies = cookies_from(loader)
        except Exception as e:
            print(f"[{name}] 読めなかったにゃ: {e}")
            continue
        if emit(name, cookies):
            found_any = True
    if not found_any:
        print("\n😿 どのブラウザにも projecteuler.net の cookie が見つからなかったにゃ。")
        print("   → そのブラウザで projecteuler.net にログインしてから、もう一度試してにゃ。")
        print("   → 特定ブラウザを指定するには: python tools/dump_pe_cookie.py chrome")


if __name__ == "__main__":
    main()
